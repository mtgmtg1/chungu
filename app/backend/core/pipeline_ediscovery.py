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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from .. import settings_store
from ..config import settings
from ..core import supabase_client
from ..core.legal_case_profile import extract_legal_profile
from ..core.ocr_client import call_text
from ..db.models import Job
from ..db.session import SessionLocal

logger = logging.getLogger(__name__)

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
DATE_RE = re.compile(
    r"(\d{4})\s*(?:년|年|\.|\-|/)\s*(\d{1,2})\s*(?:월|月|\.|\-|/)\s*(\d{1,2})\s*(?:일|日)?"
    r"|(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})"
    r"|(\d{4})\s*(?:년|年)\s*(\d{1,2})\s*(?:월|月)",
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
    parent_id: str = ""     # 소속 swimlane 노드 ID (assemble_graph에서 주입)
    meta: dict = field(default_factory=dict)


@dataclass
class ChildChunk:
    """슬라이딩 윈도우로 분할된 자식 청크 — 페이지 메타데이터를 보존한다."""
    page_no: int
    text: str
    index: int              # 같은 페이지 내 청크 순번


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


def extract_page_texts(job: Job) -> dict[int, str]:
    """[Flow: Step 1 (PDF 텍스트 레이어 추출 시도) -> Step 2 (빈 페이지가 많으면 마크다운 폴백) -> Step 3 (page_no → 텍스트 맵 반환)]

    searchable_pdf_storage_path → pdf_storage_path → result_md_storage_path 순서로 폴백.
    법률 문서는 텍스트 레이어가 있는 경우가 많으므로 PDF 우선, 스캔 문서는 마크다운을 사용.
    """
    pdf_bytes = _download_pdf_bytes(job)
    if pdf_bytes:
        page_texts = _extract_page_texts_from_pdf(pdf_bytes)
        non_empty = sum(1 for t in page_texts.values() if t.strip())
        if non_empty > 0:
            logger.info(f"[ediscovery] PDF 텍스트 레이어에서 {non_empty}페이지 추출")
            return page_texts
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
                return page_texts
        except Exception as e:
            logger.warning(f"[ediscovery] 마크다운 다운로드 실패 path={storage_path}: {e}")
    return {}


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
) -> list[ChildChunk]:
    """[Flow: Step 1 (page_range 필터링) -> Step 2 (페이지별 단어 분할) -> Step 3 (슬라이딩 윈도우 자식 청크 생성)
          -> Step 4 (청크 텍스트 길이 상한 적용) -> Step 5 (ChildChunk 목록 반환)]

    부모 청크 = 페이지 전체 텍스트 (컨텍스트 보존).
    자식 청크 = 단어 단위 슬라이딩 윈도우 (chunk_size 단어, overlap 단위 겹침).
    페이지 메타데이터(page_no)를 각 자식 청크에 보존한다.
    """
    if chunk_size <= 0:
        chunk_size = DEFAULT_CHUNK_SIZE
    if overlap < 0 or overlap >= chunk_size:
        overlap = DEFAULT_OVERLAP

    page_set = set(page_range) if page_range else set()
    chunks: list[ChildChunk] = []
    for page_no in sorted(page_texts.keys()):
        if page_set and page_no not in page_set:
            continue
        words = _split_into_words(page_texts[page_no])
        if not words:
            continue
        step = chunk_size - overlap
        index = 0
        start = 0
        while start < len(words):
            end = min(start + chunk_size, len(words))
            text = _words_to_text(words[start:end])
            if len(text) > MAX_CHARS_PER_CHUNK:
                text = text[:MAX_CHARS_PER_CHUNK]
            chunks.append(ChildChunk(page_no=page_no, text=text, index=index))
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
    # 그룹 우선순위: (Y, M, D) | (Y, M, D) | (Y, M)
    year = m.group(1) or m.group(4) or m.group(7)
    month = m.group(2) or m.group(5) or m.group(8) or "01"
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


