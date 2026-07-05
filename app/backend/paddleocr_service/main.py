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
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

# 로컬 개발 및 Docker 모두에서 backend.core 패키지를 찾을 수 있도록 상위 경로 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # PyMuPDF
import requests
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PROOF PaddleOCR-VL Service")

VLLM_SERVER_URL = os.environ.get("VLLM_SERVER_URL", "http://vllm:8080/v1")
VLLM_MODEL_NAME = os.environ.get("VLLM_MODEL_NAME", "PaddleOCR-VL-0.9B")
PIPELINE_VERSION = os.environ.get("PADDLEOCR_PIPELINE_VERSION", "v1.6")
DATA_DIR = Path("/data")
IMAGE_BASE_DIR = DATA_DIR / "paddleocr_images"

# PaddleOCR 자동 파라미터 추천 설정 (Vision LLM 샘플 기반)
AUTO_PARAMETER_ENABLED = os.environ.get("PADDLEOCR_AUTO_PARAMETER_ENABLED", "true").lower() == "true"
SAMPLE_DPI = int(os.environ.get("PADDLEOCR_SAMPLE_DPI", "150"))
SAMPLE_MAX_TOKENS = int(os.environ.get("PADDLEOCR_SAMPLE_MAX_TOKENS", "2000"))

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
        raise RuntimeError(f"LibreOffice is not installed: {e}")
    if result.returncode != 0:
        stderr_text = result.stderr.decode("utf-8", errors="ignore")
        raise RuntimeError(f"LibreOffice PDF conversion failed: {stderr_text[:500]}")
    pdf_path = output_dir / f"{input_path.stem}.pdf"
    if not pdf_path.exists():
        raise RuntimeError(f"LibreOffice PDF output not found: {pdf_path}")
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


def _get_paddleocr_params(pdf_path: Path | None, work_dir: Path) -> dict[str, Any]:
    """PDF/오피스 문서에 대해 자동 파라미터 추천을 수행한다.

    [Flow: Step 1 (자동 추천 활성화 여부 확인) -> Step 2 (PDF 경로 확인) -> Step 3 (샘플 추출 및 LLM 추천) -> Step 4 (파라미터 반환)]

    Args:
        pdf_path: 샘플을 추출할 PDF 경로 (이미지 파일인 경우 None)
        work_dir: 샘플 이미지를 저장할 작업 디렉터리

    Returns:
        PaddleOCRVL.predict()에 전달할 파라미터 딕셔너리. 비활성화 또는 이미지 파일이면 빈 dict
    """
    if not AUTO_PARAMETER_ENABLED:
        return {}
    if pdf_path is None or not pdf_path.exists():
        return {}

    try:
        from backend.core.paddleocr_parameter_recommender import decide_parameters
    except ImportError:
        try:
            from core.paddleocr_parameter_recommender import decide_parameters
        except ImportError:
            logger.warning("[paddleocr] 파라미터 추천 모듈 import 실패, 기본값 사용")
            return {}

    sample_dir = work_dir / "samples"
    try:
        params = decide_parameters(
            pdf_path=pdf_path,
            sample_dir=sample_dir,
            endpoint=VLLM_SERVER_URL,
            model=VLLM_MODEL_NAME,
            api_key="",
            dpi=SAMPLE_DPI,
            max_tokens=SAMPLE_MAX_TOKENS,
        )
        logger.info(f"[paddleocr] 자동 추천 파라미터 적용: {params}")
        return params
    except Exception as e:
        logger.warning(f"[paddleocr] 파라미터 추천 실패, 기본값 사용: {e}")
        return {}


