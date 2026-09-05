#!/usr/bin/env python3
# [Flow: Step 1 (파일 수신) -> Step 2 (PDF→페이지 이미지 변환) -> Step 3 (선택된 OCR 백엔드 호출) -> Step 4 (마크다운 + 이미지 추출) -> Step 5 (docling_client 호환 응답)]
# PROOF 통합 OCR FastAPI 서비스 — 모든 OCR 요청의 단일 진입점.
#
# 백엔드 3종을 PADDLEOCR_BACKEND 환경변수로 선택하며, 클라이언트가 보는 엔드포인트 계약
# (/api/convert, /api/convert/batch, /api/convert/pdf)은 백엔드와 무관하게 동일하다.
# 따라서 백엔드 교체는 환경변수 한 줄이며, core/paddleocr_client.py 이하 상위 파이프라인은
# 수정이 필요 없다.
#   local_v5 : PP-OCRv5 + PP-StructureV3 로컬 CPU 추론 (a1, GPU 불필요) — 기본값
#   aistudio : PaddleOCR AI Studio 유료 API 프록시 (외부 의존)
#   local_vl : PaddleOCR-VL 1.6 + vLLM 로컬 추론 (GPU 필요 — b2 복구 후)
import base64
import functools
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

try:  # 패키지 컨텍스트 (backend.paddleocr_service.ocr_v5)
    from . import ocr_v5
except ImportError:  # 컨테이너 컨텍스트 (/app/main.py + /app/ocr_v5.py)
    import ocr_v5

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="PROOF PaddleOCR-VL Service")

VLLM_SERVER_URL = os.environ.get("VLLM_SERVER_URL", "http://vllm:8080/v1")
VLLM_MODEL_NAME = os.environ.get("VLLM_MODEL_NAME", "PaddleOCR-VL-0.9B")
PIPELINE_VERSION = os.environ.get("PADDLEOCR_PIPELINE_VERSION", "v1.6")

# ─── OCR 백엔드 선택 ───
# 상위 파이프라인은 항상 /api/convert* 계약만 호출하고, 실제 엔진은 여기서 결정된다.
BACKEND_LOCAL_V5 = "local_v5"
BACKEND_AISTUDIO = "aistudio"
BACKEND_LOCAL_VL = "local_vl"
VALID_BACKENDS = (BACKEND_LOCAL_V5, BACKEND_AISTUDIO, BACKEND_LOCAL_VL)

OCR_BACKEND = os.environ.get("PADDLEOCR_BACKEND", BACKEND_LOCAL_V5).strip().lower()
if OCR_BACKEND not in VALID_BACKENDS:
    logger.warning(f"[paddleocr] 알 수 없는 PADDLEOCR_BACKEND={OCR_BACKEND!r} — {BACKEND_LOCAL_V5}로 대체")
    OCR_BACKEND = BACKEND_LOCAL_V5

# 로컬 추론이 실패했을 때 AI Studio API로 재시도할지 여부 (토큰이 설정된 경우에만 동작).
# 로컬 엔진 배포 초기에 안전망으로 켜두고, 안정화 후 false로 내리는 것을 권장한다.
LOCAL_FALLBACK_TO_AISTUDIO = (
    os.environ.get("PADDLEOCR_LOCAL_FALLBACK_TO_AISTUDIO", "true").lower() == "true"
)

DATA_DIR = Path("/data")
IMAGE_BASE_DIR = DATA_DIR / "paddleocr_images"

