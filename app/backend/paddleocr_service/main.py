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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
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
AISTUDIO_POLL_INTERVAL = int(os.environ.get("PADDLEOCR_POLL_INTERVAL", "1"))
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

# PDF user-space 변환 상수
PDF_POINTS_PER_INCH = 72.0
OCR_RENDER_DPI = 300  # _pdf_to_images와 동일한 DPI

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


def _pdf_to_images(pdf_path: Path, dpi: int = 300) -> list[Path]:
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
    pdf_source_path: Path | None = None,
) -> dict[str, Any]:
    # [Flow: Step 1 (PaddleOCR pipeline 가져오기) -> Step 2 (파라미터 병합)
    #       -> Step 3 (원본 PDF 페이지 크기 측정) -> Step 4 (각 이미지 추론)
    #       -> Step 5 (결과 병합, 필요 시 layout bbox 수집)]
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

    # PDF 원본을 직접 입력할 경우, PaddleOCR 반환 bbox 좌표계와 DPI를 추정하기 위해
    # 원본 PDF의 페이지 크기(포인트)를 미리 측정한다.
    page_sizes: dict[int, tuple[float, float]] = {}
    if pdf_source_path and pdf_source_path.exists():
        try:
            doc = fitz.open(str(pdf_source_path))
            for i, page in enumerate(doc):
                page_sizes[i] = (page.rect.width, page.rect.height)
            doc.close()
            logger.info(
                f"[paddleocr] PDF 원본 페이지 크기 측정 완료: {pdf_source_path.name} "
                f"({len(page_sizes)}페이지)"
            )
        except Exception as e:
            logger.warning(f"[paddleocr] PDF 원본 페이지 크기 측정 실패: {e}")

    for idx, img_path in enumerate(image_paths):
        try:
            output = pipeline.predict(str(img_path), **predict_params)
            for res in output:
                page_md = _extract_markdown_from_result(res)
                if page_md:
                    all_markdown_parts.append(f"<!-- Page {idx + 1} -->\n{page_md}")
                    total_pages += 1
                if capture_layout:
                    page_width_pt, page_height_pt = page_sizes.get(idx, (None, None))
                    layout_pages.append(
                        _extract_layout_from_result(res, page_height_pt=page_height_pt)
                    )
        except Exception as e:
            logger.error(f"[paddleocr] 페이지 {idx + 1} 추론 실패: {e}")
            all_markdown_parts.append(f"<!-- Page {idx + 1} (OCR 실패) -->\n")
            if capture_layout:
                layout_pages.append({})

    markdown = "\n\n".join(all_markdown_parts)
    return {"markdown": markdown, "page_count": total_pages, "layout": layout_pages}


def _image_bbox_to_pdf_rect(
    bbox: list[float] | tuple[float, ...],
    page_height_px: float,
    scale: float,
) -> list[float]:
    """PaddleOCR-VL 이미지 좌표계(top-left origin, y↓) bbox를 PDF user-space(rect)로 변환한다.

    [Flow: Step 1 (x는 동일 방향으로 스케일) -> Step 2 (y는 페이지 높이에서 뺀 뒤 스케일)
          -> Step 3 (PDF user-space [x0, y0, x1, y1] 반환)]

    Args:
        bbox: [xmin, ymin, xmax, ymax] 이미지 좌표계 bbox.
        page_height_px: 이미지 전체 높이(픽셀).
        scale: PDF 포인트/픽셀 변환 비율 (PDF_POINTS_PER_INCH / OCR_RENDER_DPI).

    Returns:
        [x0, y0, x1, y1] PDF user-space 좌표 (y↑, 원점 좌하단).
    """
    if not bbox or len(bbox) < 4:
        return list(bbox) if bbox else []
    x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    pdf_y0 = (page_height_px - y1) * scale
    pdf_y1 = (page_height_px - y0) * scale
    return [x0 * scale, pdf_y0, x1 * scale, pdf_y1]


