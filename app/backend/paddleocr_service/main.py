#!/usr/bin/env python3
# [Flow: Step 1 (파일 수신) -> Step 2 (PDF→페이지 이미지 변환) -> Step 3 (PaddleOCR Pipeline 호출) -> Step 4 (마크다운 + 이미지 추출) -> Step 5 (docling_client 호환 응답)]
# PaddleOCR-VL 1.6 FastAPI 서비스 — 기존 docling_client.py API 스펙 호환
# vLLM 서버(http://vllm:8080)에 VLM 추론 위임, PP-DocLayoutV2로 레이아웃 분석
# AI Studio API 폴백 엔드포인트(/api/convert) 포함: 외부 API 호출을 서비스 내부로 캡슐화
import base64
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Chungu PaddleOCR-VL Service")

VLLM_SERVER_URL = os.environ.get("VLLM_SERVER_URL", "http://vllm:8080/v1")
PIPELINE_VERSION = os.environ.get("PADDLEOCR_PIPELINE_VERSION", "v1.6")
DATA_DIR = Path("/data")
IMAGE_BASE_DIR = DATA_DIR / "paddleocr_images"

# AI Studio API 설정 (폴백용)
AISTUDIO_API_URL = os.environ.get("PADDLEOCR_API_URL", "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs")
AISTUDIO_API_TOKEN = os.environ.get("PADDLEOCR_API_TOKEN", "")
AISTUDIO_MODEL = os.environ.get("PADDLEOCR_API_MODEL", "PaddleOCR-VL-1.6")
AISTUDIO_UPLOAD_TIMEOUT = int(os.environ.get("PADDLEOCR_UPLOAD_TIMEOUT", "300"))
AISTUDIO_POLL_INTERVAL = int(os.environ.get("PADDLEOCR_POLL_INTERVAL", "5"))
AISTUDIO_POLL_TIMEOUT = int(os.environ.get("PADDLEOCR_POLL_TIMEOUT", "30"))
AISTUDIO_DOWNLOAD_TIMEOUT = int(os.environ.get("PADDLEOCR_DOWNLOAD_TIMEOUT", "120"))
AISTUDIO_MAX_POLL_DURATION = int(os.environ.get("PADDLEOCR_MAX_POLL_DURATION", "1800"))

# 지원 확장자 (PDF + 이미지 + 오피스 문서)
SUPPORTED_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp",
    ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".html", ".htm",
}