def _build_extraction_prompt(chunk_text: str, page_no: int) -> str:
    """[Flow: Step 1 (노드 타입/필드 안내) -> Step 2 (JSON 스키마 명시) -> Step 3 (주의사항) -> Step 4 (청크 텍스트 삽입)]

    청크 텍스트에서 쟁점/원고/피고/증거 노드를 추출하는 LLM 프롬프트를 구성한다.
    시간순 타임라인 + 주체별 스윔레인 배치를 위해 entity/date/summary 필드를 함께 추출한다.
    반환 JSON 스키마는 프론트엔드/AI 백엔드 데이터 계약을 따른다.
    """
    return f"""아래는 법률 문서의 {page_no}페이지에서 추출한 텍스트 일부이다.
이 텍스트에서 다음 4가지 유형의 노드를 추출하라:
- issue: 문서의 핵심 쟁점(법적 다툼의 대상이 되는 사실/권리)
- plaintiff: 원고(소송을 제기한 측)의 이름/주장
- defendant: 피고(소송을 대응하는 측)의 이름/주장
- evidence: 증거(문서/증인/감정 결과 등)

각 노드는 다음 JSON 형식으로 반환하라. 결과는 JSON 배열만 반환한다 (다른 설명 금지).
[
  {{
    "type": "issue | plaintiff | defendant | evidence",
    "label": "간결한 한국어 요약 (핵심 내용)",
    "entity": "plaintiff | defendant | third_party | issue",
    "date": "해당 사건/증거의 날짜 표현 (예: 2023년 4월 5일, 2023-04-05). 없으면 빈 문자열",
    "summary": "1~2문장 상세 설명. label보다 구체적인 맥락을 포함",
    "confidence": 0.0~1.0
  }}
]

주의:
- entity는 이 노드의 행위 주체가 누구인지 분류한다. issue 노드는 "issue", 원고 관련은 "plaintiff", 피고 관련은 "defendant", 그 외 제3자/감정인/증인은 "third_party".
- date는 텍스트에 명시된 날짜를 원문 그대로 추출. 날짜가 없으면 빈 문자열.
- summary는 label보다 구체적인 1~2문장 설명 (점진적 탐색 패널에 표시됨).
- confidence는 해당 노드가 텍스트에 명확히 나타나는 정도 (0.0=불확실, 1.0=명확).
- label은 간결하게 한국어로 작성.
- 텍스트에 해당 정보가 없으면 빈 배열 [] 반환.

--- 텍스트 ---
{chunk_text}
"""


def _strip_json_fence(content: str) -> str:
    """LLM 응답에서 ```json ... ``` 펜스를 제거한다."""
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


def _parse_nodes(content: str, page_no: int) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (JSON 펜스 제거) -> Step 2 (JSON 파싱) -> Step 3 (노드 스키마 검증/변환 + entity/date/summary 추출)
          -> Step 4 (EdiscoveryNode 목록 반환)]

    LLM 응답 문자열을 EdiscoveryNode 목록으로 변환한다.
    entity/date/summary 필드를 함께 파싱해 시간순 정렬 + 스윔레인 배치 + 점진적 탐색에 활용한다.
    스키마에 맞지 않는 항목은 건너뛴다.
    """
    cleaned = _strip_json_fence(content)
    try:
        items = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[ediscovery] 노드 JSON 파싱 실패 page={page_no}: {cleaned[:200]}")
        return []
    if not isinstance(items, list):
        return []

    nodes: list[EdiscoveryNode] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        node_type = str(item.get("type", "")).lower().strip()
        if node_type not in VALID_NODE_TYPES:
            continue
        label = str(item.get("label", "")).strip()
        if not label:
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
        node_id = f"{node_type}-{page_no}-{idx}"
        nodes.append(EdiscoveryNode(
            id=node_id, type=node_type, label=label, page=page_no, confidence=confidence,
            entity=entity, date_text=date_text, date_iso=date_iso, summary=summary,
        ))
    return nodes


def extract_nodes_from_chunk(
    chunk: ChildChunk,
    endpoint: str,
    model: str,
    api_key: str,
) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (프롬프트 구성) -> Step 2 (vLLM 호출) -> Step 3 (응답 파싱) -> Step 4 (노드 목록 반환)]

    단일 자식 청크에서 vLLM Proxy를 호출해 노드를 추출한다.
    """
    prompt = _build_extraction_prompt(chunk.text, chunk.page_no)
    try:
        content, _ = call_text(prompt, endpoint, model, api_key, max_tokens=2000)
        return _parse_nodes(content, chunk.page_no)
    except Exception as e:
        logger.warning(f"[ediscovery] 청크 추출 실패 page={chunk.page_no} idx={chunk.index}: {e}")
        return []