# PaddleOCR 자동 파라미터 추천 설정 (Vision LLM 샘플 기반)
AUTO_PARAMETER_ENABLED = os.environ.get("PADDLEOCR_AUTO_PARAMETER_ENABLED", "true").lower() == "true"
SAMPLE_DPI = int(os.environ.get("PADDLEOCR_SAMPLE_DPI", "150"))
SAMPLE_MAX_TOKENS = int(os.environ.get("PADDLEOCR_SAMPLE_MAX_TOKENS", "2000"))
# 추천에 사용할 Vision LLM. local_v5 백엔드에는 vLLM 컨테이너가 없으므로 VLLM_SERVER_URL을
# 그대로 쓰면 문서마다 없는 호스트로 붙었다가 타임아웃한다 — 앱의 실제 LLM 엔드포인트를 지정한다.
RECOMMENDER_ENDPOINT = (
    os.environ.get("PADDLEOCR_RECOMMENDER_ENDPOINT", "")
    or os.environ.get("DEFAULT_LLM_ENDPOINT", "")
    or VLLM_SERVER_URL
)
RECOMMENDER_MODEL = (
    os.environ.get("PADDLEOCR_RECOMMENDER_MODEL", "")
    or os.environ.get("DEFAULT_LLM_MODEL", "")
    or VLLM_MODEL_NAME
)
RECOMMENDER_API_KEY = os.environ.get("PADDLEOCR_RECOMMENDER_API_KEY", "")

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
            endpoint=RECOMMENDER_ENDPOINT,
            model=RECOMMENDER_MODEL,
            api_key=RECOMMENDER_API_KEY,
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
    # [Flow: Step 1 (PaddleOCR pipeline 가져오기) -> Step 2 (파라미터 병합)
    #       -> Step 3 (각 이미지 추론) -> Step 4 (결과 병합, 필요 시 layout bbox 수집)]
    pipeline = get_pipeline()
    all_markdown_parts: list[str] = []
    layout_pages: list[dict] = []
    page_angles: list[int] = []
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
                page_angles.append(ocr_v5._angle_code(ocr_v5._raw_json(res)))
        except Exception as e:
            logger.error(f"[paddleocr] 페이지 {idx + 1} 추론 실패: {e}")
            all_markdown_parts.append(f"<!-- Page {idx + 1} (OCR 실패) -->\n")
            if capture_layout:
                layout_pages.append({})
            page_angles.append(-1)

    markdown = "\n\n".join(all_markdown_parts)
    return {
        "markdown": markdown,
        "page_count": total_pages,
        "layout": layout_pages,
        "page_angles": page_angles,
    }


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


def _normalize_bbox(
    bbox: list[float] | tuple[float, ...],
    page_width_px: float,
    page_height_px: float,
    flip_y: bool = True,
) -> list[float]:
    """bbox를 0~1 top-left normalized(y=0이 상단) 좌표로 변환한다.

    [Flow: Step 1 (x좌표를 페이지 너비로 나눔) -> Step 2 (y좌표를 페이지 높이로 나눔)
          -> Step 3 (원본이 bottom-left면 y를 뒤집음) -> Step 4 ([x0, y0, x1, y1] 반환)]

    ⚠️ 이 함수는 좌표 규약 중립이 아니다. 입력 원점이 무엇인지 호출부가 알려줘야 한다.

    Args:
        flip_y: 입력 bbox가 **bottom-left origin(y↑)** 이면 True (AI Studio 가 PDF 를
            직접 받았을 때의 규약). 입력이 이미 **top-left origin(y↓)** 이면 False —
            PP-StructureV3(local_v5) 는 이미지 픽셀 좌표를 top-left 로 반환하므로 여기에 해당한다.

    출력은 항상 top-left normalized 이며, 소비자
    (`_normalized_bbox_to_pdf_user`, `add_text_layer_from_ocr`, `build_embedpdf_annotations`)
    가 PDF user-space 로 갈 때 한 번 더 뒤집는다. 따라서 top-left 입력에 flip_y=True 를
    쓰면 뒤집기가 두 번이 되어 상쇄되고, 하이라이트가 페이지 중앙 기준으로 상하 반전된다.
    """
    if not bbox or len(bbox) < 4:
        return list(bbox) if bbox else []
    x0, y0, x1, y1 = (float(v) for v in bbox[:4])
    if flip_y:
        ny0, ny1 = 1.0 - (y1 / page_height_px), 1.0 - (y0 / page_height_px)
    else:
        ny0, ny1 = y0 / page_height_px, y1 / page_height_px
    return [x0 / page_width_px, ny0, x1 / page_width_px, ny1]