# LibreOffice 변환이 필요한 오피스 문서 확장자
OFFICE_EXTENSIONS = {".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".html", ".htm"}

# 전역 PaddleOCR pipeline (지연 초기화)
_pipeline = None
_pipeline_lock = threading.Lock()


def get_pipeline():
    # [Flow: Step 1 (pipeline 잠금) -> Step 2 (PaddleOCRVL 인스턴스 생성) -> Step 3 (vLLM 서버 연결)]
    global _pipeline
    if _pipeline is not None:
        return _pipeline
    with _pipeline_lock:
        if _pipeline is not None:
            return _pipeline
        from paddleocr import PaddleOCRVL
        vllm_model_name = os.environ.get("VLLM_MODEL_NAME", "PaddleOCR-VL-0.9B")
        logger.info(f"[paddleocr] PaddleOCRVL 초기화 (version={PIPELINE_VERSION}, vllm={VLLM_SERVER_URL}, model={vllm_model_name})")
        _pipeline = PaddleOCRVL(
            pipeline_version=PIPELINE_VERSION,
            vl_rec_backend="vllm-server",
            vl_rec_server_url=VLLM_SERVER_URL,
            vl_rec_model_name=vllm_model_name,
        )
        logger.info("[paddleocr] PaddleOCRVL 초기화 완료")
        return _pipeline


def _detect_file_type(filename: str) -> str:
    # 확장자로 파일 타입 추정
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"):
        return "image"
    if ext in OFFICE_EXTENSIONS:
        return "office"
    return "unknown"


def _libreoffice_env() -> dict[str, str]:
    # LibreOffice headless 변환에 필요한 locale 설정
    return {
        **dict(os.environ),
        "LANG": "ko_KR.UTF-8",
        "LC_ALL": "ko_KR.UTF-8",
        "HOME": str(Path("/tmp")),
    }


def _convert_office_to_pdf(input_path: Path, output_dir: Path) -> Path:
    # [Flow: Step 1 (LibreOffice headless 실행) -> Step 2 (PDF 산출물 확인) -> Step 3 (경로 반환)]
    cmd = [
        "libreoffice", "--headless", "--convert-to", "pdf",
        "--outdir", str(output_dir),
        str(input_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            env=_libreoffice_env(),
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"LibreOffice가 설치되지 않았습니다: {e}")
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"LibreOffice PDF 변환 실패: {stderr_text[:500]}")
    pdf_path = output_dir / f"{input_path.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError(f"LibreOffice PDF 산출물을 찾을 수 없습니다: {pdf_path}")
    logger.info(f"[paddleocr] {input_path.name} -> PDF 변환 완료")
    return pdf_path


def _pdf_to_images(pdf_path: Path, dpi: int = 200) -> list[Path]:
    # [Flow: Step 1 (PyMuPDF로 PDF 열기) -> Step 2 (페이지별 이미지 렌더링) -> Step 3 (임시 파일 저장)]
    image_paths: list[Path] = []
    doc = fitz.open(str(pdf_path))
    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    output_dir = pdf_path.parent / f"{pdf_path.stem}_pages"
    output_dir.mkdir(exist_ok=True)
    for page_num in range(len(doc)):
        page = doc[page_num]
        pix = page.get_pixmap(matrix=matrix)
        img_path = output_dir / f"page_{page_num:04d}.png"
        pix.save(str(img_path))
        image_paths.append(img_path)
    doc.close()
    logger.info(f"[paddleocr] PDF → {len(image_paths)}페이지 이미지 변환 완료")
    return image_paths


def _extract_embedded_images(pdf_path: Path, request_id: str) -> list[str]:
    # PDF 내장 이미지 추출 (PaddleOCR 결과와 별도)
    image_dir = IMAGE_BASE_DIR / request_id
    image_dir.mkdir(parents=True, exist_ok=True)
    relative_paths: list[str] = []
    try:
        doc = fitz.open(str(pdf_path))
        img_idx = 0
        for page_num in range(len(doc)):
            page = doc[page_num]
            images = page.get_images(full=True)
            for img_info in images:
                xref = img_info[0]
                try:
                    base_image = doc.extract_image(xref)
                    img_bytes = base_image["image"]
                    ext = base_image.get("ext", "png")
                    out_path = image_dir / f"image_{img_idx:04d}.{ext}"
                    out_path.write_bytes(img_bytes)
                    relative_paths.append(str(out_path.relative_to(DATA_DIR)))
                    img_idx += 1
                except Exception as e:
                    logger.warning(f"[paddleocr] 이미지 추출 실패 (page={page_num}, xref={xref}): {e}")
        doc.close()
    except Exception as e:
        logger.warning(f"[paddleocr] 내장 이미지 추출 실패: {e}")
    return relative_paths


def _run_paddleocr(image_paths: list[Path]) -> dict[str, Any]:
    # [Flow: Step 1 (PaddleOCR pipeline 가져오기) -> Step 2 (각 이미지 추론) -> Step 3 (결과 병합)]
    pipeline = get_pipeline()
    all_markdown_parts: list[str] = []
    total_pages = 0

    for idx, img_path in enumerate(image_paths):
        try:
            output = pipeline.predict(str(img_path))
            for res in output:
                page_md = _extract_markdown_from_result(res)
                if page_md:
                    all_markdown_parts.append(f"<!-- Page {idx + 1} -->\n{page_md}")
                    total_pages += 1
        except Exception as e:
            logger.error(f"[paddleocr] 페이지 {idx + 1} 추론 실패: {e}")
            all_markdown_parts.append(f"<!-- Page {idx + 1} (OCR 실패) -->\n")

    markdown = "\n\n".join(all_markdown_parts)
    return {"markdown": markdown, "page_count": total_pages}


def _extract_markdown_from_result(res: Any) -> str:
    # PaddleOCR 결과에서 마크다운 추출
    try:
        if hasattr(res, "markdown"):
            md = res.markdown
            if hasattr(md, "markdown"):
                return md.markdown
            return str(md)
        if hasattr(res, "json"):
            return str(res.json)
        return str(res)
    except Exception as e:
        logger.warning(f"[paddleocr] 마크다운 추출 실패: {e}")
        return ""


# ─── API 스펙 (docling_client.py 호환) ───

class ConvertResponse(BaseModel):
    markdown: str
    images: list[str]
    page_count: int
    file_type: str
    error: str | None = None


class AsyncConvertResponse(BaseModel):
    task_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: ConvertResponse | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


# 비동기 변환 task store
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _do_convert(task_id: str, input_path: Path, filename: str) -> None:
    # [Flow: Step 1 (파일 타입 확인) -> Step 2 (PDF→이미지 or 단일 이미지) -> Step 3 (PaddleOCR 추론) -> Step 4 (결과 저장)]
    try:
        file_type = _detect_file_type(filename)
        request_id = uuid.uuid4().hex

        if file_type == "office":
            pdf_path = _convert_office_to_pdf(input_path, input_path.parent)
            image_paths = _pdf_to_images(pdf_path)
            if not image_paths:
                raise RuntimeError("PDF에서 페이지 이미지를 추출할 수 없습니다")
            embedded_images = _extract_embedded_images(pdf_path, request_id)
            file_type = "pdf"
        elif file_type == "pdf":
            image_paths = _pdf_to_images(input_path)
            if not image_paths:
                raise RuntimeError("PDF에서 페이지 이미지를 추출할 수 없습니다")
            embedded_images = _extract_embedded_images(input_path, request_id)
        elif file_type == "image":
            image_paths = [input_path]
            embedded_images = []
        else:
            raise RuntimeError(f"지원하지 않는 파일 형식: {filename}")

        ocr_result = _run_paddleocr(image_paths)

        convert_result = ConvertResponse(
            markdown=ocr_result["markdown"],
            images=embedded_images,
            page_count=ocr_result["page_count"],
            file_type=file_type,
        )

        with _tasks_lock:
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["result"] = convert_result
            _tasks[task_id]["finished_at"] = time.time()

        logger.info(f"[paddleocr-async] {filename} 변환 완료 ({ocr_result['page_count']}페이지)")

    except Exception as e:
        logger.exception(f"[paddleocr-async] {filename} 변환 실패: {e}")
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["finished_at"] = time.time()


@app.post("/convert/async", response_model=AsyncConvertResponse)
async def convert_async(file: UploadFile = File(...)) -> AsyncConvertResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {file.filename}")

    task_id = uuid.uuid4().hex
    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir)
    input_path = tmp_path / (file.filename or "input.bin")
    input_path.write_bytes(await file.read())

    with _tasks_lock:
        _tasks[task_id] = {
            "status": "processing",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "tmpdir": tmpdir,
        }

    thread = threading.Thread(target=_do_convert, args=(task_id, input_path, file.filename), daemon=True)
    thread.start()

    return AsyncConvertResponse(task_id=task_id, status="processing")


