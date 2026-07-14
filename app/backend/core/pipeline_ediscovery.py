#!/usr/bin/env python3
# [Flow: Step 1 (PDF 텍스트 레이어 추출) -> Step 2 (페이지 단위 부모 청크 + 슬라이딩 윈도우 자식 청크 생성)
#       -> Step 3 (vLLM Proxy 호출로 청크별 쟁점/증거 노드 JSON 추출) -> Step 4 (신뢰도 임계값 필터링)
#       -> Step 5 (중복 제거 + 엣지 조립으로 그래프 구성) -> Step 6 (jobs 테이블 상태/결과 갱신)]
# e-Discovery GraphRAG 추출 파이프라인.
# 수천 장 단위의 법률 문서에서 쟁점(issue)/원고(plaintiff)/피고(defendant)/증거(evidence) 노드를
# 추출해 React Flow 시각화용 그래프 JSON으로 조립한다.
# xlsx_advanced_converter.run 과 동일한 job 상태 갱신/환불 가능 패턴을 따른다.
import json
import logging
import re
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from .. import settings_store
from ..config import settings
from ..core import points_service, supabase_client
from ..core.ocr_client import call_text
from ..db.models import Job, User
from ..db.session import SessionLocal

logger = logging.getLogger(__name__)


# --- 크레딧 차감 유틸리티 ------------------------------------------------------
# [Flow: Step 1 (user_id 유효성 확인) -> Step 2 (별도 DB 세션 생성) -> Step 3 (사용자 조회)
#       -> Step 4 (1 credit 차감) -> Step 5 (세션 닫기)]
# 병렬 스레드에서도 메인 SQLAlchemy 세션을 공유하지 않고 1 step = 1 credit(1000 milli-USD)를 차감한다.
# 차감 실패는 로깅만 하고 파이프라인을 중단하지 않는다.
def _spend_agent_step_for_call(user_id: str | uuid.UUID | None, description: str) -> None:
    if not user_id:
        return
    db = SessionLocal()
    try:
        user = db.get(User, uuid.UUID(str(user_id)))
        if user:
            points_service.spend_agent_step(db, user, description)
            db.commit()
    except Exception as e:
        logger.warning(f"[ediscovery] step 크레딧 차감 실패 user={user_id} desc={description}: {e}")
    finally:
        db.close()


# --- 튜닝 상수 ---------------------------------------------------------------
DEFAULT_CHUNK_SIZE = 512          # 자식 청크 토큰(단어) 수
DEFAULT_OVERLAP = 64              # 슬라이딩 윈도우 overlap
DEFAULT_THRESHOLD = 0.5           # 노드 신뢰도 임계값
MAX_LLM_WORKERS = 16              # vLLM 동시 호출 상한 (settings.llm_max_workers 보다 보수적)
MAX_NODES_PER_GRAPH = 5000        # 그래프 노드 수 상한 (JSONB 크기 폭증 방지)
MAX_CHARS_PER_CHUNK = 8000        # 청크당 LLM 전달 텍스트 상한 (토큰 폭증 방지)
MAX_ANOMALY_NODES = 200           # 2차 anomaly 탐지에 전달할 노드 수 상한 (비용/지연 폭증 방지)
PAGE_MARKER_RE = re.compile(r"<!--\s*(?:페이지|page)\s*(\d+)\s*-->", re.IGNORECASE)
# 날짜 표현 정규화용 정규식 — 한국식(년/월/일)/일본식(年/月/日)/서양식(. - /) 모두 처리
# LLM이 상대 표현을 절대 날짜로 환산해 "YYYY-MM-DD"뿐 아니라 "YYYY년 4월"/"YYYY-MM"(연/월만 아는 경우)로
# 반환할 수도 있으므로 연-월만 있는 형태도 함께 매칭한다 (타임라인 시간순 정렬 정확도 향상).
DATE_RE = re.compile(
    r"(\d{4})\s*(?:년|年|\.|\-|/)\s*(\d{1,2})\s*(?:월|月|\.|\-|/)\s*(\d{1,2})\s*(?:일|日)?"
    r"|(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})"
    r"|(\d{4})\s*(?:년|年)\s*(\d{1,2})\s*(?:월|月)"
    r"|(\d{4})\s*[-/]\s*(\d{1,2})(?!\s*[-/]\s*\d)",
    re.IGNORECASE,
)
# 유효한 노드 타입 + 행위 주체 분류값
VALID_NODE_TYPES = {"issue", "plaintiff", "defendant", "evidence"}
VALID_ENTITY_TYPES = {"plaintiff", "defendant", "third_party", "issue"}
# swimlane 노드 ID 고정 매핑 — 주체별 최상위 부모 노드
SWIMLANE_IDS = {
    "plaintiff": "swimlane_plaintiff",
    "defendant": "swimlane_defendant",
    "third_party": "swimlane_third_party",
    "issue": "swimlane_issue",
}


# --- 데이터 클래스 -----------------------------------------------------------
@dataclass
class EdiscoveryNode:
    """e-Discovery 그래프의 단일 노드 — 쟁점/원고/피고/증거/제3자 중 하나.

    시간순 타임라인 + 주체별 스윔레인 배치를 위해 entity/date_text/summary/parent_id를 보존한다.
    """
    id: str
    type: str               # issue | plaintiff | defendant | evidence
    label: str
    page: int               # 1-based 페이지 번호
    confidence: float = 1.0 # 0.0 ~ 1.0 신뢰도 (임계값 필터링용)
    entity: str = ""        # 행위 주체 분류: plaintiff | defendant | third_party | issue
    date_text: str = ""     # 원본 날짜 표현 (예: "2023년 4월 5일")
    date_iso: str = ""      # 정규화된 ISO 날짜 (예: "2023-04-05") — 시간순 정렬용
    summary: str = ""       # 1~2문 요약 — 점진적 탐색 패널 표시용
    connection_reason: str = "" # 해당 페이지 원문에서 이 노드를 추출한 근거 (LLM이 설명)
    parent_id: str = ""     # 소속 swimlane 노드 ID (assemble_graph에서 주입)
    source_file: str = ""   # 원본 파일명 (SourcePanel에서 파일 전환용)
    original_page: int = 0    # 원본 파일 내 페이지 번호 (1-based, 0이면 미상)
    meta: dict = field(default_factory=dict)


@dataclass
class ChildChunk:
    """슬라이딩 윈도우로 분할된 자식 청크 — 페이지 메타데이터를 보존한다."""
    page_no: int
    text: str
    index: int              # 같은 페이지 내 청크 순번
    source_file: str = ""   # 원본 파일명 (global page가 어떤 파일에서 왔는지 추적)
    original_page: int = 0   # 원본 파일 내 페이지 번호 (1-based, 0이면 미상)


# --- 텍스트 추출 -------------------------------------------------------------
def _download_pdf_bytes(job: Job) -> bytes | None:
    """[Flow: Step 1 (searchable_pdf 우선 다운로드) -> Step 2 (실패 시 원본 pdf_storage_path) -> Step 3 (bytes 반환)]

    검색 가능한 텍스트 레이어가 있는 PDF를 우선 사용하고, 없으면 원본 PDF를 사용한다.
    """
    client = supabase_client.get_service_client()
    for storage_path in (job.searchable_pdf_storage_path, job.pdf_storage_path):
        if not storage_path:
            continue
        try:
            return client.storage.from_("pdfs").download(storage_path).read()
        except Exception:
            try:
                return supabase_client.download_pdf(storage_path).read()
            except Exception as e:
                logger.warning(f"[ediscovery] PDF 다운로드 실패 path={storage_path}: {e}")
    return None


def _download_storage_bytes(bucket: str, path: str) -> bytes | None:
    """[Flow: Step 1 (Storage에서 객체 다운로드 시도) -> Step 2 (실패 시 download_pdf 폴백) -> Step 3 (bytes 또는 None 반환)]

    지정한 버킷과 경로의 파일을 Supabase Storage에서 다운로드한다.
    """
    client = supabase_client.get_service_client()
    try:
        return client.storage.from_(bucket).download(path).read()
    except Exception:
        try:
            return supabase_client.download_pdf(path).read()
        except Exception:
            return None


def _extract_page_texts_from_pdf(pdf_bytes: bytes) -> dict[int, str]:
    """[Flow: Step 1 (PyMuPDF로 PDF 열기) -> Step 2 (페이지별 blocks 텍스트 결합) -> Step 3 (page_no → 텍스트 맵 반환)]

    PDF 텍스트 레이어에서 페이지별 전체 텍스트를 추출한다.
    pdf_annotate_converter._collect_page_elements_from_searchable_pdf 와 동일 방식.
    """
    page_texts: dict[int, str] = {}
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_idx in range(doc.page_count):
            page = doc[page_idx]
            blocks = page.get_text("blocks")
            parts = []
            for block in blocks:
                try:
                    text = block[4]
                except Exception:
                    continue
                if text and text.strip():
                    parts.append(text.strip())
            page_texts[page_idx + 1] = "\n".join(parts)
    finally:
        doc.close()
    return page_texts