def extract_nodes_concurrent(
    chunks: list[ChildChunk],
    endpoint: str,
    model: str,
    api_key: str,
) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (ThreadPoolExecutor 생성) -> Step 2 (청크별 vLLM 호출 병렬화) -> Step 3 (결과 취합) -> Step 4 (노드 목록 반환)]

    청크별 vLLM 호출을 스레드 풀로 병렬화한다. 동시 호출 수는 MAX_LLM_WORKERS로 제한.
    """
    if not chunks:
        return []
    max_workers = min(len(chunks), MAX_LLM_WORKERS)
    all_nodes: list[EdiscoveryNode] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(extract_nodes_from_chunk, chunk, endpoint, model, api_key): chunk
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


def _build_anomaly_prompt(nodes_batch: list[EdiscoveryNode]) -> str:
    """[Flow: Step 1 (노드 목록을 ID+label+summary+type+date로 직렬화) -> Step 2 (모순 탐지 지시) -> Step 3 (JSON 배열 스키마 명시)]

    추출된 노드 목록에서 진술(plaintiff/defendant 주장)과 객관적 증거(evidence)가 충돌하는 쌍을
    탐지하는 2차 LLM 프롬프트를 구성한다. conflict_reason은 법률 전문가가 한눈에 파악할 수 있도록 구체적으로 작성.
    """
    node_lines = []
    for n in nodes_batch:
        node_lines.append(
            f'- id={n.id} | type={n.type} | entity={n.entity} | date={n.date_text or "없음"} | label={n.label}'
            f' | summary={n.summary or "(요약 없음)"}'
        )
    nodes_block = "\n".join(node_lines)
    return f"""아래는 법률 문서에서 추출한 사건 노드 목록이다.
이 노드들 중에서 "진술/주장(plaintiff, defendant)"과 "객관적 증거(evidence)"가 논리적으로 충돌(모순)하는 쌍을 찾아라.
충돌의 예: 진술한 날짜와 증거의 날짜가 다름, 진술한 금액과 이체 내역이 다름, 알리바이와 감정 결과가 상충함.

각 모순 쌍을 다음 JSON 형식으로 반환하라. 결과는 JSON 배열만 반환한다 (다른 설명 금지).
[
  {{
    "source_id": "노드 id",
    "target_id": "노드 id",
    "conflict_reason": "왜 모순인지 1~2문장으로 구체적으로 설명 (한국어)"
  }}
]

주의:
- source_id와 target_id는 위 목록에 존재하는 정확한 id여야 한다.
- 진술과 증거가 아닌 노드 쌍(예: issue vs issue)은 모순에서 제외한다.
- 명확한 충돌만 포함하고, 단순한 정보 누락은 모순으로 간주하지 않는다.
- 모순이 없으면 빈 배열 [] 반환.

--- 노드 목록 ---
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
) -> list[AnomalyPair]:
    """[Flow: Step 1 (노드 수 상한 적용) -> Step 2 (주체별 배치 분할) -> Step 3 (배치별 2차 LLM 호출 병렬화)
          -> Step 4 (결과 취합 + 중복 제거) -> Step 5 (AnomalyPair 목록 반환)]

    추출된 노드에서 진술-증거 모순을 탐지한다. 노드가 많으면 주체별로 배치를 나눠
    2차 LLM 호출을 병렬화한다 (MAX_LLM_WORKERS 상한). 비용/지연 폭증 방지를 위해
    MAX_ANOMALY_NODES 상한을 초과하는 노드는 confidence 내림차순으로 잘라낸다.
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
        prompt = _build_anomaly_prompt(batch)
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


def _deduplicate_nodes(nodes: list[EdiscoveryNode]) -> list[EdiscoveryNode]:
    """[Flow: Step 1 (label 기준 그룹화) -> Step 2 (같은 label+type은 confidence 최댓값으로 병합 + date/summary 보존) -> Step 3 (고유 노드 목록 반환)]

    같은 type+label을 가진 노드를 병합한다 (여러 청크에서 중복 추출 방지).
    페이지 번호는 가장 빠른 페이지를, date는 가장 이른 날짜를, summary는 가장 긴 것을 유지한다.
    """
    by_key: dict[tuple[str, str], EdiscoveryNode] = {}
    for node in nodes:
        key = (node.type, node.label.lower())
        if key not in by_key:
            by_key[key] = node
            continue
        existing = by_key[key]
        existing.confidence = max(existing.confidence, node.confidence)
        existing.page = min(existing.page, node.page)
        # 더 이른 날짜 우선 (빈 문자열은 무시)
        if node.date_iso and (not existing.date_iso or node.date_iso < existing.date_iso):
            existing.date_iso = node.date_iso
            existing.date_text = node.date_text
        # 더 구체적인 summary 우선
        if len(node.summary) > len(existing.summary):
            existing.summary = node.summary
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

    # 자식 노드 그래프 JSON 생성 — parentId 포함
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
                "issue": n.label if n.type == "issue" else "",
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

def _build_param_suggestion_prompt(page_texts: dict[int, str]) -> str:
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
        sample_blocks.append(f"--- 페이지 {page_no} ---\n{text}")
    sample_text = "\n\n".join(sample_blocks)

    return f"""아래는 법률 문서의 일부 페이지 샘플이다. 이 문서의 특성을 분석하여 e-Discovery GraphRAG 파이프라인에 사용할 최적의 파라미터 3개를 JSON으로 반환하라.