def _image_polygon_to_pdf_points(
    points: list[list[float]] | list[tuple[float, ...]],
    page_height_px: float,
    scale: float,
) -> list[list[float]]:
    """PaddleOCR-VL 이미지 좌표계 다각형 점들을 PDF user-space로 변환한다.

    [Flow: Step 1 (각 점의 x를 스케일) -> Step 2 (y를 페이지 높이에서 뺀 뒤 스케일)
          -> Step 3 (변환된 점 목록 반환)]
    """
    if not points:
        return []
    converted: list[list[float]] = []
    for pt in points:
        if not pt or len(pt) < 2:
            converted.append(list(pt) if pt else [])
            continue
        x, y = float(pt[0]), float(pt[1])
        converted.append([x * scale, (page_height_px - y) * scale])
    return converted


def _detect_coordinate_system(
    page_height_px: float,
    page_height_pt: float | None,
) -> tuple[str, float]:
    """PaddleOCR-VL 반환값의 좌표계와 스케일을 추정한다.

    [Flow: Step 1 (원본 PDF 페이지 높이(포인트) 확인)
          -> Step 2 (layout["height"]와 비교)
          -> Step 3 (PDF user-space 또는 이미지 좌표계 판정 및 scale 반환)]

    PDF 원본 페이지 높이(포인트)가 주어지면, layout["height"]가 이와 거의 같으면
    PaddleOCR이 이미 PDF user-space를 반환한 것으로 보고 y-flip을 생략한다.
    차이가 크면 이미지 좌표계로 보고, 원본 PDF 높이 / 픽셀 높이로 scale을 역산한다.

    PDF 원본 정보가 없으면 기존 300 DPI 가정을 유지한다.

    Args:
        page_height_px: PaddleOCR layout["height"] 값 (픽셀 또는 포인트).
        page_height_pt: 원본 PDF 페이지 높이 (포인트, 없을 수 있음).

    Returns:
        (coordinate_system, scale) 튜플.
        coordinate_system: "pdf_user" | "image".
        scale: PDF user-space 포인트/소스 단위 변환 비율.
    """
    if page_height_pt is not None and page_height_pt > 0 and page_height_px > 0:
        if abs(page_height_px - page_height_pt) <= 1.0:
            logger.info(
                f"[paddleocr] 좌표계 감지: PDF user-space (height={page_height_px:.2f}, "
                f"page_height_pt={page_height_pt:.2f})"
            )
            return "pdf_user", 1.0
        scale = page_height_pt / page_height_px
        inferred_dpi = scale * PDF_POINTS_PER_INCH
        logger.info(
            f"[paddleocr] 좌표계 감지: 이미지 좌표계 (height={page_height_px:.2f}px, "
            f"page_height_pt={page_height_pt:.2f}pt, 추정 DPI={inferred_dpi:.1f})"
        )
        return "image", scale

    # PDF 원본 정보 없음: 기존 300 DPI 가정
    scale = PDF_POINTS_PER_INCH / OCR_RENDER_DPI
    logger.info(
        f"[paddleocr] 좌표계 감지: 이미지 좌표계 (기본 300 DPI, scale={scale:.4f})"
    )
    return "image", scale