def _extract_page_texts_from_markdown(markdown: str) -> dict[int, str]:
    """[Flow: Step 1 (페이지 마커 정규식 매칭) -> Step 2 (마커 사이 텍스트 분할) -> Step 3 (page_no → 텍스트 맵 반환)]

    텍스트 레이어가 없는 스캔 PDF의 폴백: 변환 결과 마크다운을 페이지 마커로 분할.
    마커가 없으면 전체를 1페이지로 취급한다.
    """
    matches = list(PAGE_MARKER_RE.finditer(markdown))
    if not matches:
        stripped = markdown.strip()
        return {1: stripped} if stripped else {}
    page_texts: dict[int, str] = {}
    for idx, match in enumerate(matches):
        page_num = int(match.group(1))
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(markdown)
        content = markdown[start:end].strip()
        if content:
            page_texts[page_num] = content
    return page_texts


def _download_source_file_bytes(info: dict, job: Job) -> bytes | None:
    """[Flow: Step 1 (info에 storage_path가 있으면 우선 사용)
          -> Step 2 (없으면 job.pdf_storage_path 폴더 또는 pdfs/{job.id}/{path} 후보 생성)
          -> Step 3 (후보 중 다운로드 성공한 bytes 반환)]

    extracted_files 항목의 원본 파일을 Storage에서 다운로드한다.
    폴더 업로드 등으로 storage_path가 비어 있을 경우 후보 경로를 유추해 시도한다.
    """
    storage_path = info.get("storage_path", "")
    if storage_path:
        bucket = info.get("bucket", "pdfs")
        return _download_storage_bytes(bucket, storage_path)

    path = info.get("path", "")
    if not path:
        return None

    candidates: list[tuple[str, str]] = []
    pdf_storage = job.pdf_storage_path or ""
    if pdf_storage.endswith("/"):
        # pdf_storage_path 자체가 폴더 prefix인 경우
        candidates.append((info.get("bucket", "pdfs"), f"{pdf_storage}{path}"))
    else:
        # 일반적인 배치: pdfs/{job.id}/{filename}
        candidates.append(("pdfs", f"{job.id}/{path}"))
        # pdf_storage_path의 디렉터리 부분을 prefix로 시도
        if "/" in pdf_storage:
            folder = pdf_storage.rsplit("/", 1)[0]
            candidates.append(("pdfs", f"{folder}/{path}"))

    for bucket, candidate in candidates:
        data = _download_storage_bytes(bucket, candidate)
        if data:
            return data
    return None


def _extract_page_texts_from_source_file(info: dict, job: Job) -> dict[int, str]:
    """[Flow: Step 1 (파일 메타데이터 파싱) -> Step 2 (searchable PDF 우선 다운로드/추출)
          -> Step 3 (빈 페이지면 원본 PDF/마크다운 폴백) -> Step 4 (page_no → 텍스트 맵 반환)]

    extracted_files의 단일 항목에서 페이지별 텍스트를 추출한다.
    PDF뿐 아니라 docx/hwp/image의 searchable PDF 폴백, file 타입의 result_markdown도 처리한다.
    폴더 업로드 등 storage_path가 없는 경우에도 job 정보를 이용해 파일을 찾는다.
    """
    ftype = info.get("type", "")
    result_markdown = info.get("result_markdown", "")
    searchable_path = info.get("searchable_pdf_storage_path", "")

    # Step 1: searchable PDF가 있으면 가장 먼저 시도 (텍스트 레이어 최적)
    if searchable_path:
        pdf_bytes = _download_storage_bytes("pdfs", searchable_path)
        if pdf_bytes:
            try:
                page_texts = _extract_page_texts_from_pdf(pdf_bytes)
                if any(t.strip() for t in page_texts.values()):
                    return page_texts
            except Exception as e:
                logger.warning(f"[ediscovery] searchable PDF 추출 실패 {searchable_path}: {e}")

    # Step 2: PDF/문서/이미지 원본을 PDF로 파싱 시도
    if ftype in ("pdf", "docx", "hwp", "image"):
        pdf_bytes = _download_source_file_bytes(info, job)
        if pdf_bytes:
            try:
                page_texts = _extract_page_texts_from_pdf(pdf_bytes)
                if any(t.strip() for t in page_texts.values()):
                    return page_texts
            except Exception as e:
                path = info.get("storage_path") or info.get("path", "unknown")
                logger.warning(f"[ediscovery] 원본 PDF 추출 실패 {path}: {e}")

    # Step 3: 마크다운 폴백
    if result_markdown:
        md_bytes = _download_storage_bytes("results", result_markdown)
        if md_bytes:
            try:
                return _extract_page_texts_from_markdown(md_bytes.decode("utf-8"))
            except Exception as e:
                logger.warning(f"[ediscovery] result_markdown 파싱 실패 {result_markdown}: {e}")

    return {}


def _extract_all_source_files(job: Job) -> tuple[dict[int, str], dict[int, dict]]:
    """[Flow: Step 1 (job.extracted_files 순회) -> Step 2 (각 파일별 텍스트 추출)
          -> Step 3 (전역 페이지 번호 부여 + 출처 접두사 추가 + page_meta 기록)
          -> Step 4 (통합 page_texts와 page_meta 반환)]

    job에 속한 모든 자료(PDF/문서/이미지 searchable PDF/file 마크다운)를 페이지 단위로 결합한다.
    단일 파일 분석이 아니라 job 전체를 하나의 문서 세트로 처리할 수 있게 한다.
    반환하는 page_meta는 각 글로벌 페이지가 어떤 원본 파일의 몇 페이지인지 추적한다.
    """
    files = job.extracted_files or []
    combined: dict[int, str] = {}
    page_meta: dict[int, dict] = {}
    global_page = 0

    for info in files:
        if not isinstance(info, dict):
            continue
        ftype = info.get("type", "")
        if ftype in ("audio", "video"):
            # 오디오/비디오는 현재 텍스트 추출이 별도로 지원되지 않음
            continue

        file_page_texts = _extract_page_texts_from_source_file(info, job)
        if not file_page_texts:
            continue

        # sourceFiles.name과 정확히 일치하도록 info.path 전체를 우선 사용한다.
        filename = info.get("path") or info.get("storage_path") or "unknown"
        for page_no in sorted(file_page_texts.keys()):
            text = file_page_texts[page_no].strip()
            if not text:
                continue
            global_page += 1
            combined[global_page] = f"[출처: {filename} 원본 {page_no}페이지]\n{text}"
            page_meta[global_page] = {"source_file": filename, "original_page": page_no}

    if combined:
        logger.info(f"[ediscovery] extracted_files에서 {len(combined)}페이지 추출 ({len(files)}개 파일 중)")
    return combined, page_meta


def extract_page_texts(job: Job) -> tuple[dict[int, str], dict[int, dict]]:
    """[Flow: Step 1 (job.extracted_files가 있으면 전체 소스 파일 집계 + page_meta)
          -> Step 2 (빈 경우 기존 단일 PDF 폴백) -> Step 3 (page_no → 텍스트 맵 반환)]

    업로드된 모든 자료를 e-Discovery 분석 대상으로 포함한다.
    job에 여러 파일이 있을 때 파일당 하나씩 분석하지 않고, job 전체를 통합해 분석한다.
    반환: (page_texts, page_meta) — page_meta는 각 글로벌 페이지의 원본 파일/페이지 추적용.
    """
    page_meta: dict[int, dict] = {}

    if job.extracted_files:
        combined, page_meta = _extract_all_source_files(job)
        if combined:
            return combined, page_meta

    # 단일 파일 업로드 하위 호환: job.searchable_pdf_storage_path → job.pdf_storage_path → 마크다운 폴백
    # pdf_storage_path가 폴더 prefix이면 단일 파일이 아니므로 건너뛴다.
    if job.pdf_storage_path and not job.pdf_storage_path.endswith("/"):
        pdf_bytes = _download_pdf_bytes(job)
        filename = job.pdf_storage_path or ""
    else:
        pdf_bytes = None
        filename = ""
    if pdf_bytes:
        page_texts = _extract_page_texts_from_pdf(pdf_bytes)
        non_empty = sum(1 for t in page_texts.values() if t.strip())
        if non_empty > 0:
            logger.info(f"[ediscovery] PDF 텍스트 레이어에서 {non_empty}페이지 추출")
            for p in sorted(page_texts.keys()):
                page_meta[p] = {"source_file": filename, "original_page": p}
            return page_texts, page_meta
        logger.info("[ediscovery] PDF 텍스트 레이어가 비어 있어 마크다운 폴백 사용")

    # 마크다운 폴백
    client = supabase_client.get_service_client()
    for storage_path in (job.result_edited_md_storage_path, job.result_md_storage_path):
        if not storage_path:
            continue
        try:
            markdown = client.storage.from_("results").download(storage_path).decode("utf-8")
            page_texts = _extract_page_texts_from_markdown(markdown)
            if page_texts:
                logger.info(f"[ediscovery] 마크다운에서 {len(page_texts)}페이지 추출: {storage_path}")
                filename = storage_path or ""
                for p in sorted(page_texts.keys()):
                    page_meta[p] = {"source_file": filename, "original_page": p}
                return page_texts, page_meta
        except Exception as e:
            logger.warning(f"[ediscovery] 마크다운 다운로드 실패 path={storage_path}: {e}")
    return {}, {}


