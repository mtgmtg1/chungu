#!/usr/bin/env python3
# [Flow: Step 1 (총 페이지 수 기반 샘플 수 계산) -> Step 2 (전략적 페이지 인덱스 선택) -> Step 3 (PyMuPDF로 샘플 이미지 렌더) -> Step 4 (Vision LLM에 추천 요청) -> Step 5 (JSON 파싱 및 검증) -> Step 6 (fallback 프리셋 적용)]
# PaddleOCR-VL 파라미터 자동 추천 모듈
# 사용자가 기술 용어를 몰라도, 업로드된 문서의 몇 장 샘플을 보고 Vision LLM이 최적 파라미터를 결정하도록 지원한다.
import json
import logging
import math
import re
from pathlib import Path
from typing import Any

import fitz

from . import ocr_client
from .prompts import build_paddleocr_parameter_recommendation_prompt

logger = logging.getLogger(__name__)

# 샘플링 상수: 1% 비율, 최소 1장, 최대 3장
SAMPLE_RATIO = 0.01
SAMPLE_MIN = 1
SAMPLE_MAX = 3
SAMPLE_DPI = 150

# 허용 파라미터 및 범위
MERGE_MODES = {"large", "small", "union"}
VALID_PARAMS = {
    "layout_threshold",
    "layout_unclip_ratio",
    "layout_merge_bboxes_mode",
    "layout_nms",
    "use_doc_orientation_classify",
    "use_doc_unwarping",
    "use_layout_detection",
    "use_ocr_for_image_block",
    "format_block_content",
    "use_chart_recognition",
    "use_seal_recognition",
}