def _extract_layout_from_result(
    res: Any,
    page_height_pt: float | None = None,
) -> dict:
    """PaddleOCR 결과 객체에서 bbox를 PDF user-space로 변환한 레이아웃을 반환한다.

    [Flow: Step 1 (res.json 추출) -> Step 2 (페이지 픽셀 높이 확인)
          -> Step 3 (좌표계 및 실제 렌더링 DPI 추정)
          -> Step 4 (parsing_res_list / layout_det_res / overall_ocr_res의 bbox 좌표계 변환)
          -> Step 5 (PDF user-space 기준 layout dict 반환)]

    PaddleOCR-VL-1.6은 기본적으로 이미지 좌표계(top-left origin, y↓)를 사용하지만,
    원본 PDF를 직접 입력하면 PDF user-space(bottom-left origin, y↑)를 반환하거나
    내부 렌더링 DPI가 300이 아닐 수 있다. 따라서 원본 PDF 페이지 높이(포인트)를
    받아 좌표계와 scale을 동적으로 추정한다.
    """
    try:
        if isinstance(res, dict):
            # AI Studio prunedResult: res 키가 없으므로 dict 자체를 layout으로 사용
            layout = res.get("res", res) if "res" in res else res
        elif hasattr(res, "json"):
            raw = res.json
            layout = raw.get("res", raw) if isinstance(raw, dict) else {}
        else:
            layout = {}
    except Exception as e:
        logger.warning(f"[paddleocr] 레이아웃(bbox) 추출 실패: {e}")
        return {}

    if not isinstance(layout, dict):
        return layout

    page_height_px = layout.get("height")
    if not isinstance(page_height_px, (int, float)) or page_height_px <= 0:
        logger.warning("[paddleocr] layout 높이 정보가 없어 bbox 좌표계 변환을 건너뜁니다.")
        return layout

    coordinate_system, scale = _detect_coordinate_system(page_height_px, page_height_pt)
    layout["_coordinate_system"] = coordinate_system
    layout["_scale"] = scale
    layout["_page_height_pt"] = page_height_pt

    if coordinate_system == "pdf_user":
        # PaddleOCR이 이미 PDF user-space를 반환하면 추가 변환 불필요
        return layout

    # 이미지 좌표계 → PDF user-space 변환
    # parsing_res_list 블록 bbox 및 polygon_points 변환
    for block in layout.get("parsing_res_list", []):
        if not isinstance(block, dict):
            continue
        bbox = block.get("block_bbox")
        if bbox:
            block["block_bbox"] = _image_bbox_to_pdf_rect(bbox, page_height_px, scale)
        points = block.get("block_polygon_points")
        if points:
            block["block_polygon_points"] = _image_polygon_to_pdf_points(
                points, page_height_px, scale
            )

    # layout_det_res 내부 boxes 변환
    layout_det = layout.get("layout_det_res") or {}
    if isinstance(layout_det, dict):
        for box in layout_det.get("boxes", []):
            if not isinstance(box, dict):
                continue
            coord = box.get("coordinate")
            if coord:
                box["coordinate"] = _image_bbox_to_pdf_rect(coord, page_height_px, scale)
            points = box.get("polygon_points")
            if points:
                box["polygon_points"] = _image_polygon_to_pdf_points(
                    points, page_height_px, scale
                )

    # overall_ocr_res.rec_boxes 변환
    ocr_res = layout.get("overall_ocr_res") or {}
    if isinstance(ocr_res, dict):
        rec_boxes = ocr_res.get("rec_boxes")
        if isinstance(rec_boxes, list):
            ocr_res["rec_boxes"] = [
                _image_bbox_to_pdf_rect(b, page_height_px, scale)
                if b and len(b) >= 4
                else b
                for b in rec_boxes
            ]

    return layout


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