# --- 청킹 -------------------------------------------------------------------
def _split_into_words(text: str) -> list[str]:
    """텍스트를 공백 기준 단어 목록으로 분할한다 (토큰 근사치)."""
    return text.split()


def _words_to_text(words: list[str]) -> str:
    """단어 목록을 다시 텍스트로 결합한다."""
    return " ".join(words)


def build_parent_child_chunks(
    page_texts: dict[int, str],
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
    page_range: list[int] | None = None,
    page_meta: dict[int, dict] | None = None,
) -> list[ChildChunk]:
    """[Flow: Step 1 (page_range 필터링) -> Step 2 (페이지별 단어 분할) -> Step 3 (슬라이딩 윈도우 자식 청크 생성)
          -> Step 4 (청크 텍스트 길이 상한 적용 + page_meta 주입) -> Step 5 (ChildChunk 목록 반환)]

    부모 청크 = 페이지 전체 텍스트 (컨텍스트 보존).
    자식 청크 = 단어 단위 슬라이딩 윈도우 (chunk_size 단어, overlap 단위 겹침).
    페이지 메타데이터(page_no)와 원본 파일 정보(source_file/original_page)를 각 자식 청크에 보존한다.
    """
    if chunk_size <= 0:
        chunk_size = DEFAULT_CHUNK_SIZE
    if overlap < 0 or overlap >= chunk_size:
        overlap = DEFAULT_OVERLAP

    page_set = set(page_range) if page_range else set()
    meta = page_meta or {}
    chunks: list[ChildChunk] = []
    for page_no in sorted(page_texts.keys()):
        if page_set and page_no not in page_set:
            continue
        words = _split_into_words(page_texts[page_no])
        if not words:
            continue
        page_meta_info = meta.get(page_no, {})
        source_file = page_meta_info.get("source_file", "")
        original_page = page_meta_info.get("original_page", 0)
        step = chunk_size - overlap
        index = 0
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            text = _words_to_text(words[start:end])
            if len(text) > MAX_CHARS_PER_CHUNK:
                text = text[:MAX_CHARS_PER_CHUNK]
            chunks.append(ChildChunk(
                page_no=page_no, text=text, index=index,
                source_file=source_file, original_page=original_page,
            ))
            if end >= len(words):
                break
            start += step
            index += 1
    return chunks


# --- 노드 추출 (vLLM 호출) --------------------------------------------------
def _normalize_date(text: str) -> str:
    """[Flow: Step 1 (DATE_RE 매칭) -> Step 2 (연/월/일 추출) -> Step 3 (ISO YYYY-MM-DD 문자열 반환)]

    노드에서 추출한 날짜 표현을 ISO 형식(YYYY-MM-DD)으로 정규화한다.
    월/일이 누락된 경우 01로 채운다. 매칭 실패 시 빈 문자열 반환.
    시간순 타임라인 정렬에 사용된다.
    """
    if not text:
        return ""
    m = DATE_RE.search(text)
    if not m:
        return ""
    # 그룹 우선순위: (Y, M, D) | (Y, M, D) | (Y, M) | (Y, M) — 마지막은 연/월만 있는 "YYYY-MM" 형태
    year = m.group(1) or m.group(4) or m.group(7) or m.group(9)
    month = m.group(2) or m.group(5) or m.group(8) or m.group(10) or "01"
    day = m.group(3) or m.group(6) or "01"
    try:
        y, mo, d = int(year), int(month), int(day)
        if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            return ""
        return f"{y:04d}-{mo:02d}-{d:02d}"
    except (TypeError, ValueError):
        return ""


def _classify_entity(node_type: str, item_entity: str) -> str:
    """[Flow: Step 1 (item_entity 우선 검증) -> Step 2 (node_type 기반 폴백) -> Step 3 (VALID_ENTITY_TYPES 중 하나 반환)]

    노드의 행위 주체 분류값을 결정한다. LLM이 명시한 entity를 우선하고,
    누락 시 노드 타입에서 추론한다. issue 노드는 항상 issue 레인에 배치.
    """
    raw = str(item_entity or "").lower().strip()
    if raw in VALID_ENTITY_TYPES:
        return raw
    if node_type == "plaintiff":
        return "plaintiff"
    if node_type == "defendant":
        return "defendant"
    if node_type == "issue":
        return "issue"
    # evidence는 기본적으로 제3자 레인(미분류)에 배치 — assemble_graph에서 관련 주체로 재매핑 가능
    return "third_party"


def _build_extraction_prompt(chunk_text: str, page_no: int, context: str = "", user_language: str = "ko") -> str:
    """[Flow: Step 1 (노드 타입/필드 안내) -> Step 2 (JSON 스키마 명시)
          -> Step 3 (일지/명단/계약 등 비소송 자료 포함 주의사항) -> Step 4 (청크 텍스트 삽입)]

    청크 텍스트에서 쟁점/원고/피고/증거 노드를 추출하는 LLM 프롬프트를 구성한다.
    시간순 타임라인 + 주체별 스윔레인 배치를 위해 entity/date/summary 필드를 함께 추출한다.
    반환 JSON 스키마는 프론트엔드/AI 백엔드 데이터 계약을 따른다.
    """
    context_section = ""
    if context:
        context_section = f"""
Below is additional context about the key/important matters of the project provided by the user. Prioritize this context when extracting key issues, plaintiff/defendant parties, and evidence. If the context conflicts with the document, prioritize the document.
Additional context: {context}
"""
    return f"""Below is a partial text extracted from page {page_no} (global page number) of the document.
{context_section}Extract the following 4 types of nodes from this text.
You must also extract people, companies, dates, transactions, and documents that appear in logs, lists, contracts, reports, meeting minutes, transaction records, etc., not just litigation documents, according to the criteria below.

- issue: The core issue, transaction, event, conflict, or important factual relationship in the document.
  Examples: "2023-04-05 loan repayment claim", "Contract breach with Company A", "Allegation of B's resignation and NDA violation"
- plaintiff: The party making the claim/assertion/demand, or the party claiming to have suffered damage.
  Examples: plaintiff, creditor, complainant, audit requester, party requesting contract termination
- defendant: The party responding to, denying, or defending against the claim.
  Examples: defendant, debtor, accused, party objecting to contract termination
- evidence: Documents, records, physical evidence, or testimony that support the factual relationship.
  Examples: logs, lists, account statements, emails, recordings, photos, contracts, expert reports

Return each node in the following JSON format. Return only a JSON array (no other explanation, markdown, or code fences).
[
  {{
    "type": "issue | plaintiff | defendant | evidence",
    "label": "Concise summary in the user's configured language ({user_language}) (core content)",
    "entity": "plaintiff | defendant | third_party | issue",
    "date": "Absolute date in YYYY-MM-DD format (must use this format if inferable). If only year/month is available, use YYYY-MM; otherwise empty string.",
    "summary": "1-2 sentence detailed explanation. Include more specific context than the label.",
    "connection_reason": "The reason this node was extracted from the original page text. Explain in 1-2 sentences which phrase/record/fact is the source (e.g., 'Based on A's statement in the investigation record page 3 that A lent B 10 million won').",
    "confidence": 0.0~1.0
  }}
]

⚠️ The date field is the sorting key for the timeline that arranges all nodes chronologically, so treat it as the most important:
- Fill the absolute date normalized as YYYY-MM-DD for any date verifiable in this page (and given context). Example: "April 5, 2023" → "2023-04-05".
- Even if no absolute date is directly written, calculate relative expressions ("next day", "3 days later", "one week after that", "20th of the same month", "early next month") into absolute dates using another absolute date in the same page/paragraph as the reference. If the reference date has already been extracted as another node, use that date as the reference.
- If only the year differs and month/day are missing, do not fill arbitrarily like "YYYY-01-01"; use only what is known, such as "YYYY" or "YYYY-MM" (the code later will normalize separately).
- Only leave the date empty if there is no evidence anywhere in the text to infer it. If any date information exists, never leave it empty.
- If multiple dates are mentioned for the same event (e.g., contract date and violation date), use the date of the actual event as date and describe other dates in summary.

Notes:
- Names of people, companies/organizations, dates, amounts, and document/record names appearing in the text must be extracted as nodes.
- Even for logs, lists, or transaction records, if a specific person/company/date/fact is mentioned, classify them as plaintiff/defendant/issue/evidence.
- entity classifies the acting subject of the node. issue nodes are "issue", claim/plaintiff side is "plaintiff", response/defendant side is "defendant", and other third parties/experts/witnesses/neutral records are "third_party".
- summary is a 1-2 sentence explanation more specific than the label (displayed in the progressive exploration panel).
- connection_reason must be based on the original page text, not the label/summary, explaining the link to the source.
- confidence is the degree to which the node clearly appears in the text (0.0=uncertain, 1.0=clear).
- label should be concise, in the user's configured language ({user_language}), preferably within 20 characters.
- Return an empty array [] only when the text contains no relevant information. If information exists, you must create nodes.

--- Text ---
{chunk_text}
"""