@app.get("/convert/status/{task_id}", response_model=TaskStatusResponse)
async def get_convert_status(task_id: str) -> TaskStatusResponse:
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task를 찾을 수 없습니다")
    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        result=task.get("result"),
        error=task.get("error"),
        started_at=task.get("started_at"),
        finished_at=task.get("finished_at"),
    )


@app.post("/convert/file", response_model=ConvertResponse)
async def convert_file(file: UploadFile = File(...)) -> ConvertResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {file.filename}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / (file.filename or "input.bin")
        input_path.write_bytes(await file.read())

        file_type = _detect_file_type(file.filename)
        request_id = uuid.uuid4().hex

        if file_type == "office":
            pdf_path = _convert_office_to_pdf(input_path, tmp_path)
            image_paths = _pdf_to_images(pdf_path)
            if not image_paths:
                raise HTTPException(status_code=500, detail="PDF에서 페이지 이미지를 추출할 수 없습니다")
            embedded_images = _extract_embedded_images(pdf_path, request_id)
            file_type = "pdf"
        elif file_type == "pdf":
            image_paths = _pdf_to_images(input_path)
            if not image_paths:
                raise HTTPException(status_code=500, detail="PDF에서 페이지 이미지를 추출할 수 없습니다")
            embedded_images = _extract_embedded_images(input_path, request_id)
        elif file_type == "image":
            image_paths = [input_path]
            embedded_images = []
        else:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식: {file.filename}")

        try:
            ocr_result = _run_paddleocr(image_paths)
        except Exception as e:
            logger.exception(f"[paddleocr-convert] {file.filename} 추론 실패: {e}")
            raise HTTPException(status_code=500, detail=f"PaddleOCR 추론 실패: {e}")

        return ConvertResponse(
            markdown=ocr_result["markdown"],
            images=embedded_images,
            page_count=ocr_result["page_count"],
            file_type=file_type,
        )


@app.get("/images/{image_path:path}")
async def get_image(image_path: str) -> FileResponse:
    base = DATA_DIR.resolve()
    target = (base / image_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="잘못된 이미지 경로")
    if not target.exists():
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")
    return FileResponse(str(target))


# ─── AI Studio API 연동 (폴백용 /api/convert 엔드포인트) ───