def _do_convert(
    task_id: str,
    input_path: Path,
    filename: str,
    capture_layout: bool = False,
) -> None:
    # [Flow: Step 1 (파일 타입 확인) -> Step 2 (PDF→이미지 or 단일 이미지)
    #       -> Step 3 (자동 파라미터 추천) -> Step 4 (PaddleOCR 추론)
    #       -> Step 5 (결과 저장)]
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
        ocr_result = _run_paddleocr(
            image_paths,
            params,
            capture_layout=capture_layout,
            pdf_source_path=pdf_path,
        )

        convert_result = ConvertResponse(
            markdown=ocr_result["markdown"],
            images=embedded_images,
            page_count=ocr_result["page_count"],
            file_type=file_type,
            layout=ocr_result.get("layout", []) if capture_layout else [],
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
async def convert_async(
    file: UploadFile = File(...),
    capture_layout: bool = Form(False),
) -> AsyncConvertResponse:
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
            "capture_layout": capture_layout,
        }

    thread = threading.Thread(
        target=_do_convert,
        args=(task_id, input_path, file.filename, capture_layout),
        daemon=True,
    )
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
async def convert_file(
    file: UploadFile = File(...),
    capture_layout: bool = Form(False),
) -> ConvertResponse:
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
            ocr_result = _run_paddleocr(
                image_paths,
                params,
                capture_layout=capture_layout,
                pdf_source_path=pdf_path,
            )
        except Exception as e:
            logger.exception(f"[paddleocr-convert] {file.filename} 추론 실패: {e}")
            raise HTTPException(status_code=500, detail=f"PaddleOCR inference failed: {e}")

        return ConvertResponse(
            markdown=ocr_result["markdown"],
            images=embedded_images,
            page_count=ocr_result["page_count"],
            file_type=file_type,
            layout=ocr_result.get("layout", []) if capture_layout else [],
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


def _aistudio_download_and_parse(
    jsonl_url: str,
    request_id: str,
    pdf_source_path: Path | None = None,
) -> dict[str, Any]:
    """JSONL 결과를 다운로드하고 페이지별 markdown + 이미지로 변환한다.

    [Flow: Step 1 (JSONL 다운로드) -> Step 2 (원본 PDF 페이지 크기 측정)
          -> Step 3 (라인별 파싱) -> Step 4 (layoutParsingResults 순회)
          -> Step 5 (markdown.text 추출) -> Step 6 (bbox 좌표계 동적 변환)
          -> Step 7 (images 다운로드 + src 치환) -> Step 8 (페이지별 마크다운 병합)]

    Args:
        pdf_source_path: 원본 PDF 경로. AI Studio에 원본 PDF를 직접 제출했을 때,
            반환 bbox 좌표계와 DPI를 추정하기 위해 페이지 크기(포인트)를 미리 측정한다.
    """
    resp = requests.get(jsonl_url, timeout=AISTUDIO_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    lines = [line.strip() for line in resp.text.strip().split("\n") if line.strip()]
    if not lines:
        raise RuntimeError("AI Studio API JSONL result is empty")

    image_dir = IMAGE_BASE_DIR / request_id
    image_dir.mkdir(parents=True, exist_ok=True)

    # PDF 원본 페이지 크기 측정 (좌표계/DPI 추정용)
    page_sizes: dict[int, tuple[float, float]] = {}
    if pdf_source_path and pdf_source_path.exists():
        try:
            doc = fitz.open(str(pdf_source_path))
            for i, page in enumerate(doc):
                page_sizes[i] = (page.rect.width, page.rect.height)
            doc.close()
            logger.info(
                f"[aistudio] PDF 원본 페이지 크기 측정 완료: {pdf_source_path.name} "
                f"({len(page_sizes)}페이지)"
            )
        except Exception as e:
            logger.warning(f"[aistudio] PDF 원본 페이지 크기 측정 실패: {e}")

    all_page_markdowns: list[str] = []
    page_markdowns: list[str] = []
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
            # PaddleOCR-VL은 이미지 좌표계(top-left, y↓)를 사용하지만, 원본 PDF 직접 제출 시
            # PDF user-space(bottom-left, y↑)를 반환할 수도 있으므로 좌표계를 동적으로 감지한다.
            pruned = lpr.get("prunedResult", {}) or {}
            page_idx = page_num - 1
            page_width_pt, page_height_pt = page_sizes.get(page_idx, (None, None))
            layout_pages.append(
                _extract_layout_from_result(pruned, page_height_pt=page_height_pt)
            )
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

            # per-page markdown (배치 응답용 — 헤더 없이 순수 페이지 텍스트)
            page_markdowns.append(md_text)
            page_header = f"<!-- Page {page_num} -->\n" if page_num > 1 else ""
            all_page_markdowns.append(f"{page_header}{md_text}")

    markdown = "\n\n".join(all_page_markdowns)
    logger.info(f"[aistudio] 변환 완료: {page_num}페이지, {len(downloaded_images)} 이미지")

    return {
        "markdown": markdown,
        "page_markdowns": page_markdowns,
        "images": downloaded_images,
        "page_count": page_num,
        "layout": layout_pages,
        "page_angles": page_angles,
    }


def _do_aistudio_convert(
    task_id: str,
    input_path: Path,
    filename: str,
    capture_layout: bool = False,
) -> None:
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
            layout=ocr_result.get("layout", []) if capture_layout else [],
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
async def api_convert(
    file: UploadFile = File(...),
    capture_layout: bool = Form(False),
) -> AsyncConvertResponse:
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
            "capture_layout": capture_layout,
        }

    thread = threading.Thread(
        target=_do_aistudio_convert,
        args=(task_id, input_path, file.filename, capture_layout),
        daemon=True,
    )
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


# ─── AI Studio API 배치 엔드포인트 (여러 이미지 → 1 job) ───

# AI Studio 기본 페이지 제한 (maxNumInputImgs 서버 사이드 설정값)
BATCH_MAX_PAGES = int(os.environ.get("PADDLEOCR_BATCH_MAX_PAGES", "10"))


class BatchPageResult(BaseModel):
    """배치 결과 내 개별 페이지 데이터."""
    markdown: str
    layout: dict
    page_angle: int


class BatchConvertResponse(BaseModel):
    """배치 변환 응답 — 업로드 순서대로 per-page 결과 리스트 반환."""
    pages: list[BatchPageResult]
    page_count: int


class BatchTaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: BatchConvertResponse | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


def _images_to_pdf(image_paths: list[Path], output_path: Path) -> Path:
    """여러 PNG 이미지를 단일 multi-page PDF로 병합한다 (JPEG 압축으로 크기 최소화).

    [Flow: Step 1 (PIL로 각 이미지를 JPEG 메모리 스트림으로 변환) -> Step 2 (fitz로 빈 PDF 생성) -> Step 3 (각 JPEG을 페이지로 삽입) -> Step 4 (PDF 저장)]

    AI Studio API는 multi-page PDF를 한 job에서 페이지별로 처리한다 (multi-page TIFF와 달리
    모든 페이지가 처리됨 — 실제 테스트 검증 완료).
    각 이미지의 픽셀 크기를 그대로 PDF 페이지 크기로 사용하므로 bbox 좌표계가 호환된다.
    PNG를 JPEG으로 압축하여 삽입하면 PDF 크기를 1/3~1/5로 줄일 수 있다.

    Args:
        image_paths: 병합할 PNG 이미지 경로 리스트 (순서 = 페이지 순서)
        output_path: 출력 PDF 파일 경로

    Returns:
        output_path (저장된 PDF 경로)
    """
    if not image_paths:
        raise RuntimeError("No images to combine into PDF")

    from PIL import Image
    import io

    pdf = fitz.open()  # 빈 PDF
    for img_path in image_paths:
        # PIL로 이미지를 JPEG 메모리 스트림으로 변환 (크기 최소화)
        pil_img = Image.open(str(img_path))
        if pil_img.mode != "RGB":
            pil_img = pil_img.convert("RGB")
        jpeg_buf = io.BytesIO()
        pil_img.save(jpeg_buf, format="JPEG", quality=85)
        pil_img.close()
        jpeg_bytes = jpeg_buf.getvalue()

        # 원본 이미지 픽셀 크기를 PDF 페이지 크기로 사용 (bbox 좌표계 호환)
        img_doc = fitz.open(str(img_path))
        page = pdf.new_page(width=img_doc[0].rect.width, height=img_doc[0].rect.height)
        img_doc.close()
        page.insert_image(page.rect, stream=jpeg_bytes)

    pdf.save(str(output_path), deflate=True, garbage=4)
    pdf.close()
    pdf_size = output_path.stat().st_size / 1024 / 1024
    logger.info(f"[paddleocr-batch] {len(image_paths)}장 → PDF 병합 완료: {output_path.name} ({pdf_size:.1f}MB)")
    return output_path


def _do_aistudio_batch_convert(task_id: str, image_paths: list[Path], filenames: list[str]) -> None:
    """여러 페이지 이미지를 하나의 AI Studio job으로 배치 변환한다.

    [Flow: Step 1 (각 이미지 deskew 보정) -> Step 2 (multi-page TIFF 병합) -> Step 3 (AI Studio job 제출) -> Step 4 (폴링) -> Step 5 (JSONL 다운로드/파싱) -> Step 6 (per-page 결과 저장)]
    """
    try:
        request_id = uuid.uuid4().hex
        work_dir = Path(tempfile.mkdtemp())

        # Step 1: 각 이미지 deskew 보정
        try:
            from backend.core.image_deskew import deskew_image
        except ImportError:
            from core.image_deskew import deskew_image
        deskewed_paths: list[Path] = []
        for img_path in image_paths:
            corrected, _angle = deskew_image(img_path, work_dir)
            deskewed_paths.append(corrected)

        # Step 2: multi-page PDF 병합 (TIFF는 1페이지만 처리되므로 PDF 사용)
        pdf_path = work_dir / "batch.pdf"
        _images_to_pdf(deskewed_paths, pdf_path)

        # Step 3-5: AI Studio job 제출 → 폴링 → 다운로드/파싱
        job_id = _aistudio_submit_job(pdf_path)
        jsonl_url = _aistudio_poll_job(job_id)
        ocr_result = _aistudio_download_and_parse(jsonl_url, request_id)

        # Step 6: per-page 결과 구성
        page_markdowns = ocr_result.get("page_markdowns", [])
        layout_pages = ocr_result.get("layout", [])
        page_angles = ocr_result.get("page_angles", [])
        page_count = ocr_result.get("page_count", len(page_markdowns))

        pages: list[BatchPageResult] = []
        for idx in range(page_count):
            pages.append(BatchPageResult(
                markdown=page_markdowns[idx] if idx < len(page_markdowns) else "",
                layout=layout_pages[idx] if idx < len(layout_pages) else {},
                page_angle=page_angles[idx] if idx < len(page_angles) else -1,
            ))

        batch_result = BatchConvertResponse(pages=pages, page_count=page_count)

        with _tasks_lock:
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["result"] = batch_result
            _tasks[task_id]["finished_at"] = time.time()

        logger.info(f"[aistudio-batch] {len(image_paths)}장 배치 변환 완료 ({page_count}페이지)")

    except Exception as e:
        logger.exception(f"[aistudio-batch] 배치 변환 실패: {e}")
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["finished_at"] = time.time()


def _do_aistudio_pdf_convert(task_id: str, pdf_path: Path, filename: str) -> None:
    """원본 PDF를 그대로 AI Studio에 제출하여 변환한다 (렌더링/deskew/병합 생략).

    [Flow: Step 1 (AI Studio job 제출) -> Step 2 (폴링) -> Step 3 (JSONL 다운로드/파싱) -> Step 4 (per-page 결과 저장)]

    원본 PDF가 10페이지 이하인 경우, 이미지 렌더링/deskew/PDF 재병합 없이
    원본 PDF를 AI Studio에 직접 제출하여 불필요한 왕복을 제거한다.
    """
    try:
        request_id = uuid.uuid4().hex

        # Step 1-3: AI Studio job 제출 → 폴링 → 다운로드/파싱
        job_id = _aistudio_submit_job(pdf_path)
        jsonl_url = _aistudio_poll_job(job_id)
        ocr_result = _aistudio_download_and_parse(
            jsonl_url, request_id, pdf_source_path=pdf_path
        )

        # Step 4: per-page 결과 구성
        page_markdowns = ocr_result.get("page_markdowns", [])
        layout_pages = ocr_result.get("layout", [])
        page_angles = ocr_result.get("page_angles", [])
        page_count = ocr_result.get("page_count", len(page_markdowns))

        pages: list[BatchPageResult] = []
        for idx in range(page_count):
            pages.append(BatchPageResult(
                markdown=page_markdowns[idx] if idx < len(page_markdowns) else "",
                layout=layout_pages[idx] if idx < len(layout_pages) else {},
                page_angle=page_angles[idx] if idx < len(page_angles) else -1,
            ))

        batch_result = BatchConvertResponse(pages=pages, page_count=page_count)

        with _tasks_lock:
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["result"] = batch_result
            _tasks[task_id]["finished_at"] = time.time()

        logger.info(f"[aistudio-pdf] {filename} 직접 변환 완료 ({page_count}페이지)")

    except Exception as e:
        logger.exception(f"[aistudio-pdf] {filename} 직접 변환 실패: {e}")
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["finished_at"] = time.time()


@app.post("/api/convert/pdf", response_model=AsyncConvertResponse)
async def api_convert_pdf(file: UploadFile = File(...)) -> AsyncConvertResponse:
    """원본 PDF를 렌더링 없이 AI Studio에 직접 제출한다 (10페이지 이하 전용).

    클라이언트가 원본 PDF를 그대로 업로드하면, 서비스가 이를 AI Studio API에
    단일 job으로 제출한다. 이미지 렌더링/deskew/PDF 재병합을 생략하여
    10페이지 이하 PDF의 처리 시간을 대폭 단축한다.
    AI Studio 기본 제한(10페이지)을 초과하면 400 에러를 반환한다.
    """
    if not AISTUDIO_API_TOKEN:
        raise HTTPException(status_code=503, detail="PADDLEOCR_API_TOKEN is not configured")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    if ext != ".pdf":
        raise HTTPException(status_code=400, detail=f"PDF endpoint supports PDF only: {file.filename}")

    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir)
    pdf_path = tmp_path / (file.filename or "input.pdf")
    pdf_path.write_bytes(await file.read())

    # 페이지 수 검증 (AI Studio 기본 제한 10페이지)
    # 클라이언트(paddleocr_client)에서 이미 PDF 최적화를 수행하므로 서비스 측에서는 생략한다.
    # 외부 API 클라이언트가 직접 호출하는 경우에 대비해 파일명에 _optimized가 없고 1MB 초과 시만 수행.
    try:
        doc = fitz.open(str(pdf_path))
        page_count = len(doc)
        needs_optimize = (
            "_optimized" not in pdf_path.stem
            and page_count > 0
            and pdf_path.stat().st_size > 1024 * 1024
        )
        if needs_optimize:
            doc.save(str(pdf_path) + ".opt", deflate=True, garbage=4)
            doc.close()
            import shutil
            shutil.move(str(pdf_path) + ".opt", str(pdf_path))
        else:
            doc.close()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read PDF: {e}")

    if page_count > BATCH_MAX_PAGES:
        raise HTTPException(
            status_code=400,
            detail=f"PDF exceeds AI Studio page limit: {page_count} > {BATCH_MAX_PAGES}. Use /api/convert/batch with rendered images.",
        )

    logger.info(f"[aistudio-pdf] {file.filename} 직접 변환 시작 ({page_count}페이지, {pdf_path.stat().st_size/1024/1024:.1f}MB)")

    task_id = uuid.uuid4().hex
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "processing",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "tmpdir": tmpdir,
        }

    thread = threading.Thread(
        target=_do_aistudio_pdf_convert,
        args=(task_id, pdf_path, file.filename),
        daemon=True,
    )
    thread.start()

    return AsyncConvertResponse(task_id=task_id, status="processing")