def _build_fallback_extraction_prompt(chunk_text: str, page_no: int, context: str = "", user_language: str = "ko") -> str:
    """[Flow: Step 1 (폴백 추출 지시) -> Step 2 (JSON 스키마 명시) -> Step 3 (청크 텍스트 삽입)]

    1차 법률 노드 추출이 빈 결과를 낸 경우, 텍스트에 등장하는 사람/기관/날짜/거래/문서/사실을
    보다 개방적으로 추출하기 위한 폴백 프롬프트를 구성한다.
    """
    context_section = ""
    if context:
        context_section = f"""
Below is additional context about the key/important matters of the project provided by the user. Prioritize this context when extracting key people, companies/organizations, dates, transactions/events, and documents/records. If the context conflicts with the document, prioritize the document.
Additional context: {context}
"""
    return f"""Extract all people, companies/organizations, dates, transactions/events, and documents/records that appear in the page {page_no} text below.
{context_section}Extract key information even from non-litigation documents such as logs, lists, contracts, reports, transaction records, and meeting minutes.

Classify the extracted items into the following 4 types and return only a JSON array (no other explanation):
- issue: A factual relationship with a specific event, transaction, conflict, or date specified.
- plaintiff: The party making the claim/demand/assertion (plaintiff, creditor, complainant, requester).
- defendant: The party responding to, denying, or defending against the claim (defendant, debtor, accused).
- evidence: Documents, logs, lists, transaction records, recordings, photos, expert reports that support the factual relationship.

[
  {{
    "type": "issue | plaintiff | defendant | evidence",
    "label": "Concise summary in the user's configured language ({user_language})",
    "entity": "plaintiff | defendant | third_party | issue",
    "date": "Absolute date in YYYY-MM-DD format (must use this format if inferable). If only year/month is available, use YYYY-MM; otherwise empty string.",
    "summary": "1-2 sentence detailed explanation",
    "connection_reason": "The reason this node was extracted from the original page text. Explain in 1-2 sentences which phrase/record/fact is the source.",
    "confidence": 0.0~1.0
  }}
]

⚠️ The date field is the sorting key for the timeline that arranges all nodes chronologically, so treat it as the most important:
- Even if no absolute date is directly written, calculate relative expressions ("next day", "3 days later", "20th of the same month") into absolute dates (YYYY-MM-DD) using another absolute date in the same page/paragraph as the reference.
- Only leave the date empty if there is no evidence anywhere to infer it.

Notes:
- Extract any person name, company name, date, amount, or document name visible in the text as nodes.
- If the related subject is unknown, set entity to "third_party".
- Create nodes even if no date is available but other information exists.
- connection_reason must be based on the original page text.

--- Text ---
{chunk_text}
"""


def _extract_fallback_nodes(
    chunks: list[ChildChunk],
    endpoint: str,
    model: str,
    api_key: str,
    context: str = "",
    max_sample: int = 5,
    user_id: str | uuid.UUID | None = None,
    user_language: str = "ko",
) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (청크 존재 여부 확인) -> Step 2 (대표 청크 샘플링)
          -> Step 3 (폴백 프롬프트로 1 step 크레딧 차감 + LLM 호출) -> Step 4 (노드 파싱/취합)
          -> Step 5 (label+type 기준 중복 제거) -> Step 6 (노드 목록 반환)]

    1차 노드 추출이 0개일 때, 문서 전체를 소급(retrospective) 검토하는 폴백 추출을 수행한다.
    너무 많은 청크를 다시 호출하면 비용이 폭증하므로 최대 max_sample개의 대표 청크만 사용한다.
    각 샘플 청크의 LLM 호출 직전에 1 step 크레딧을 차감한다.
    """
    if not chunks:
        return []

    step = max(1, len(chunks) // max_sample)
    sample_chunks = chunks[::step][:max_sample]

    all_nodes: list[EdiscoveryNode] = []
    for chunk in sample_chunks:
        _spend_agent_step_for_call(user_id, "AI agent: e-Discovery fallback node extraction")
        prompt = _build_fallback_extraction_prompt(chunk.text, chunk.page_no, context=context, user_language=user_language)
        try:
            content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=2000)
            all_nodes.extend(_parse_nodes(
                content, chunk.page_no,
                source_file=chunk.source_file, original_page=chunk.original_page,
            ))
        except Exception as e:
            logger.warning(f"[ediscovery] 폴백 청크 추출 실패 page={chunk.page_no}: {e}")

    seen: set[tuple[str, str]] = set()
    unique_nodes: list[EdiscoveryNode] = []
    for node in all_nodes:
        key = (node.label, node.type)
        if key in seen:
            continue
        seen.add(key)
        unique_nodes.append(node)

    logger.info(f"[ediscovery] 폴백 추출로 {len(unique_nodes)}개 노드 생성 (샘플 청크 {len(sample_chunks)}개)")
    return unique_nodes


def _strip_json_fence(content: str) -> str:
    """LLM 응답에서 ```json ... ``` 펜스를 제거한다."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _parse_nodes(content: str, page_no: int, source_file: str = "", original_page: int = 0) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱: 객체이면 리스트로 변환)
          -> Step 3 (노드 스키마 검증/변환 + entity/date/summary + source_file/original_page 추출)
          -> Step 4 (EdiscoveryNode 목록 반환)]

    LLM 응답 문자열을 EdiscoveryNode 목록으로 변환한다.
    entity/date/summary 필드를 함께 파싱해 시간순 정렬 + 스윔레인 배치 + 점진적 탐색에 활용한다.
    source_file/original_page는 SourcePanel에서 원본 파일을 전환하고 해당 페이지로 스크롤하는 데 사용한다.
    스키마에 맞지 않는 항목은 건너뛴다.
    """
    cleaned = _strip_json_fence(content)
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[ediscovery] 노드 JSON 파싱 실패 page={page_no}: {cleaned[:200]}")
        return []
    if isinstance(items, dict):
        # 단일 객체 반환 시 리스트로 감싸서 처리
        items = [items]
    if not isinstance(items, list):
        logger.warning(f"[ediscovery] 노드 파싱 실패 page={page_no}: list/dict가 아님 ({type(items).__name__})")
        return []

    nodes: list[EdiscoveryNode] = []
    skipped = 0
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            skipped += 1
            continue
        node_type = str(item.get("type", "")).lower().strip()
        if node_type not in VALID_NODE_TYPES:
            skipped += 1
            continue
        label = str(item.get("label", "")).strip()
        if not label:
            skipped += 1
            continue
        try:
            confidence = float(item.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = max(0.0, min(1.0, confidence))
        date_text = str(item.get("date", "")).strip()
        date_iso = _normalize_date(date_text)
        entity = _classify_entity(node_type, str(item.get("entity", "")).strip())
        summary = str(item.get("summary", "")).strip()
        connection_reason = str(item.get("connection_reason", "")).strip()
        node_id = f"{node_type}-{page_no}-{idx}"
        nodes.append(EdiscoveryNode(
            id=node_id, type=node_type, label=label, page=page_no, confidence=confidence,
            entity=entity, date_text=date_text, date_iso=date_iso, summary=summary,
            connection_reason=connection_reason,
            source_file=source_file, original_page=original_page,
        ))
    if skipped:
        logger.debug(f"[ediscovery] page={page_no} 노드 {skipped}개 스키마 불일치로 건너뜀")
    return nodes


def extract_nodes_from_chunk(
    chunk: ChildChunk,
    endpoint: str,
    model: str,
    api_key: str,
    context: str = "",
    user_id: str | uuid.UUID | None = None,
    user_language: str = "ko",
) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (프롬프트 구성) -> Step 2 (1 step 크레딧 차감) -> Step 3 (vLLM 호출)
          -> Step 4 (응답 파싱) -> Step 5 (노드 목록 반환)]

    단일 자식 청크에서 vLLM Proxy를 호출해 노드를 추출한다.
    chunk에 담긴 원본 파일 정보(source_file/original_page)를 노드 메타데이터로 보존한다.
    context가 주어지면 LLM 프롬프트에 프로젝트 주요/중요 사항을 포함한다.
    LLM 호출 직전에 1 step 크레딧을 차감한다.
    """
    _spend_agent_step_for_call(user_id, "AI agent: e-Discovery node extraction")
    prompt = _build_extraction_prompt(chunk.text, chunk.page_no, context=context, user_language=user_language)
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=2000)
        return _parse_nodes(
            content, chunk.page_no,
            source_file=chunk.source_file, original_page=chunk.original_page,
        )
    except Exception as e:
        logger.warning(f"[ediscovery] 청크 추출 실패 page={chunk.page_no} idx={chunk.index}: {e}")
        return []