# 문서 유형별 프리셋 (fallback용)
_PRESETS: dict[str, dict[str, Any]] = {
    "receipt": {
        "layout_threshold": 0.35,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "invoice": {
        "layout_threshold": 0.4,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": True,
    },
    "form": {
        "layout_threshold": 0.45,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "union",
        "layout_nms": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_ocr_for_image_block": False,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "paper": {
        "layout_threshold": 0.5,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "table_heavy": {
        "layout_threshold": 0.4,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "union",
        "layout_nms": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "image_heavy": {
        "layout_threshold": 0.45,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "business_card": {
        "layout_threshold": 0.35,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "report": {
        "layout_threshold": 0.5,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
    "mixed": {
        "layout_threshold": 0.45,
        "layout_unclip_ratio": 1.0,
        "layout_merge_bboxes_mode": "large",
        "layout_nms": True,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_layout_detection": True,
        "use_ocr_for_image_block": True,
        "format_block_content": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
    },
}

_DEFAULT_PRESET = _PRESETS["report"]


def _calculate_sample_count(total_pages: int) -> int:
    """총 페이지 수를 기반으로 샘플링할 페이지 수를 반환한다.

    1% 비율을 적용하되 최소 1장, 최대 3장으로 제한한다.

    Args:
        total_pages: PDF의 전체 페이지 수

    Returns:
        샘플링할 페이지 수
    """
    return max(SAMPLE_MIN, min(SAMPLE_MAX, math.ceil(total_pages * SAMPLE_RATIO)))


def _select_page_indices(total_pages: int, count: int) -> list[int]:
    """문서 전체 구조를 대표하는 페이지 인덱스를 선택한다.

    인덱스는 0-based이며, 첫 페이지, 중간 페이지, 마지막 페이지 근처를 우선적으로 선택한다.

    Args:
        total_pages: 전체 페이지 수
        count: 샘플링할 페이지 수

    Returns:
        0-based 페이지 인덱스 목록
    """
    if count <= 0 or total_pages <= 0:
        return []
    if total_pages == 1:
        return [0]

    count = min(count, total_pages)

    if count == 1:
        return [total_pages // 2]
    if count == 2:
        return [0, total_pages - 1]
    return [0, total_pages // 2, total_pages - 1]


def render_sample_pages(pdf_path: Path, sample_dir: Path, dpi: int = SAMPLE_DPI) -> list[Path]:
    """PDF에서 전략적으로 선택한 샘플 페이지를 PNG로 렌더링한다.

    Args:
        pdf_path: 원본 PDF 파일 경로
        sample_dir: 샘플 이미지를 저장할 디렉터리
        dpi: 렌더링 해상도 (기본 150, 비용 절감용)

    Returns:
        렌더링된 샘플 이미지 경로 목록 (페이지 번호 순)
    """
    sample_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    count = _calculate_sample_count(total_pages)
    indices = _select_page_indices(total_pages, count)

    zoom = dpi / 72.0
    matrix = fitz.Matrix(zoom, zoom)
    paths: list[Path] = []

    for idx in indices:
        page = doc[idx]
        pix = page.get_pixmap(matrix=matrix)
        img_path = sample_dir / f"sample_page_{idx + 1:04d}.png"
        pix.save(str(img_path))
        paths.append(img_path)

    doc.close()
    logger.info(f"[paddleocr-recommender] {pdf_path.name} → 샘플 {len(paths)}장 추출 (pages={[p.stem for p in paths]})")
    return paths


def _extract_json_from_response(content: str) -> dict[str, Any] | None:
    """LLM 응답에서 마크다운 코드 블록을 제거하고 JSON 객체를 파싱한다.

    Args:
        content: LLM 응답 문자열

    Returns:
        파싱된 JSON 객체, 실패 시 None
    """
    if not content:
        return None
    cleaned = re.sub(r"```(?:json)?\n?|\n?```", "", content).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning(f"[paddleocr-recommender] JSON 파싱 실패: {cleaned[:200]}")
        return None


def _clamp(value: float, min_val: float, max_val: float) -> float:
    """값을 지정한 범위 내로 clamping한다.

    Args:
        value: 입력값
        min_val: 최소값
        max_val: 최대값

    Returns:
        clamping된 값
    """
    return max(min_val, min(max_val, value))


def validate_parameters(raw: dict[str, Any]) -> dict[str, Any]:
    """LLM이 추천한 파라미터를 검증하고 안전한 범위로 조정한다.

    Args:
        raw: LLM 추천 원본 파라미터 딕셔너리

    Returns:
        검증된 파라미터 딕셔너리
    """
    validated: dict[str, Any] = {}

    for key, value in raw.items():
        if key not in VALID_PARAMS:
            continue

        if key == "layout_threshold":
            try:
                validated[key] = _clamp(float(value), 0.1, 0.9)
            except (ValueError, TypeError):
                pass
        elif key == "layout_unclip_ratio":
            try:
                validated[key] = _clamp(float(value), 0.5, 2.0)
            except (ValueError, TypeError):
                pass
        elif key == "layout_merge_bboxes_mode":
            mode = str(value).lower()
            if mode in MERGE_MODES:
                validated[key] = mode
        elif key in {
            "layout_nms",
            "use_doc_orientation_classify",
            "use_doc_unwarping",
            "use_layout_detection",
            "use_ocr_for_image_block",
            "format_block_content",
            "use_chart_recognition",
            "use_seal_recognition",
        }:
            validated[key] = bool(value)

    return validated


def get_preset_parameters(doc_type: str) -> dict[str, Any]:
    """문서 유형에 맞는 기본 파라미터 프리셋을 반환한다.

    Args:
        doc_type: 문서 유형 문자열 (receipt, invoice, form, paper 등)

    Returns:
        해당 문서 유형의 기본 파라미터 딕셔너리
    """
    return _PRESETS.get(doc_type.lower(), _DEFAULT_PRESET).copy()


def recommend_parameters(
    sample_paths: list[Path],
    endpoint: str,
    model: str,
    api_key: str = "",
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """Vision LLM에 샘플 페이지를 보여주고 최적 PaddleOCR-VL 파라미터를 추천받는다.

    Args:
        sample_paths: 샘플 페이지 이미지 경로 목록
        endpoint: Vision LLM 엔드포인트 URL
        model: 사용할 모델명
        api_key: API 키 (없으면 빈 문자열)
        max_tokens: 최대 토큰 수

    Returns:
        추천 파라미터 딕셔너리. LLM 호출/파싱 실패 시 빈 딕셔너리 반환
    """
    if not sample_paths:
        return {}

    prompt = build_paddleocr_parameter_recommendation_prompt()
    try:
        content, _finish_reason = ocr_client.call_media(
            prompt,
            endpoint,
            model,
            api_key,
            image_paths=sample_paths,
            max_tokens=max_tokens,
            provider="openai",
        )
    except Exception as e:
        logger.warning(f"[paddleocr-recommender] LLM 추천 요청 실패: {e}")
        return {}

    parsed = _extract_json_from_response(content)
    if not parsed:
        return {}

    validated = validate_parameters(parsed)
    logger.info(f"[paddleocr-recommender] 추천 파라미터: {validated}")
    return validated


def decide_parameters(
    pdf_path: Path,
    sample_dir: Path,
    endpoint: str,
    model: str,
    api_key: str = "",
    dpi: int = SAMPLE_DPI,
    max_tokens: int = 2000,
) -> dict[str, Any]:
    """PDF에서 샘플을 추출하고 LLM 추천을 받아 최종 파라미터를 결정한다.

    LLM 추천이 실패하면 문서 유형 프리셋 중 'mixed'를 기본 fallback으로 사용한다.

    Args:
        pdf_path: 원본 PDF 파일 경로
        sample_dir: 샘플 이미지 저장 디렉터리
        endpoint: Vision LLM 엔드포인트 URL
        model: 모델명
        api_key: API 키
        dpi: 샘플 렌더링 해상도
        max_tokens: LLM 최대 토큰 수

    Returns:
        최종 PaddleOCR-VL predict() 파라미터 딕셔너리
    """
    sample_paths = render_sample_pages(pdf_path, sample_dir, dpi=dpi)
    if not sample_paths:
        return get_preset_parameters("mixed")

    recommended = recommend_parameters(sample_paths, endpoint, model, api_key, max_tokens)
    if recommended:
        return recommended

    logger.info("[paddleocr-recommender] LLM 추천 실패, mixed 프리셋 fallback 사용")
    return get_preset_parameters("mixed")