[파라미터 설명]
- chunk_size: 한 번에 LLM에 전달할 텍스트의 단어 수. 문서가 짧고 단순하면 256~512, 사실관계가 복잡하고 많은 쟁점/주체가 등장하면 1024~2048, 매우 복잡하면 2048~4096.
- threshold: 노드 추출 신뢰도 임계값(0.0~1.0). 노이즈가 많거나 보수적으로 추출하려면 0.6~0.7, 균형 잡히게 추출하려면 0.45~0.55, 많은 후보를 남기려면 0.3~0.4.
- max_docs: 처리할 최대 페이지 수. 짧은 문서(50페이지 이하)면 전체 페이지 수, 중간(50~500페이지)이면 50~200, 긴 문서(500페이지 이상)이면 100~500 정도로 샘플링하여 비용과 커버리지를 균형.

[JSON 응답 형식]
{{
  "chunk_size": 1024,
  "threshold": 0.5,
  "max_docs": 100,
  "reasoning": "한국어로 1문장 설명"
}}

결과는 JSON만 반환한다. 다른 설명은 금지.

--- 문서 샘플 ---
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
) -> dict:
    """[Flow: Step 1 (페이지 샘플 선택 및 프롬프트 구성) -> Step 2 (vLLM 호출)
          -> Step 3 (응답 파싱) -> Step 4 (권장 범위 내 clamp) -> Step 5 (파라미터 dict 반환)]

    전체 문서의 페이지 샘플을 LLM에 전달해 e-Discovery 파이프라인의 chunk_size/threshold/max_docs를
    자동 추천받는다. LLM 호출 실패 시 안전한 기본값을 반환한다.
    """
    total_pages = len(page_texts)
    if not page_texts:
        return _clamp_suggested_params({}, total_pages)

    prompt = _build_param_suggestion_prompt(page_texts)
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
    """
    # max_docs → max_chunks 호환 매핑 (api/ediscovery.py의 extract/threshold 엔드포인트 호환)
    if max_chunks is None and max_docs is not None:
        max_chunks = max_docs
    legal_profile: dict = {}
    db = SessionLocal()
    try:
        job = db.get(Job, job_id)
        if job is None:
            return {"error": "job not found"}

        endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint") or settings.default_llm_endpoint
        model = job.model or settings_store.get_setting(db, "llm_model") or settings.default_llm_model
        api_key = settings_store.get_setting(db, "llm_api_key") or ""

        # Step 2: 텍스트 추출
        page_texts = extract_page_texts(job)
        if not page_texts:
            raise ValueError("문서에서 텍스트를 추출할 수 없습니다 (텍스트 레이어/마크다운 모두 비어 있음)")

        # Step 2a: 법률 분야/청구 원인/쟁점/요건사실 자동 추출
        # LLM이 문서 샘플을 보고 민사/형사/행정/이혼/헌법 등 분야와 입증 요건을 추출한다.
        legal_profile = extract_legal_profile(page_texts, endpoint, model, api_key)
        if legal_profile.get("claim_type"):
            job.element_mappings = {
                "claim_type": legal_profile["claim_type"],
                "overall_progress_percent": 0,
                "elements": legal_profile.get("legal_elements", []),
            }
            db.commit()
            logger.info(
                f"[ediscovery] job={job_id} legal_profile 추출: "
                f"legal_domain={legal_profile.get('legal_domain')}, "
                f"claim_type={legal_profile.get('claim_type')}, "
                f"elements={len(legal_profile.get('legal_elements', []))}"
            )

        # Step 2b: 파라미터가 명시되지 않으면 LLM이 전체 문서 샘플을 보고 자동 추천
        auto_params = None
        if chunk_size is None or threshold is None or max_chunks is None:
            auto_params = _suggest_params(page_texts, endpoint, model, api_key)
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
            logger.info(f"[ediscovery] job={job_id} max_chunks 적용: {len(page_texts)}페이지 사용")

        # Step 4: 청킹
        chunks = build_parent_child_chunks(page_texts, chunk_size=chunk_size, page_range=page_range)
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
        raw_nodes = extract_nodes_concurrent(chunks, endpoint, model, api_key)
        logger.info(f"[ediscovery] job={job_id} 원시 노드 {len(raw_nodes)}개 추출")

        # Step 7: 임계값 필터 + 2차 LLM 패스 모순 탐지 + 그래프 조립
        filtered = filter_nodes_by_threshold(raw_nodes, threshold)
        anomalies = detect_anomalies_concurrent(filtered, endpoint, model, api_key)
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
            "legal_profile": legal_profile,
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
            if legal_profile:
                job.ediscovery_metrics["legal_profile"] = legal_profile
            db.commit()
        return {"job_id": job_id, "status": "error", "error": str(e)}
    finally:
        db.close()