def _run_paddleocr(
    image_paths: list[Path],
    params: dict[str, Any] | None = None,
    capture_layout: bool = False,
    force_no_geometric_correction: bool = False,
) -> dict[str, Any]:
    # [Flow: Step 1 (PaddleOCR pipeline 가져오기) -> Step 2 (파라미터 병합) -> Step 3 (각 이미지 추론) -> Step 4 (결과 병합, 필요 시 layout bbox 수집)]
    pipeline = get_pipeline()
    all_markdown_parts: list[str] = []
    layout_pages: list[dict] = []
    total_pages = 0
    predict_params = dict(params or {})
    if force_no_geometric_correction:
        # PDF 하이라이트/여백 주석 기능: use_doc_unwarping/orientation_classify가 켜지면
        # bbox 좌표가 "보정된 이미지" 기준으로 나와 원본 페이지 좌표와 어긋나므로 강제로 끈다.
        predict_params["use_doc_orientation_classify"] = False
        predict_params["use_doc_unwarping"] = False

    for idx, img_path in enumerate(image_paths):
        try:
            output = pipeline.predict(str(img_path), **predict_params)
            for res in output:
                page_md = _extract_markdown_from_result(res)
                if page_md:
                    all_markdown_parts.append(f"<!-- Page {idx + 1} -->\n{page_md}")
                    total_pages += 1
                if capture_layout:
                    layout_pages.append(_extract_layout_from_result(res))
        except Exception as e:
            logger.error(f"[paddleocr] 페이지 {idx + 1} 추론 실패: {e}")
            all_markdown_parts.append(f"<!-- Page {idx + 1} (OCR 실패) -->\n")
            if capture_layout:
                layout_pages.append({})

    markdown = "\n\n".join(all_markdown_parts)
    return {"markdown": markdown, "page_count": total_pages, "layout": layout_pages}


def _extract_layout_from_result(res: Any) -> dict:
    """PaddleOCR 결과 객체에서 bbox가 포함된 원본 레이아웃(res.json)을 추출한다.

    layout_det_res.boxes[].coordinate, overall_ocr_res.{rec_polys,rec_texts,rec_boxes},
    table_res_list[].{cell_box_list,pred_html,table_ocr_pred} 등을 그대로 담고 있다.
    AI Studio API의 prunedResult와 동일한 스키마(input_path/page_index 제외)이므로
    core/ocr_layout.py의 파서가 두 소스를 동일하게 처리할 수 있다.
    """
    try:
        if hasattr(res, "json"):
            raw = res.json
            return raw.get("res", raw) if isinstance(raw, dict) else {}
        return {}
    except Exception as e:
        logger.warning(f"[paddleocr] 레이아웃(bbox) 추출 실패: {e}")
        return {}


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
    # PDF 하이라이트/여백 주석 기능용 원본 레이아웃(bbox) — 페이지 순서대로 res.json/prunedResult 그대로 저장
    # (하위 호환: 기존 소비자는 이 필드를 무시하면 되므로 기본값 빈 리스트)
    layout: list[dict] = []
    # 페이지별 90° 단위 회전 각도 코드 (0/1/2/3 = 0°/90°/180°/270°, -1 = 미적용)
    # useDocOrientationClassify=True일 때 AI Studio가 보정한 각도. 주석 PDF 생성 시 클라이언트가
    # 원본 이미지를 같은 각도로 회전시켜 보정 결과를 재현하기 위해 사용.
    page_angles: list[int] = []


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
    # [Flow: Step 1 (파일 타입 확인) -> Step 2 (PDF→이미지 or 단일 이미지) -> Step 3 (자동 파라미터 추천) -> Step 4 (PaddleOCR 추론) -> Step 5 (결과 저장)]
    try:
        file_type = _detect_file_type(filename)
        request_id = uuid.uuid4().hex
        pdf_path: Path | None = None

        if file_type == "office":
            pdf_path = _convert_office_to_pdf(input_path, input_path.parent)
            image_paths = _pdf_to_images(pdf_path)
            if not image_paths:
                raise RuntimeError("Failed to extract page images from PDF")
            embedded_images = _extract_embedded_images(pdf_path, request_id)
            file_type = "pdf"
        elif file_type == "pdf":
            pdf_path = input_path
            image_paths = _pdf_to_images(input_path)
            if not image_paths:
                raise RuntimeError("Failed to extract page images from PDF")
            embedded_images = _extract_embedded_images(input_path, request_id)
        elif file_type == "image":
            image_paths = [input_path]
            embedded_images = []
        else:
            raise RuntimeError(f"Unsupported file type: {filename}")

        params = _get_paddleocr_params(pdf_path, input_path.parent)
        ocr_result = _run_paddleocr(image_paths, params)

        convert_result = ConvertResponse(
            markdown=ocr_result["markdown"],
            images=embedded_images,
            page_count=ocr_result["page_count"],
            file_type=file_type,
            layout=ocr_result.get("layout", []),
            page_angles=ocr_result.get("page_angles", []),
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
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {file.filename}")

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
        raise HTTPException(status_code=404, detail="Task not found")
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
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Unsupported file format: {file.filename}")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / (file.filename or "input.bin")
        input_path.write_bytes(await file.read())

        file_type = _detect_file_type(file.filename)
        request_id = uuid.uuid4().hex
        pdf_path: Path | None = None

        if file_type == "office":
            pdf_path = _convert_office_to_pdf(input_path, tmp_path)
            image_paths = _pdf_to_images(pdf_path)
            if not image_paths:
                raise HTTPException(status_code=500, detail="Failed to extract page images from PDF")
            embedded_images = _extract_embedded_images(pdf_path, request_id)
            file_type = "pdf"
        elif file_type == "pdf":
            pdf_path = input_path
            image_paths = _pdf_to_images(input_path)
            if not image_paths:
                raise HTTPException(status_code=500, detail="Failed to extract page images from PDF")
            embedded_images = _extract_embedded_images(input_path, request_id)
        elif file_type == "image":
            image_paths = [input_path]
            embedded_images = []
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.filename}")

        try:
            params = _get_paddleocr_params(pdf_path, tmp_path)
            ocr_result = _run_paddleocr(image_paths, params)
        except Exception as e:
            logger.exception(f"[paddleocr-convert] {file.filename} 추론 실패: {e}")
            raise HTTPException(status_code=500, detail=f"PaddleOCR inference failed: {e}")

        return ConvertResponse(
            markdown=ocr_result["markdown"],
            images=embedded_images,
            page_count=ocr_result["page_count"],
            file_type=file_type,
            page_angles=ocr_result.get("page_angles", []),
        )