def extract_nodes_concurrent(
    chunks: list[ChildChunk],
    endpoint: str,
    model: str,
    api_key: str,
    context: str = "",
    user_id: str | uuid.UUID | None = None,
    user_language: str = "ko",
) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (ThreadPoolExecutor 생성) -> Step 2 (청크별 1 step 크레딧 차감 + vLLM 호출 병렬화)
          -> Step 3 (결과 취합) -> Step 4 (노드 목록 반환)]

    청크별 vLLM 호출을 스레드 풀로 병렬화한다. 동시 호출 수는 MAX_LLM_WORKERS로 제한.
    각 청크의 LLM 호출 직전에 1 step 크레딧을 차감한다 (thread-safe).
    """
    if not chunks:
        return []
    max_workers = min(len(chunks), MAX_LLM_WORKERS)
    all_nodes: list[EdiscoveryNode] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_nodes_from_chunk, chunk, endpoint, model, api_key, context, user_id, user_language): chunk
            for chunk in chunks
        }
        for future in as_completed(futures):
            all_nodes.extend(future.result())
    return all_nodes


# --- 2차 LLM 패스: 모순(Anomaly) 탐지 ----------------------------------------
@dataclass
class AnomalyPair:
    """진술과 객관적 증거가 충돌하는 노드 쌍 — anomaly 엣지의 원본 데이터."""
    source_id: str
    target_id: str
    conflict_reason: str


def _build_anomaly_prompt(nodes_batch: list[EdiscoveryNode], context: str = "", user_language: str = "ko") -> str:
    """[Flow: Step 1 (노드 목록을 ID+label+summary+type+date로 직렬화) -> Step 2 (모순 탐지 지시) -> Step 3 (JSON 배열 스키마 명시)]

    추출된 노드 목록에서 진술(plaintiff/defendant 주장)과 객관적 증거(evidence)가 충돌하는 쌍을
    탐지하는 2차 LLM 프롬프트를 구성한다. conflict_reason은 법률 전문가가 한눈에 파악할 수 있도록 구체적으로 작성.
    """
    node_lines = []
    for n in nodes_batch:
        node_lines.append(
            f'- id={n.id} | type={n.type} | entity={n.entity} | date={n.date_text or "none"} | label={n.label}'
            f' | summary={n.summary or "(no summary)"}'
        )
    nodes_block = "\n".join(node_lines)
    context_section = ""
    if context:
        context_section = f"""
Below is additional context about the key/important matters of the project provided by the user. Prioritize this context when judging conflicts. If the context conflicts with the document, prioritize the document.
Additional context: {context}
"""
    return f"""Below is a list of case nodes extracted from a legal document.
{context_section}Find pairs of nodes where "statements/claims (plaintiff, defendant)" and "objective evidence (evidence)" logically conflict (contradict).
Examples of conflicts: the stated date differs from the evidence date, the stated amount differs from the transfer record, an alibi contradicts an expert result.

Return each conflicting pair in the following JSON format. Return only a JSON array (no other explanation).
[
  {{
    "source_id": "node id",
    "target_id": "node id",
    "conflict_reason": "Explain specifically in 1-2 sentences why it is a conflict. Write in the user's configured language ({user_language})."
  }}
]

Notes:
- source_id and target_id must be exact ids that exist in the list above.
- Exclude pairs that are not statement vs evidence (e.g., issue vs issue).
- Include only clear conflicts; do not treat simple missing information as a conflict.
- Return an empty array [] if there are no conflicts.