@app.get("/api/convert/pdf/status/{task_id}", response_model=BatchTaskStatusResponse)
async def api_convert_pdf_status(task_id: str) -> BatchTaskStatusResponse:
    """PDF 직접 변환 작업의 상태를 조회한다 (/api/convert/batch/status와 동일 스펙)."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return BatchTaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        result=task.get("result"),
        error=task.get("error"),
        started_at=task.get("started_at"),
        finished_at=task.get("finished_at"),
    )


@app.post("/api/convert/batch", response_model=AsyncConvertResponse)
async def api_convert_batch(files: list[UploadFile] = File(...)) -> AsyncConvertResponse:
    if not AISTUDIO_API_TOKEN:
        raise HTTPException(status_code=503, detail="PADDLEOCR_API_TOKEN is not configured")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    if len(files) > BATCH_MAX_PAGES:
        raise HTTPException(
            status_code=400,
            detail=f"Batch exceeds AI Studio page limit: {len(files)} > {BATCH_MAX_PAGES}. Split into smaller batches.",
        )

    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir)
    image_paths: list[Path] = []
    filenames: list[str] = []

    for f in files:
        if not f.filename:
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}:
            raise HTTPException(
                status_code=400,
                detail=f"Batch endpoint supports images only: {f.filename}",
            )
        saved_path = tmp_path / f.filename
        saved_path.write_bytes(await f.read())
        image_paths.append(saved_path)
        filenames.append(f.filename)

    if not image_paths:
        raise HTTPException(status_code=400, detail="No valid image files uploaded")

    task_id = uuid.uuid4().hex
    with _tasks_lock:
        _tasks[task_id] = {
            "status": "processing",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "tmpdir": tmpdir,
        }

    thread = threading.Thread(
        target=_do_aistudio_batch_convert,
        args=(task_id, image_paths, filenames),
        daemon=True,
    )
    thread.start()

    return AsyncConvertResponse(task_id=task_id, status="processing")


@app.get("/api/convert/batch/status/{task_id}", response_model=BatchTaskStatusResponse)
async def api_convert_batch_status(task_id: str) -> BatchTaskStatusResponse:
    """배치 변환 작업의 상태를 조회한다 (/api/convert/status/{task_id}와 동일 스펙, 결과 타입만 상이)."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    return BatchTaskStatusResponse(
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