@app.get("/images/{image_path:path}")
async def get_image(image_path: str) -> FileResponse:
    base = DATA_DIR.resolve()
    target = (base / image_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid image path")
    if not target.exists():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(str(target))


# ─── AI Studio API 연동 (폴백용 /api/convert 엔드포인트) ───

def _snake_to_camel(snake: str) -> str:
    """snake_case 문자열을 camelCase로 변환한다.

    Args:
        snake: snake_case 형식 문자열

    Returns:
        camelCase 형식 문자열
    """
    parts = snake.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


def _convert_params_to_camel_case(params: dict[str, Any]) -> dict[str, Any]:
    """PaddleOCRVL 파라미터를 AI Studio API optionalPayload camelCase 키로 변환한다.

    Args:
        params: snake_case 키의 파라미터 딕셔너리

    Returns:
        camelCase 키의 파라미터 딕셔너리
    """
    return {_snake_to_camel(k): v for k, v in params.items()}


def _aistudio_submit_job(file_path: Path, params: dict[str, Any] | None = None) -> str:
    """AI Studio API에 OCR job을 제출하고 jobId를 반환한다.

    [Flow: Step 1 (파라미터 camelCase 변환) -> Step 2 (파일 업로드 + 모델 선택) -> Step 3 (API POST) -> Step 4 (jobId 추출)]
    """
    if not AISTUDIO_API_TOKEN:
        raise RuntimeError("PADDLEOCR_API_TOKEN is not configured")

    headers = {"Authorization": f"bearer {AISTUDIO_API_TOKEN}"}
    # [Flow: 대회전(90/180/270°) 자동 보정 활성화]
    # useDocOrientationClassify=True → AI Studio가 문서 방향을 0/1/2/3(0°/90°/180°/270°)으로
    # 분류하고 보정한 이미지 기준으로 bbox를 반환. 보정된 페이지 이미지 자체는 반환하지 않으므로
    # 클라이언트가 주석 PDF 생성 시 응답의 doc_preprocessor_res.angle을 참조해 90° 회전을 재현해야 한다.
    # useDocUnwarping=False 유지: 왜곡 보정은 변환 행렬을 응답에 노출하지 않아 bbox 역매핑이 불가하므로
    # 주석 기능에 해로움.
    optional_payload = {
        "useDocOrientationClassify": True,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    if params:
        optional_payload.update(_convert_params_to_camel_case(params))
    data = {"model": AISTUDIO_MODEL, "optionalPayload": json.dumps(optional_payload)}

    with open(file_path, "rb") as f:
        files = {"file": (file_path.name, f)}
        resp = requests.post(
            AISTUDIO_API_URL, headers=headers, data=data, files=files,
            timeout=AISTUDIO_UPLOAD_TIMEOUT,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"AI Studio API job submission failed: HTTP {resp.status_code} {resp.text[:300]}")

    job_data = resp.json().get("data", {})
    job_id = job_data.get("jobId")
    if not job_id:
        raise RuntimeError(f"AI Studio API missing jobId: {resp.text[:300]}")

    logger.info(f"[aistudio] job 제출 완료: jobId={job_id}, file={file_path.name}, params={optional_payload}")
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
            raise TimeoutError(f"AI Studio API polling timeout: {elapsed:.0f}s > {AISTUDIO_MAX_POLL_DURATION}s")

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
                raise RuntimeError(f"AI Studio API missing result URL: {json.dumps(data)[:300]}")
            logger.info(f"[aistudio] job 완료: jobId={job_id}, elapsed={elapsed:.0f}s, polls={poll_count}")
            return json_url

        if state == "failed":
            error_msg = data.get("errorMsg", "Unknown error")
            raise RuntimeError(f"AI Studio API job failed: {error_msg}")

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
        raise RuntimeError("AI Studio API JSONL result is empty")

    image_dir = IMAGE_BASE_DIR / request_id
    image_dir.mkdir(parents=True, exist_ok=True)

    all_page_markdowns: list[str] = []
    downloaded_images: list[str] = []
    layout_pages: list[dict] = []
    # 페이지별 90° 단위 회전 각도 (0/90/180/270). 주석 PDF 생성 시 클라이언트가 이미지를
    # 같은 각도로 회전시켜 AI Studio 보정 결과를 재현하기 위해 사용.
    page_angles: list[int] = []
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
            # prunedResult == 로컬 파이프라인 res.json에서 input_path/page_index만 제거한 것과 동일 스키마.
            # PDF 하이라이트/여백 주석 기능의 bbox 소스로 그대로 사용한다 (core/ocr_layout.py에서 파싱).
            pruned = lpr.get("prunedResult", {}) or {}
            layout_pages.append(pruned)
            # doc_preprocessor_res.angle 추출 (0/1/2/3 = 0°/90°/180°/270°, -1 = 미적용)
            doc_pre = pruned.get("doc_preprocessor_res", {}) if isinstance(pruned, dict) else {}
            angle_code = doc_pre.get("angle", -1) if isinstance(doc_pre, dict) else -1
            page_angles.append(int(angle_code) if isinstance(angle_code, (int, float)) else -1)

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

            # div 래퍼 제거 (ProseMirror 호환성)
            md_text = re.sub(r'<div[^>]*>(<img[^>]*>)</div>', r'\1', md_text)

            page_header = f"<!-- Page {page_num} -->\n" if page_num > 1 else ""
            all_page_markdowns.append(f"{page_header}{md_text}")

    markdown = "\n\n".join(all_page_markdowns)
    logger.info(f"[aistudio] 변환 완료: {page_num}페이지, {len(downloaded_images)} 이미지")

    return {
        "markdown": markdown,
        "images": downloaded_images,
        "page_count": page_num,
        "layout": layout_pages,
        "page_angles": page_angles,
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
            layout=ocr_result.get("layout", []),
            page_angles=ocr_result.get("page_angles", []),
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
        raise HTTPException(status_code=503, detail="PADDLEOCR_API_TOKEN is not configured")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
    if ext not in image_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"AI Studio API supports images only (png/jpg/bmp/tiff/webp): {file.filename}",
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
        raise HTTPException(status_code=404, detail="Task not found")
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
    return JSONResponse(status_code=500, content={"detail": f"Internal error: {exc}"})