--- Node list ---
{nodes_block}
"""


def _parse_anomalies(content: str, valid_ids: set[str]) -> list[AnomalyPair]:
    """[Flow: Step 1 (JSON 펜스 제거 + 파싱) -> Step 2 (스키마 검증 + 유효 id 필터링) -> Step 3 (AnomalyPair 목록 반환)]

    2차 LLM 응답에서 모순 쌍을 파싱한다. 존재하지 않는 id를 참조하는 항목은 건너뛴다.
    """
    cleaned = _strip_json_fence(content)
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[ediscovery] anomaly JSON 파싱 실패: {cleaned[:200]}")
        return []
    if not isinstance(items, list):
        return []
    pairs: list[AnomalyPair] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        src = str(item.get("source_id", "")).strip()
        dst = str(item.get("target_id", "")).strip()
        reason = str(item.get("conflict_reason", "")).strip()
        if not src or not dst or src not in valid_ids or dst not in valid_ids or not reason:
            continue
        if src == dst:
            continue
        pairs.append(AnomalyPair(source_id=src, target_id=dst, conflict_reason=reason))
    return pairs


def detect_anomalies_concurrent(
    nodes: list[EdiscoveryNode],
    endpoint: str,
    model: str,
    api_key: str,
    context: str = "",
    user_id: str | uuid.UUID | None = None,
    user_language: str = "ko",
) -> list[AnomalyPair]:
    """[Flow: Step 1 (노드 수 상한 적용) -> Step 2 (주체별 배치 분할) -> Step 3 (배치별 1 step 크레딧 차감 + 2차 LLM 호출 병렬화)
          -> Step 4 (결과 취합 + 중복 제거) -> Step 5 (AnomalyPair 목록 반환)]

    추출된 노드에서 진술-증거 모순을 탐지한다. 노드가 많으면 주체별로 배치를 나눠
    2차 LLM 호출을 병렬화한다 (MAX_LLM_WORKERS 상한). 비용/지연 폭증 방지를 위해
    MAX_ANOMALY_NODES 상한을 초과하는 노드는 confidence 내림차순으로 잘라낸다.
    각 배치의 LLM 호출 직전에 1 step 크레딧을 차감한다 (thread-safe).
    """
    if len(nodes) < 2:
        return []
    # confidence 내림차순 정렬 후 상한 적용 — 중요 노드 우선 탐지
    ranked = sorted(nodes, key=lambda n: n.confidence, reverse=True)
    if len(ranked) > MAX_ANOMALY_NODES:
        logger.info(f"[ediscovery] anomaly 탐지 노드 상한 적용: {MAX_ANOMALY_NODES}개로 축소")
        ranked = ranked[:MAX_ANOMALY_NODES]

    # 주체별 배치 분할 — 같은 주체 그룹 내 + 교차 주체(진술 vs 증거) 쌍을 함께 검사
    # 간단히 전체를 배치 크기 40으로 분할 (LLM 컨텍스트 한계 고려)
    BATCH_SIZE = 40
    batches = [ranked[i:i + BATCH_SIZE] for i in range(0, len(ranked), BATCH_SIZE)]
    valid_ids = {n.id for n in ranked}

    max_workers = min(len(batches), MAX_LLM_WORKERS) if batches else 0
    if max_workers == 0:
        return []

    def _detect_batch(batch: list[EdiscoveryNode]) -> list[AnomalyPair]:
        if len(batch) < 2:
            return []
        _spend_agent_step_for_call(user_id, "AI agent: e-Discovery anomaly detection")
        prompt = _build_anomaly_prompt(batch, context=context, user_language=user_language)
        try:
            content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=2000)
            return _parse_anomalies(content, valid_ids)
        except Exception as e:
            logger.warning(f"[ediscovery] anomaly 탐지 실패 batch_size={len(batch)}: {e}")
            return []

    all_pairs: list[AnomalyPair] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_detect_batch, b) for b in batches]
        for future in as_completed(futures):
            all_pairs.extend(future.result())

    # 중복 제거 (source, target 순서 무관)
    seen: set[tuple[str, str]] = set()
    unique: list[AnomalyPair] = []
    for p in all_pairs:
        key = tuple(sorted((p.source_id, p.target_id)))
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)
    return unique


# --- 필터링 + 그래프 조립 ---------------------------------------------------
def filter_nodes_by_threshold(
    nodes: list[EdiscoveryNode],
    threshold: float,
) -> list[EdiscoveryNode]:
    """신뢰도가 임계값 이상인 노드만 남긴다 (파이프라인 방식)."""
    if threshold <= 0:
        return nodes
    return [n for n in nodes if n.confidence >= threshold]


# 쟁점(issue) 중복 판별용 상수 -------------------------------------------------
_ISSUE_STOPWORDS = {
    "의", "에", "에서", "로", "으로", "는", "은", "이", "가", "을", "를", "과", "와",
    "한", "할", "하는", "된", "된다", "되며", "및", "등", "또는", "에 대한", "에 대해",
    "에 따른", "the", "a", "an", "and", "or", "of", "in", "on", "at", "to", "for",
    "with", "by",
}


def _normalize_issue_key(label: str) -> str:
    """공백/특수문자를 제거하고 소문자로 변환해 issue dedup 키를 만든다.

    예: "계약 위반" -> "계약위반", "A의 계약 위반!" -> "A의계약위반"
    """
    text = re.sub(r"\s+", "", label.lower())
    text = re.sub(r"[^\w가-힣a-z0-9]", "", text)
    return text


def _issue_token_set(label: str) -> set[str]:
    """issue label을 공백/특수문자로 분리하고 불용어를 제거한 토큰 집합을 반환한다."""
    tokens = re.split(r"\s+|[\.,;!?()\[\]{}:：\"'‘’“”]", label.lower())
    return {t for t in tokens if t and t not in _ISSUE_STOPWORDS and len(t) > 1}


def _is_similar_issue(label_a: str, label_b: str) -> bool:
    """두 issue label이 의미상 동일하거나 거의 같으면 True를 반환한다.

    판단 기준:
    1. 정규화(공백/특수문자 제거) 후 동일
    2. 한쪽이 다른 쪽에 포함
    3. 토큰 집합의 Jaccard 유사도 >= 0.6
    """
    norm_a = _normalize_issue_key(label_a)
    norm_b = _normalize_issue_key(label_b)
    if norm_a == norm_b:
        return True
    if not norm_a or not norm_b:
        return False
    if norm_a in norm_b or norm_b in norm_a:
        return True
    tokens_a = _issue_token_set(label_a)
    tokens_b = _issue_token_set(label_b)
    if not tokens_a or not tokens_b:
        return False
    union = tokens_a | tokens_b
    return len(tokens_a & tokens_b) / len(union) >= 0.6


def _deduplicate_nodes(nodes: list[EdiscoveryNode]) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (label 기준 그룹화 + issue는 의미 중복도 병합)
          -> Step 2 (같은 label+type은 confidence 최댓값으로 병합 + date/summary 보존)
          -> Step 3 (고유 노드 목록 반환)]

    같은 type+label을 가진 노드를 병합한다 (여러 청크에서 중복 추출 방지).
    issue 노드는 단어 순서/공백/조사만 다른 유사 label도 하나로 묶어 쟁점 필터 중복을 줄인다.
    페이지 번호는 가장 빠른 페이지를, date는 가장 이른 날짜를, summary는 가장 긴 것을 유지한다.
    """

    def merge(existing: EdiscoveryNode, node: EdiscoveryNode) -> None:
        existing.confidence = max(existing.confidence, node.confidence)
        # 더 빠른 글로벌 페이지를 우선으로 병합; 페이지가 갱신되면 원본 파일 정보도 함께 동기화
        if node.page < existing.page:
            existing.page = node.page
            existing.source_file = node.source_file
            existing.original_page = node.original_page
        # 더 이른 날짜 우선 (빈 문자열은 무시)
        if node.date_iso and (not existing.date_iso or node.date_iso < existing.date_iso):
            existing.date_iso = node.date_iso
            existing.date_text = node.date_text
        # 더 구체적인 summary 우선; summary가 갱신되면 연결 근거도 함께 동기화
        if len(node.summary) > len(existing.summary):
            existing.summary = node.summary
            existing.connection_reason = node.connection_reason

    by_key: dict[tuple[str, str], EdiscoveryNode] = {}
    # issue 노드는 의미상 중복도 병합하기 위해 정규화 키로 추가 색인
    by_issue_norm: dict[str, EdiscoveryNode] = {}

    for node in nodes:
        # issue 노드: fuzzy dedup — "계약 위반"과 "계약위반", "A의 계약 위반" 등을 하나로 묶음
        if node.type == "issue":
            norm = _normalize_issue_key(node.label)
            if norm in by_issue_norm:
                merge(by_issue_norm[norm], node)
                continue
            similar = next(
                ((k, n) for k, n in by_issue_norm.items() if _is_similar_issue(node.label, n.label)),
                None,
            )
            if similar:
                _, existing = similar
                merge(existing, node)
                by_issue_norm[norm] = existing
                continue
            by_issue_norm[norm] = node

        key = (node.type, node.label.lower())
        if key not in by_key:
            by_key[key] = node
            continue
        merge(by_key[key], node)

    return list(by_key.values())


# --- 스윔레인 구성 -----------------------------------------------------------
# swimlane 표시 라벨 (프론트엔드 i18n 키와 매칭)
SWIMLANE_LABELS = {
    "plaintiff": "원고",
    "defendant": "피고",
    "third_party": "제3자",
    "issue": "쟁점",
}


def _build_swimlanes(nodes: list[EdiscoveryNode]) -> tuple[list[dict], dict[str, str]]:
    """[Flow: Step 1 (등장한 entity 수집) -> Step 2 (swimlane 노드 생성) -> Step 3 (각 노드에 parent_id 주입) -> Step 4 (swimlane 노드 + id 매핑 반환)]

    사건 주체(원고/피고/제3자/쟁점)를 최상위 swimlane 노드로 생성하고,
    각 사건 노드에 해당 주체의 parentId를 매핑한다. 등장하지 않은 주체의 swimlane은 생성하지 않는다.
    반환: (swimlane_graph_nodes, node_id → swimlane_id 매핑)
    """
    present_entities = {n.entity for n in nodes if n.entity in VALID_ENTITY_TYPES}
    # 기본 순서: plaintiff, defendant, third_party, issue
    ordered = [e for e in ("plaintiff", "defendant", "third_party", "issue") if e in present_entities]

    swimlane_nodes: list[dict] = []
    id_map: dict[str, str] = {}
    for entity in ordered:
        swimlane_id = SWIMLANE_IDS[entity]
        swimlane_nodes.append({
            "id": swimlane_id,
            "type": "swimlane",
            "data": {"label": SWIMLANE_LABELS[entity], "entity": entity},
        })
        id_map[entity] = swimlane_id

    # 각 노드에 parent_id 주입 — entity 기반 매핑
    for n in nodes:
        n.parent_id = id_map.get(n.entity, "")
    return swimlane_nodes, id_map