def _aistudio_submit_job(file_path: Path) -> str:
    """AI Studio API에 OCR job을 제출하고 jobId를 반환한다.

    [Flow: Step 1 (파일 업로드 + 모델 선택) -> Step 2 (API POST) -> Step 3 (jobId 추출)]
    """
    if not AISTUDIO_API_TOKEN:
        raise RuntimeError("PADDLEOCR_API_TOKEN이 설정되지 않았습니다")

    headers = {"Authorization": f"bearer {AISTUDIO_API_TOKEN}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    data = {"model": AISTUDIO_MODEL, "optionalPayload": json.dumps(optional_payload)}

    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f)}
        resp = requests.post(
            AISTUDIO_API_URL, headers=headers, data=data, files=files,
            timeout=AISTUDIO_UPLOAD_TIMEOUT,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"AI Studio API job 제출 실패: HTTP {resp.status_code} {resp.text[:300]}")

    job_data = resp.json().get("data", {})
    job_id = job_data.get("jobId")
    if not job_id:
        raise RuntimeError(f"AI Studio API jobId 없음: {resp.text[:300]}")

    logger.info(f"[aistudio] job 제출 완료: jobId={job_id}, file={file_path.name}")
    return job_id


def _aistudio_poll_job(job_id: str) -> str:
    """AI Studio API job이 완료될 때까지 폴링하고 JSONL 결과 URL을 반환한다.

    [Flow: Step 1 (5초 간격 폴링) -> Step 2 (state=done 시 jsonUrl 반환) -> Step 3 (state=failed 시 예외)]
    """
    headers = {"Authorization": f"bearer {AISTUDIO_API_TOKEN}"}
    poll_url = f"{AISTUDIO_API_URL}/{job_id}"
    start_time = time.monotonic()

    poll_count = 0
    while True:
        elapsed = time.monotonic() - start_time
        if elapsed > AISTUDIO_MAX_POLL_DURATION:
            raise TimeoutError(f"AI Studio API 폴링 타임아웃: {elapsed:.0f}s > {AISTUDIO_MAX_POLL_DURATION}s")

        poll_count += 1
        try:
            resp = requests.get(poll_url, headers=headers, timeout=AISTUDIO_POLL_TIMEOUT)
        except Exception as e:
            logger.warning(f"[aistudio] 폴링 실패 (poll {poll_count}): {e}")
            time.sleep(AISTUDIO_POLL_INTERVAL)
            continue

        if resp.status_code != 200:
            logger.warning(f"[aistudio] 폴링 HTTP {resp.status_code} (poll {poll_count})")
            time.sleep(AISTUDIO_POLL_INTERVAL)
            continue

        data = resp.json().get("data", {})
        state = data.get("state", "")

        if state == "done":
            json_url = data.get("resultUrl", {}).get("jsonUrl", "")
            if not json_url:
                raise RuntimeError(f"AI Studio API 결과 URL 없음: {json.dumps(data)[:300]}")
            logger.info(f"[aistudio] job 완료: jobId={job_id}, elapsed={elapsed:.0f}s, polls={poll_count}")
            return json_url

        if state == "failed":
            error_msg = data.get("errorMsg", "알 수 없는 오류")
            raise RuntimeError(f"AI Studio API job 실패: {error_msg}")

        logger.debug(f"[aistudio] 폴링 중 (poll {poll_count}): state={state}, elapsed={elapsed:.0f}s")
        time.sleep(AISTUDIO_POLL_INTERVAL)