def _normalize_points(
    points: list[list[float]] | list[tuple[float, ...]],
    page_width_px: float,
    page_height_px: float,
    flip_y: bool = True,
) -> list[list[float]]:
    """다각형 점들을 0~1 top-left normalized 좌표로 변환한다.

    [Flow: Step 1 (각 점의 x를 페이지 너비로 나눔) -> Step 2 (y를 페이지 높이로 나눔)
          -> Step 3 (원본이 bottom-left면 y를 뒤집음) -> Step 4 (변환된 점 목록 반환)]

    `flip_y` 의미는 `_normalize_bbox` 와 동일하다.
    """
    if not points:
        return []
    converted: list[list[float]] = []
    for pt in points:
        if not pt or len(pt) < 2:
            converted.append(list(pt) if pt else [])
            continue
        x, y = float(pt[0]), float(pt[1])
        ny = 1.0 - (y / page_height_px) if flip_y else y / page_height_px
        converted.append([x / page_width_px, ny])
    return converted


def _extract_layout_from_result(res: Any, flip_y: bool = True) -> dict:
    """결과 객체에서 bbox를 0~1 top-left normalized 좌표로 변환한 레이아웃을 반환한다.

    [Flow: Step 1 (res.json 추출) -> Step 2 (페이지 픽셀 크기 확인)
          -> Step 3 (parsing_res_list / layout_det_res / overall_ocr_res의 bbox를 normalized 좌표로 변환)
          -> Step 4 (normalized 좌표계 기준 layout dict 반환)]

    출력은 항상 0~1 top-left normalized(y=0 상단, y=1 하단)이다. 소비자
    (`_collect_page_elements_*`, `add_text_layer_from_ocr`)가 원본 PDF 페이지 크기만 알면
    정확한 PDF user-space 좌표를 계산할 수 있다.

    Args:
        flip_y: 입력 bbox 의 y 원점이 하단(y↑)이면 True. AI Studio 에 **PDF 를 직접 제출**하면
            bbox 가 PDF user-space(bottom-left)로 오므로 True 가 맞다.
            **PP-StructureV3(local_v5)** 는 이미지 픽셀 좌표를 top-left 로 반환하므로 False 여야 한다.
            잘못 주면 소비자 쪽 뒤집기와 상쇄되어 하이라이트가 상하 반전된다.
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

    page_width_px = layout.get("width")
    page_height_px = layout.get("height")
    if (
        not isinstance(page_width_px, (int, float))
        or page_width_px <= 0
        or not isinstance(page_height_px, (int, float))
        or page_height_px <= 0
    ):
        logger.warning("[paddleocr] layout 크기 정보가 없어 bbox 정규화를 건너뜁니다.")
        return layout

    page_width_px = float(page_width_px)
    page_height_px = float(page_height_px)

    layout["_coordinate_system"] = "normalized"
    layout["_page_width_px"] = page_width_px
    layout["_page_height_px"] = page_height_px

    # parsing_res_list 블록 bbox 및 polygon_points 변환
    for block in layout.get("parsing_res_list", []):
        if not isinstance(block, dict):
            continue
        bbox = block.get("block_bbox")
        if bbox:
            block["block_bbox"] = _normalize_bbox(bbox, page_width_px, page_height_px, flip_y)
        points = block.get("block_polygon_points")
        if points:
            block["block_polygon_points"] = _normalize_points(points, page_width_px, page_height_px, flip_y)

    # layout_det_res 내부 boxes 변환
    layout_det = layout.get("layout_det_res") or {}
    if isinstance(layout_det, dict):
        for box in layout_det.get("boxes", []):
            if not isinstance(box, dict):
                continue
            coord = box.get("coordinate")
            if coord:
                box["coordinate"] = _normalize_bbox(coord, page_width_px, page_height_px, flip_y)
            points = box.get("polygon_points")
            if points:
                box["polygon_points"] = _normalize_points(points, page_width_px, page_height_px, flip_y)

    # overall_ocr_res.rec_boxes 변환
    ocr_res = layout.get("overall_ocr_res") or {}
    if isinstance(ocr_res, dict):
        rec_boxes = ocr_res.get("rec_boxes")
        if isinstance(rec_boxes, list):
            ocr_res["rec_boxes"] = [
                _normalize_bbox(b, page_width_px, page_height_px, flip_y)
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
    """서비스 상태 및 현재 선택된 OCR 백엔드를 반환한다."""
    return {
        "status": "ok",
        "backend": OCR_BACKEND,
        "rec_model": ocr_v5.V5_REC_MODEL if OCR_BACKEND == BACKEND_LOCAL_V5 else "",
    }


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
        target=_do_local_v5_convert if _is_local_v5() else _do_convert,
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

        if _is_local_v5():
            try:
                return _v5_convert_sync(input_path, file.filename, capture_layout)
            except Exception as e:
                logger.exception(f"[ocr-v5-sync] {file.filename} 변환 실패: {e}")
                raise HTTPException(status_code=500, detail=f"PaddleOCR v5 inference failed: {e}")

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
) -> dict[str, Any]:
    """JSONL 결과를 다운로드하고 페이지별 markdown + 이미지로 변환한다.

    [Flow: Step 1 (JSONL 다운로드) -> Step 2 (라인별 파싱)
          -> Step 3 (layoutParsingResults 순회) -> Step 4 (markdown.text 추출)
          -> Step 5 (bbox를 top-left normalized로 변환)
          -> Step 6 (images 다운로드 + src 치환) -> Step 7 (페이지별 마크다운 병합)]
    """
    resp = requests.get(jsonl_url, timeout=AISTUDIO_DOWNLOAD_TIMEOUT)
    resp.raise_for_status()

    lines = [line.strip() for line in resp.text.strip().split("\n") if line.strip()]
    if not lines:
        raise RuntimeError("AI Studio API JSONL result is empty")

    image_dir = IMAGE_BASE_DIR / request_id
    image_dir.mkdir(parents=True, exist_ok=True)

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
            pruned = lpr.get("prunedResult", {}) or {}
            layout_pages.append(_extract_layout_from_result(pruned))
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


# ─── 로컬 PP-OCRv5 (PP-StructureV3) 백엔드 ───
#
# AI Studio 경로와 동일한 per-page 결과(markdown/layout/page_angle)를 만들어내는 것이 목표다.
# 좌표 규약을 맞추기 위해 PDF도 항상 페이지 이미지로 렌더링한 뒤 추론한다 (AI Studio PDF 직접
# 제출 경로는 bbox가 PDF user-space로 내려와 이미지 경로와 원점이 달랐다 — 로컬 백엔드는
# 이미지 규약 하나만 쓰므로 그 불일치가 사라진다).

# 로컬 백엔드는 외부 API의 페이지 제한(10페이지/job)을 받지 않는다.
LOCAL_BATCH_MAX_PAGES = int(os.environ.get("PADDLEOCR_LOCAL_BATCH_MAX_PAGES", "200"))


def _is_local_v5() -> bool:
    """현재 선택된 백엔드가 로컬 PP-OCRv5인지 여부."""
    return OCR_BACKEND == BACKEND_LOCAL_V5


def _effective_batch_max_pages() -> int:
    """현재 백엔드의 배치 페이지 상한을 반환한다."""
    return LOCAL_BATCH_MAX_PAGES if _is_local_v5() else BATCH_MAX_PAGES


def _v5_deskew_all(image_paths: list[Path], work_dir: Path) -> list[Path]:
    """각 페이지 이미지에 deskew(미세 기울기) 보정을 적용한 경로 목록을 반환한다.

    AI Studio 배치 경로(_do_aistudio_batch_convert)와 동일한 전처리다. 보정된 이미지 기준으로
    bbox가 나오므로, 클라이언트가 주석 PDF의 베이스 이미지를 같은 방식으로 보정해 재현할 수 있다.
    """
    try:
        from backend.core.image_deskew import deskew_image
    except ImportError:
        from core.image_deskew import deskew_image

    corrected: list[Path] = []
    for img_path in image_paths:
        try:
            fixed, _angle = deskew_image(img_path, work_dir)
            corrected.append(fixed)
        except Exception as e:
            logger.warning(f"[ocr-v5] {img_path.name} deskew 실패, 원본 사용: {e}")
            corrected.append(img_path)
    return corrected


def _v5_predict(
    image_paths: list[Path],
    params: dict[str, Any] | None,
    capture_layout: bool,
) -> list[dict[str, Any]]:
    """페이지 이미지 목록을 로컬 PP-OCRv5로 추론해 per-page 결과 리스트를 반환한다."""
    # PP-StructureV3 는 bbox 를 입력 이미지 픽셀 좌표(top-left origin)로 반환한다.
    # AI Studio 의 PDF 직접 제출(bottom-left)과 규약이 다르므로 flip_y=False 여야 한다.
    # True 로 두면 소비자(_normalized_bbox_to_pdf_user)의 뒤집기와 상쇄되어
    # 스캔 PDF 하이라이트가 페이지 중앙 기준으로 상하 반전된다.
    extractor = (
        functools.partial(_extract_layout_from_result, flip_y=False) if capture_layout else None
    )
    return ocr_v5.predict_pages(image_paths, params=params, layout_extractor=extractor)


def _v5_merge_markdown(pages: list[dict[str, Any]]) -> str:
    """per-page 마크다운을 `<!-- Page N -->` 마커로 병합한다 (AI Studio 경로와 동일 규칙)."""
    parts: list[str] = []
    for idx, page in enumerate(pages):
        md = page.get("markdown", "") or ""
        header = f"<!-- Page {idx + 1} -->\n" if idx > 0 else ""
        parts.append(f"{header}{md}")
    return "\n\n".join(parts)


def _v5_page_images(
    input_path: Path, filename: str, work_dir: Path
) -> tuple[list[Path], list[str], str, Path | None]:
    """입력 파일을 페이지 이미지 목록으로 변환한다.

    [Flow: Step 1 (파일 타입 판정) -> Step 2 (오피스 문서는 LibreOffice로 PDF 변환)
          -> Step 3 (PDF는 300DPI 페이지 이미지로 렌더링) -> Step 4 (이미지는 그대로 사용)]

    Returns:
        (페이지 이미지 경로 목록, PDF 내장 이미지 상대경로 목록, 정규화된 file_type,
         샘플 추출에 쓸 PDF 경로 — 이미지 입력이면 None)

        오피스 문서는 변환된 PDF 경로를 돌려준다. 원본 .docx를 파라미터 추천기에 넘기면
        PyMuPDF가 열지 못해 추천이 매번 조용히 실패한다.
    """
    file_type = _detect_file_type(filename)
    request_id = uuid.uuid4().hex

    if file_type == "office":
        pdf_path = _convert_office_to_pdf(input_path, work_dir)
        file_type = "pdf"
    elif file_type == "pdf":
        pdf_path = input_path
    elif file_type == "image":
        return [input_path], [], "image", None
    else:
        raise RuntimeError(f"Unsupported file type: {filename}")

    image_paths = _pdf_to_images(pdf_path)
    if not image_paths:
        raise RuntimeError("Failed to extract page images from PDF")
    return image_paths, _extract_embedded_images(pdf_path, request_id), file_type, pdf_path


def _v5_convert_sync(input_path: Path, filename: str, capture_layout: bool = False) -> "ConvertResponse":
    """단일 파일(이미지/PDF/오피스)을 로컬 PP-OCRv5로 변환해 ConvertResponse를 반환한다.

    [Flow: Step 1 (페이지 이미지 확보) -> Step 2 (자동 파라미터 추천) -> Step 3 (페이지별 추론)
          -> Step 4 (마크다운 병합 + layout/page_angles 수집)]
    """
    work_dir = input_path.parent
    image_paths, embedded_images, file_type, pdf_path = _v5_page_images(input_path, filename, work_dir)
    params = _get_paddleocr_params(pdf_path, work_dir)
    pages = _v5_predict(image_paths, params, capture_layout)

    return ConvertResponse(
        markdown=_v5_merge_markdown(pages),
        images=embedded_images,
        page_count=len(pages),
        file_type=file_type,
        layout=[p.get("layout", {}) for p in pages] if capture_layout else [],
        page_angles=[p.get("page_angle", -1) for p in pages],
    )


def _v5_batch_result(pages: list[dict[str, Any]]) -> "BatchConvertResponse":
    """per-page 결과를 BatchConvertResponse로 변환한다."""
    return BatchConvertResponse(
        pages=[
            BatchPageResult(
                markdown=page.get("markdown", "") or "",
                layout=page.get("layout", {}) or {},
                page_angle=page.get("page_angle", -1),
            )
            for page in pages
        ],
        page_count=len(pages),
    )


def _task_done(task_id: str, result: Any) -> None:
    """task를 완료 상태로 전이시킨다."""
    with _tasks_lock:
        _tasks[task_id]["status"] = "done"
        _tasks[task_id]["result"] = result
        _tasks[task_id]["finished_at"] = time.time()


def _task_error(task_id: str, message: str) -> None:
    """task를 실패 상태로 전이시킨다."""
    with _tasks_lock:
        _tasks[task_id]["status"] = "error"
        _tasks[task_id]["error"] = message
        _tasks[task_id]["finished_at"] = time.time()


def _aistudio_fallback_available() -> bool:
    """로컬 추론 실패 시 AI Studio API로 폴백할 수 있는지 여부."""
    return LOCAL_FALLBACK_TO_AISTUDIO and bool(AISTUDIO_API_TOKEN)


def _do_local_v5_convert(
    task_id: str,
    input_path: Path,
    filename: str,
    capture_layout: bool = False,
) -> None:
    """단일 파일 변환 (백그라운드 스레드). 실패 시 설정에 따라 AI Studio로 폴백한다."""
    try:
        result = _v5_convert_sync(input_path, filename, capture_layout)
        _task_done(task_id, result)
        logger.info(f"[ocr-v5] {filename} 변환 완료 ({result.page_count}페이지)")
        return
    except Exception as e:
        logger.exception(f"[ocr-v5] {filename} 변환 실패: {e}")
        if not _aistudio_fallback_available():
            _task_error(task_id, str(e))
            return
        logger.warning(f"[ocr-v5] {filename} AI Studio 폴백 시도")
    _do_aistudio_convert(task_id, input_path, filename, capture_layout)


def _do_local_v5_batch_convert(task_id: str, image_paths: list[Path], filenames: list[str]) -> None:
    """여러 페이지 이미지 배치 변환 (백그라운드 스레드).

    [Flow: Step 1 (deskew 보정) -> Step 2 (페이지별 병렬 추론) -> Step 3 (per-page 결과 저장)]
    """
    try:
        work_dir = Path(tempfile.mkdtemp())
        deskewed = _v5_deskew_all(image_paths, work_dir)
        pages = _v5_predict(deskewed, None, capture_layout=True)
        _task_done(task_id, _v5_batch_result(pages))
        logger.info(f"[ocr-v5-batch] {len(image_paths)}장 배치 변환 완료")
        return
    except Exception as e:
        logger.exception(f"[ocr-v5-batch] 배치 변환 실패: {e}")
        if not _aistudio_fallback_available():
            _task_error(task_id, str(e))
            return
        logger.warning("[ocr-v5-batch] AI Studio 폴백 시도")
    _do_aistudio_batch_convert(task_id, image_paths, filenames)


def _do_local_v5_pdf_convert(task_id: str, pdf_path: Path, filename: str) -> None:
    """PDF를 페이지 이미지로 렌더링한 뒤 per-page 결과를 반환한다 (백그라운드 스레드).

    AI Studio PDF 직접 제출과 달리 렌더링을 거치므로 bbox 좌표 규약이 이미지 경로와 동일해진다.
    """
    try:
        image_paths = _pdf_to_images(pdf_path)
        if not image_paths:
            raise RuntimeError("Failed to extract page images from PDF")
        params = _get_paddleocr_params(pdf_path, pdf_path.parent)
        pages = _v5_predict(image_paths, params, capture_layout=True)
        _task_done(task_id, _v5_batch_result(pages))
        logger.info(f"[ocr-v5-pdf] {filename} 변환 완료 ({len(pages)}페이지)")
        return
    except Exception as e:
        logger.exception(f"[ocr-v5-pdf] {filename} 변환 실패: {e}")
        if not _aistudio_fallback_available():
            _task_error(task_id, str(e))
            return
        logger.warning(f"[ocr-v5-pdf] {filename} AI Studio 폴백 시도")
    _do_aistudio_pdf_convert(task_id, pdf_path, filename)


@app.post("/api/convert", response_model=AsyncConvertResponse)
async def api_convert(
    file: UploadFile = File(...),
    capture_layout: bool = Form(False),
) -> AsyncConvertResponse:
    """이미지 한 장을 현재 선택된 OCR 백엔드로 변환한다 (상위 파이프라인의 기본 진입점).

    백엔드가 aistudio일 때만 외부 API 토큰이 필요하며, 토큰은 서비스 환경 변수에서만
    사용되어 클라이언트에 노출되지 않는다.
    """
    if not _is_local_v5() and not AISTUDIO_API_TOKEN:
        raise HTTPException(status_code=503, detail="PADDLEOCR_API_TOKEN is not configured")

    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = Path(file.filename).suffix.lower()
    image_extensions = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
    if ext not in image_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"/api/convert supports images only (png/jpg/bmp/tiff/webp): {file.filename}",
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
        target=_do_local_v5_convert if _is_local_v5() else _do_aistudio_convert,
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
        ocr_result = _aistudio_download_and_parse(jsonl_url, request_id)

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
    """원본 PDF를 업로드받아 per-page 결과를 반환한다.

    클라이언트는 렌더링 없이 원본 PDF를 그대로 올린다. 백엔드별 처리:
      - local_v5 : 서비스가 300DPI로 페이지 렌더링 후 페이지별 병렬 추론
                   (페이지 상한은 PADDLEOCR_LOCAL_BATCH_MAX_PAGES)
      - aistudio : PDF를 단일 job으로 직접 제출 (외부 API 기본 제한 10페이지)
    """
    if not _is_local_v5() and not AISTUDIO_API_TOKEN:
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

    max_pages = _effective_batch_max_pages()
    if page_count > max_pages:
        raise HTTPException(
            status_code=400,
            detail=f"PDF exceeds page limit for backend {OCR_BACKEND}: {page_count} > {max_pages}. Use /api/convert/batch with rendered images.",
        )

    logger.info(
        f"[{OCR_BACKEND}-pdf] {file.filename} 변환 시작 "
        f"({page_count}페이지, {pdf_path.stat().st_size/1024/1024:.1f}MB)"
    )

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
        target=_do_local_v5_pdf_convert if _is_local_v5() else _do_aistudio_pdf_convert,
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
    """여러 페이지 이미지를 한 요청으로 변환하고 업로드 순서대로 per-page 결과를 반환한다."""
    if not _is_local_v5() and not AISTUDIO_API_TOKEN:
        raise HTTPException(status_code=503, detail="PADDLEOCR_API_TOKEN is not configured")

    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    max_pages = _effective_batch_max_pages()
    if len(files) > max_pages:
        raise HTTPException(
            status_code=400,
            detail=f"Batch exceeds page limit for backend {OCR_BACKEND}: {len(files)} > {max_pages}. Split into smaller batches.",
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
        target=_do_local_v5_batch_convert if _is_local_v5() else _do_aistudio_batch_convert,
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