def assemble_graph(
    nodes: list[EdiscoveryNode],
    anomalies: list[AnomalyPair] | None = None,
) -> dict:
    """[Flow: Step 1 (노드 중복 제거) -> Step 2 (노드 수 상한 적용) -> Step 3 (swimlane 생성 + parentId 매핑)
          -> Step 4 (시간순 정렬) -> Step 5 (smoothstep 일반 엣지 + anomaly 엣지 조립) -> Step 6 (그래프 JSON 반환)]

    노드 중복 제거 후 4개 swimlane(원고/피고/제3자/쟁점)을 최상위 노드로 배치하고,
    자식 노드에 parentId를 주입한다. 시간순(date_iso → page → id) 정렬 후
    같은 swimlane 내 인접 노드 간 smoothstep 엣지 + 모순 쌍 간 anomaly 엣지를 조립한다.
    데이터 계약 스키마({nodes, edges})를 따른다.
    """
    unique_nodes = _deduplicate_nodes(nodes)
    if len(unique_nodes) > MAX_NODES_PER_GRAPH:
        unique_nodes = sorted(unique_nodes, key=lambda n: n.confidence, reverse=True)[:MAX_NODES_PER_GRAPH]
        logger.warning(f"[ediscovery] 노드 수 상한 적용: {MAX_NODES_PER_GRAPH}개로 축소")

    # Step 3: swimlane 생성 + parentId 매핑
    swimlane_nodes, _id_map = _build_swimlanes(unique_nodes)

    # Step 4: 시간순 정렬 — date_iso 우선, 없으면 page, 그 다음 id (안정 정렬)
    sorted_nodes = sorted(
        unique_nodes,
        key=lambda n: (n.date_iso or "9999-12-31", n.page, n.id),
    )

    # 자식 노드 그래프 JSON 생성 — parentId + 원본 파일/페이지 메타데이터 포함
    graph_child_nodes = [
        {
            "id": n.id,
            "type": n.type,
            "parentId": n.parent_id,
            "data": {
                "label": n.label,
                "page": n.page,
                "confidence": n.confidence,
                "entity": n.entity,
                "date": n.date_text,
                "summary": n.summary,
                "connection_reason": n.connection_reason,
                "issue": n.label if n.type == "issue" else "",
                "source_file": n.source_file,
                "original_page": n.original_page if n.original_page > 0 else n.page,
            },
        }
        for n in sorted_nodes
    ]

    # Step 5: 엣지 조립
    edges: list[dict] = []
    edge_seen: set[tuple[str, str]] = set()

    # 5-a: 같은 swimlane 내 시간순 인접 노드 간 smoothstep 엣지 (타임라인 흐름)
    by_swimlane: dict[str, list[EdiscoveryNode]] = {}
    for n in sorted_nodes:
        if n.parent_id:
            by_swimlane.setdefault(n.parent_id, []).append(n)
    for swimlane_id, lane_nodes in by_swimlane.items():
        for i in range(len(lane_nodes) - 1):
            src, dst = lane_nodes[i], lane_nodes[i + 1]
            edge_key = (src.id, dst.id)
            if edge_key in edge_seen:
                continue
            edge_seen.add(edge_key)
            edges.append({
                "id": f"edge-{src.id}-{dst.id}",
                "source": src.id,
                "target": dst.id,
                "type": "smoothstep",
            })

    # 5-b: anomaly 엣지 — 모순 쌍 (swimlane 간 횡단 가능)
    anomaly_set = anomalies or []
    for pair in anomaly_set:
        edge_key = tuple(sorted((pair.source_id, pair.target_id)))
        if edge_key in edge_seen:
            continue
        edge_seen.add(edge_key)
        edges.append({
            "id": f"anomaly-{pair.source_id}-{pair.target_id}",
            "source": pair.source_id,
            "target": pair.target_id,
            "type": "anomaly",
            "data": {"conflict_reason": pair.conflict_reason},
        })

    # 최종 노드 목록: swimlane(부모) + 자식 노드
    return {"nodes": swimlane_nodes + graph_child_nodes, "edges": edges}


# --- 자동 파라미터 추천 ------------------------------------------------------