def _aistudio_download_and_parse(jsonl_url: str, request_id: str) -> dict[str, Any]:
    """JSONL 결과를 다운로드하고 페이지별 markdown + 이미지로 변환한다.

    [Flow: Step 1 (JSONL 다운로드) -> Step 2 (라인별 파싱) -> Step 3 (layoutParsingResults 순회) -> Step 4 (markdown.text 추출) -> Step 5 (images 다운로드 + src 치환) -> Step 6 (페이지별 마크다운 병합)]
    """
    resp = requests.get(jsonl_url, timeout=AISTUDIO_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    lines = [line.strip() for line in resp.text.strip().split("\n") if line.strip()]
    if not lines:
        raise RuntimeError("AI Studio API JSONL 결과가 비어있음")

    image_dir = IMAGE_BASE_DIR / request_id
    image_dir.mkdir(parents=True, exist_ok=True)

    all_page_markdowns: list[str] = []
    downloaded_images: list[str] = []
    page_num = 0

    for line in lines:
        parsed = json.loads(line)
        result = parsed.get("result", {})
        if not isinstance(result, dict):
            continue

        layout_results = result.get("layoutParsingResults", [])
        for lpr in layout_results:
            page_num += 1
            md = lpr.get("markdown", {})
            md_text = md.get("text", "") if isinstance(md, dict) else ""
            md_images = md.get("images", {}) if isinstance(md, dict) else {}

            # 이미지 다운로드 및 base64 data URI로 markdown에 직접 삽입
            for img_rel_path, img_url in md_images.items():
                try:
                    img_resp = requests.get(img_url, timeout=60)
                    img_resp.raise_for_status()
                    img_b64 = base64.b64encode(img_resp.content).decode("ascii")
                    mime = "image/png" if Path(img_rel_path).suffix.lower() == ".png" else "image/jpeg"
                    data_uri = f"data:{mime};base64,{img_b64}"
                    md_text = md_text.replace(f'src="{img_rel_path}"', f'src="{data_uri}"')
                    md_text = md_text.replace(f"src='{img_rel_path}'", f"src='{data_uri}'")
                    downloaded_images.append(img_rel_path)
                except Exception as e:
                    logger.warning(f"[aistudio] 이미지 다운로드 실패 ({img_rel_path}): {e}")

            page_header = f"<!-- Page {page_num} -->\n" if page_num > 1 else ""
            all_page_markdowns.append(f"{page_header}{md_text}")

    markdown = "\n\n".join(all_page_markdowns)
    logger.info(f"[aistudio] 변환 완료: {page_num}페이지, {len(downloaded_images)} 이미지")

    return {
        "markdown": markdown,
        "images": downloaded_images,
        "page_count": page_num,
    }


def _do_aistudio_convert(task_id: str, input_path: Path, filename: str) -> None:
    """AI Studio API를 통한 비동기 변환 작업을 실행한다.

    [Flow: Step 1 (job 제출) -> Step 2 (폴링) -> Step 3 (JSONL 다운로드/파싱) -> Step 4 (결과 저장)]
    """
    try:
        request_id = uuid.uuid4().hex
        job_id = _aistudio_submit_job(input_path)
        jsonl_url = _aistudio_poll_job(job_id)
        ocr_result = _aistudio_download_and_parse(jsonl_url, request_id)

        convert_result = ConvertResponse(
            markdown=ocr_result["markdown"],
            images=ocr_result["images"],
            page_count=ocr_result["page_count"],
            file_type=_detect_file_type(filename),
        )

        with _tasks_lock:
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["result"] = convert_result
            _tasks[task_id]["finished_at"] = time.time()

        logger.info(f"[aistudio-async] {filename} 변환 완료 ({ocr_result['page_count']}페이지)")

    except Exception as e:
        logger.exception(f"[aistudio-async] {filename} 변환 실패: {e}")
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["finished_at"] = time.time()


@app.post("/api/convert", response_model=AsyncConvertResponse)
async def api_convert(file: UploadFile = File(...)) -> AsyncConvertResponse:
    """AI Studio API를 호출하여 OCR 변환을 수행한다 (폴백 전용 엔드포인트).

    토큰은 서비스 환경 변수에서만 사용되어 클라이언트에 노출되지 않는다.
    """
    if not AISTUDIO_API_TOKEN:
        raise HTTPException(status_code=503, detail="PADDLEOCR_API_TOKEN이 설정되지 않았습니다")

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

    ext = Path(file.filename).suffix.lower()
    image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
    if ext not in image_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"AI Studio API는 이미지만 지원합니다 (png/jpg/bmp/tiff/webp): {file.filename}",
        )

    task_id = uuid.uuid4().hex
    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir)
    input_path = tmp_path / (file.filename or "input.bin")
    input_path.write_bytes(await file.read())

    with _tasks_lock:
        _tasks[task_id] = {
            "status": "processing",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "tmpdir": tmpdir,
        }

    thread = threading.Thread(target=_do_aistudio_convert, args=(task_id, input_path, file.filename), daemon=True)
    thread.start()

    return AsyncConvertResponse(task_id=task_id, status="processing")


@app.get("/api/convert/status/{task_id}", response_model=TaskStatusResponse)
async def api_convert_status(task_id: str) -> TaskStatusResponse:
    """AI Studio API 변환 작업의 상태를 조회한다 (/convert/status/{task_id}와 동일 스펙)."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task를 찾을 수 없습니다")
    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        result=task.get("result"),
        error=task.get("error"),
        started_at=task.get("started_at"),
        finished_at=task.get("finished_at"),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(_: Any, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"detail": f"내부 오류: {exc}"})