def _build_param_suggestion_prompt(page_texts: dict[int, str], context: str = "", user_language: str = "ko") -> str:
    """[Flow: Step 1 (처음/중간/끝 페이지 샘플 선택) -> Step 2 (각 샘플을 2000자로 truncate)
          -> Step 3 (프롬프트 문자열 조합) -> Step 4 (LLM 입력 문자열 반환)]

    전체 문서의 페이지 샘플을 기반으로 chunk_size/threshold/max_docs를 추천하도록 LLM에 지시하는
    프롬프트를 생성한다. 짧은 문서는 전체 페이지, 긴 문서는 처음/중간/끝 페이지만 샘플링해
    토큰 비용을 절감한다.
    """
    total_pages = len(page_texts)
    sorted_pages = sorted(page_texts.keys())
    if total_pages <= 3:
        sample_pages = sorted_pages
    else:
        sample_pages = [sorted_pages[0], sorted_pages[total_pages // 2], sorted_pages[-1]]

    sample_blocks = []
    for page_no in sample_pages:
        text = page_texts[page_no].strip()
        if len(text) > 2000:
            text = text[:2000] + "..."
        sample_blocks.append(f"--- Page {page_no} ---\n{text}")
    sample_text = "\n\n".join(sample_blocks)

    context_section = ""
    if context:
        context_section = f"""
Below is additional context about the key/important matters of the project provided by the user. Prioritize this context when recommending parameters. If the context conflicts with the document, prioritize the document.
Additional context: {context}
"""
    return f"""Below are sample pages from a legal document.{context_section} Analyze the characteristics of this document and return the 3 optimal parameters for the e-Discovery GraphRAG pipeline as JSON.

[Parameter descriptions]
- chunk_size: The number of words passed to the LLM at once. Use 256-512 for short and simple documents, 1024-2048 for complex documents with many issues/parties, and 2048-4096 for very complex documents.
- threshold: The node extraction confidence threshold (0.0-1.0). Use 0.6-0.7 for noisy or conservative extraction, 0.45-0.55 for balanced extraction, and 0.3-0.4 to keep more candidates.
- max_docs: The maximum number of pages to process. For short documents (<=50 pages), use the total page count; for medium documents (50-500 pages), use 50-200; for long documents (500+ pages), use 100-500 to balance cost and coverage.

[JSON response format]
{{
  "chunk_size": 1024,
  "threshold": 0.5,
  "max_docs": 100,
  "reasoning": "Explain in one sentence in the user's configured language ({user_language})."
}}

Return only the JSON. No other explanation.

--- Document samples ---
{sample_text}
"""


def _parse_param_suggestion(content: str) -> dict:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (필드 추출/기본값 적용)
          -> Step 4 (dict 반환)]

    LLM의 파라미터 추천 응답을 파싱한다. 파싱 실패 또는 필드 누락 시 기본값을 채워 반환한다.
    """
    cleaned = _strip_json_fence(content).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[ediscovery] 파라미터 추천 JSON 파싱 실패: {cleaned[:200]}")
        return {}
    if not isinstance(data, dict):
        return {}

    try:
        chunk_size = int(data.get("chunk_size", DEFAULT_CHUNK_SIZE))
    except (TypeError, ValueError):
        chunk_size = DEFAULT_CHUNK_SIZE

    try:
        threshold = float(data.get("threshold", DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        threshold = DEFAULT_THRESHOLD

    max_docs = data.get("max_docs")
    if max_docs is not None:
        try:
            max_docs = int(max_docs)
        except (TypeError, ValueError):
            max_docs = None

    return {
        "chunk_size": chunk_size,
        "threshold": threshold,
        "max_docs": max_docs,
        "reasoning": str(data.get("reasoning", "")).strip(),
    }


def _clamp_suggested_params(suggested: dict, total_pages: int) -> dict:
    """[Flow: Step 1 (chunk_size를 128 단위로 256~4096 범위로 clamp)
          -> Step 2 (threshold를 0.3~0.7 범위로 clamp)
          -> Step 3 (max_docs를 1~min(전체,5000) 범위로 clamp) -> Step 4 (dict 반환)]

    LLM이 추천한 파라미터를 안전한 범위 내로 조정한다.
    """
    raw_chunk = suggested.get("chunk_size", DEFAULT_CHUNK_SIZE)
    try:
        raw_chunk = int(raw_chunk)
    except (TypeError, ValueError):
        raw_chunk = DEFAULT_CHUNK_SIZE
    chunk_size = max(256, min(4096, ((raw_chunk // 128) * 128)))

    raw_threshold = suggested.get("threshold", DEFAULT_THRESHOLD)
    try:
        raw_threshold = float(raw_threshold)
    except (TypeError, ValueError):
        raw_threshold = DEFAULT_THRESHOLD
    threshold = round(max(0.3, min(0.7, raw_threshold)), 2)

    raw_max_docs = suggested.get("max_docs")
    if raw_max_docs is None:
        max_docs = total_pages
    else:
        try:
            max_docs = int(raw_max_docs)
        except (TypeError, ValueError):
            max_docs = total_pages
        max_docs = max(1, min(5000, max_docs))
    max_docs = min(max_docs, total_pages) if total_pages else max_docs

    return {
        "chunk_size": chunk_size,
        "threshold": threshold,
        "max_docs": max_docs,
        "reasoning": suggested.get("reasoning", ""),
    }


def _suggest_params(
    page_texts: dict[int, str],
    endpoint: str,
    model: str,
    api_key: str,
    context: str = "",
    user_id: str | uuid.UUID | None = None,
    user_language: str = "ko",
) -> dict:
    """[Flow: Step 1 (페이지 샘플 선택 및 프롬프트 구성) -> Step 2 (1 step 크레딧 차감)
          -> Step 3 (vLLM 호출) -> Step 4 (응답 파싱) -> Step 5 (권장 범위 내 clamp) -> Step 6 (파라미터 dict 반환)]

    전체 문서의 페이지 샘플을 LLM에 전달해 e-Discovery 파이프라인의 chunk_size/threshold/max_docs를
    자동 추천받는다. LLM 호출 직전에 1 step 크레딧을 차감한다. LLM 호출 실패 시 안전한 기본값을 반환한다.
    """
    total_pages = len(page_texts)
    if not page_texts:
        return _clamp_suggested_params({}, total_pages)

    _spend_agent_step_for_call(user_id, "AI agent: e-Discovery parameter suggestion")
    prompt = _build_param_suggestion_prompt(page_texts, context=context, user_language=user_language)
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=500)
    except Exception as e:
        logger.warning(f"[ediscovery] 파라미터 추천 LLM 호출 실패: {e}")
        return _clamp_suggested_params({}, total_pages)

    suggested = _parse_param_suggestion(content)
    return _clamp_suggested_params(suggested, total_pages)


# --- 메인 오케스트레이션 ----------------------------------------------------
def run(
    job_id: str,
    chunk_size: int | None = None,
    threshold: float | None = None,
    page_range: list[int] | None = None,
    max_chunks: int | None = None,
    query: str | None = None,
    max_docs: int | None = None,
    context: str | None = None,
    user_id: str | uuid.UUID | None = None,
) -> dict:
    """[Flow: Step 1 (job 로드 + LLM 설정) -> Step 2 (텍스트 추출) -> Step 2b (파라미터 누락 시 LLM 자동 추천)
          -> Step 3 (max_chunks 적용) -> Step 4 (청킹) -> Step 5 (query 필터링) -> Step 6 (병렬 노드 추출)
          -> Step 7 (임계값 필터 + 그래프 조립) -> Step 8 (jobs 상태 done 갱신) -> Step 9 (예외 시 error + 환불 플래그)]

    e-Discovery 추출 파이프라인을 실행하고 jobs 테이블의 ediscovery_* 필드를 갱신한다.
    chunk_size/threshold/max_docs 중 하나라도 None이면 LLM이 문서 샘플을 보고 자동으로 추천한다.
    xlsx_advanced_converter.run 과 동일한 상태/환불 패턴을 따른다.

    매개변수:
        chunk_size: 자식 청크 단어 수. None이면 LLM이 자동 추천.
        threshold: 노드 신뢰도 임계값. None이면 LLM이 자동 추천.
        max_chunks: 처리할 최대 페이지(문서) 수. None이면 LLM이 자동 추천.
        query: 자연어 쿼리. 지정 시 쿼리 용어를 포함한 청크만 처리 대상으로 한다.
        max_docs: max_chunks의 별칭 (api/ediscovery.py 호환용). max_chunks가 None일 때만 적용.
        context: 사용자가 입력한 프로젝트 주요/중요 사항. LLM 프롬프트에 포함되어 분석에 참고된다.
    """
    # max_docs → max_chunks 호환 매핑 (api/ediscovery.py의 extract/threshold 엔드포인트 호환)
    if max_chunks is None and max_docs is not None:
        max_chunks = max_docs
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}

        endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
        model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
        api_key = settings_store.get_setting(db, "llm_api_key") or ""

        # 파라미터로 전달된 context가 없으면 DB에 저장된 job.ediscovery_context를 사용한다.
        # 첫 업로드 시 입력한 맥락과 분석 시 수정한 맥락을 모두 반영할 수 있다.
        if context is None:
            context = job.ediscovery_context or ""
        context = (context or "").strip()

        # 사용자 설정 언어 조회. LLM 프롬프트는 영어로 보내지만, 응답은 사용자 설정 언어를 우선한다.
        user_language = "ko"
        if user_id:
            try:
                user = db.get(User, uuid.UUID(str(user_id)))
                if user and user.language:
                    user_language = user.language
            except Exception:
                pass

        # Step 2: 텍스트 추출 (page_texts + 원본 파일/페이지 추적용 page_meta)
        page_texts, page_meta = extract_page_texts(job)
        if not page_texts:
            raise ValueError("문서에서 텍스트를 추출할 수 없습니다 (텍스트 레이어/마크다운 모두 비어 있음)")

        # Step 2a: 파라미터가 명시되지 않으면 LLM이 전체 문서 샘플을 보고 자동 추천
        auto_params = None
        if chunk_size is None or threshold is None or max_chunks is None:
            auto_params = _suggest_params(page_texts, endpoint, model, api_key, context=context, user_id=user_id, user_language=user_language)
            if chunk_size is None:
                chunk_size = auto_params["chunk_size"]
            if threshold is None:
                threshold = auto_params["threshold"]
            if max_chunks is None:
                max_chunks = auto_params["max_docs"]
            logger.info(f"[ediscovery] job={job_id} LLM 추천 파라미터: {auto_params}")

        # Step 3: max_chunks 적용 — 페이지 번호 오름차순으로 상위 max_chunks개만 사용
        if max_chunks and len(page_texts) > max_chunks:
            kept_pages = sorted(page_texts.keys())[:max_chunks]
            page_texts = {p: page_texts[p] for p in kept_pages}
            page_meta = {p: page_meta.get(p, {}) for p in kept_pages}
            logger.info(f"[ediscovery] job={job_id} max_chunks 적용: {len(page_texts)}페이지 사용")

        # Step 4: 청킹 (page_meta를 함께 전달해 청크별 원본 파일 정보 보존)
        chunks = build_parent_child_chunks(
            page_texts, chunk_size=chunk_size, page_range=page_range, page_meta=page_meta
        )
        if not chunks:
            raise ValueError("청킹 결과가 비어 있습니다 (텍스트가 너무 짧거나 page_range 불일치)")
        logger.info(f"[ediscovery] job={job_id} 청크 {len(chunks)}개 생성 (chunk_size={chunk_size})")

        # Step 5: query 필터링 — 쿼리 용어를 포함한 청크만 처리
        if query and query.strip():
            terms = [t.strip().lower() for t in query.strip().split() if t.strip()]
            filtered_chunks = [
                c for c in chunks
                if any(term in c.text.lower() for term in terms)
            ]
            if filtered_chunks:
                chunks = filtered_chunks
                logger.info(f"[ediscovery] job={job_id} query 필터링: {len(chunks)}개 청크 사용")
            else:
                logger.warning(f"[ediscovery] job={job_id} query 용어와 일치하는 청크 없음, 전체 청크 사용")

        # Step 6: 병렬 노드 추출
        raw_nodes = extract_nodes_concurrent(chunks, endpoint, model, api_key, context=context, user_id=user_id, user_language=user_language)
        logger.info(f"[ediscovery] job={job_id} 원시 노드 {len(raw_nodes)}개 추출")

        # Step 6b: 1차 추출이 0개면 폴백 추출 시도 (일지/명단 등 비소송 자료 대응)
        if not raw_nodes and chunks:
            logger.warning(f"[ediscovery] job={job_id} 1차 노드 추출 0개, 폴백 추출 시도")
            raw_nodes = _extract_fallback_nodes(chunks, endpoint, model, api_key, context=context, user_id=user_id, user_language=user_language)

        # Step 7: 임계값 필터 + 2차 LLM 패스 모순 탐지 + 그래프 조립
        filtered = filter_nodes_by_threshold(raw_nodes, threshold)
        anomalies = detect_anomalies_concurrent(filtered, endpoint, model, api_key, context=context, user_id=user_id, user_language=user_language)
        logger.info(f"[ediscovery] job={job_id} 모순 쌍 {len(anomalies)}개 탐지")
        graph = assemble_graph(filtered, anomalies)
        metrics = {
            "total_docs": len(page_texts),
            "processed_chunks": len(chunks),
            "chunk_size": chunk_size,
            "threshold": threshold,
            "max_docs": max_chunks,
            "raw_nodes": len(raw_nodes),
            "filtered_nodes": len(filtered),
            "anomalies_detected": len(anomalies),
            "graph_nodes": len(graph["nodes"]),
            "graph_edges": len(graph["edges"]),
            "auto_params": auto_params is not None,
            "reasoning": auto_params.get("reasoning", "") if auto_params else "",
        }
        logger.info(f"[ediscovery] job={job_id} 그래프 완성: {metrics}")

        # Step 6: 상태 done 갱신
        job.ediscovery_status = "done"
        job.ediscovery_graphs = graph
        job.ediscovery_metrics = metrics
        job.ediscovery_refundable = False
        db.commit()
        return {"job_id": job_id, "status": "done", "metrics": metrics}

    except Exception as e:
        logger.exception(f"[ediscovery] {job_id} 추출 실패: {e}")
        tb = traceback.format_exc()
        job = db.get(Job, job_id)
        if job is not None:
            job.ediscovery_status = "error"
            job.ediscovery_refundable = True
            job.ediscovery_metrics = {
                "error": str(e),
                "traceback": tb[:2000],
            }
            db.commit()
        return {"job_id": job_id, "status": "error", "error": str(e)}
    finally:
        db.close()
