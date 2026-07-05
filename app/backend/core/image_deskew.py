#!/usr/bin/env python3
# [Flow: Step 1 (이미지 로드 → 그레이스케일 변환) -> Step 2 (determine_skew로 미세 기울기 각도 추정)
#       -> Step 3 (임계값 이하면 원본 그대로 반환) -> Step 4 (cv2.warpAffine 역회전 적용)
#       -> Step 5 (보정된 이미지를 지정 경로에 저장 후 경로 반환)]
# 이미지 미세 회전(수평에서 몇 도 기울어짐)을 감지하고 수평으로 보정하는 모듈.
# 90°/180°/270° 단위的大회전은 처리하지 않는다 — AI Studio API의 useDocOrientationClassify가 담당.
# deskew 라이브러리(determine_skew)는 텍스트 줄의 투영 프로파일 분산을 기반으로 [-45°, 45°] 범위의
# 실수 각도를 추정하므로 "살짝 기울어진 스캔/사진" 케이스에 최적이다.
from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# |각도|가 이 값 미만이면 보정하지 않고 원본을 그대로 사용한다.
# 너무 작은 각도는 노이즈일 수 있고, 불필요한 warpAffine 호출과 미세한 이미지 열화를 방지한다.
DESkew_MIN_ANGLE_DEG = 0.5

# 보정 후 이미지 테두리의 빈 영역을 채울 배경색 (흰색).
# 문서 이미지이므로 흰 배경이 가장 자연스럽다.
DESkew_BACKGROUND = (255, 255, 255)


def determine_skew_angle(image_path: Path) -> float:
    """이미지에서 미세 기울기 각도(도 단위)를 추정한다.

    Args:
        image_path: 입력 이미지 파일 경로 (PNG/JPG/BMP/TIFF/WebP)

    Returns:
        추정된 기울기 각도(도 단위, [-45, 45]). 추정 실패 시 0.0.
        양수 = 시계방향 기울어짐, 음수 = 반시계방향 기울어짐 (deskew 라이브러리 기준).
    """
    try:
        from deskew import determine_skew
    except ImportError:
        logger.warning("[image_deskew] deskew 패키지가 설치되어 있지 않아 각도 추정을 건너뜁니다")
        return 0.0

    try:
        # 그레이스케일로 로드 (determine_skew는 2D 배열을 요구)
        gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            logger.warning(f"[image_deskew] 이미지 로드 실패: {image_path.name}")
            return 0.0

        angle = determine_skew(gray)
        if angle is None or not math.isfinite(angle):
            logger.info(f"[image_deskew] {image_path.name} 각도 추정 불가 (None) — 보정 생략")
            return 0.0

        logger.info(f"[image_deskew] {image_path.name} 추정 기울기 각도: {angle:.3f}°")
        return float(angle)
    except Exception as e:
        logger.warning(f"[image_deskew] {image_path.name} 각도 추정 실패: {e}")
        return 0.0


def rotate_image(image_path: Path, angle: float, output_path: Path) -> Path:
    """이미지를 주어진 각도(도 단위)만큼 회전시켜 저장한다.

    deskew의 determine_skew가 반환한 각도를 그대로 전달하면 수평으로 보정된다.
    배경은 흰색으로 채운다.

    Args:
        image_path: 원본 이미지 경로
        angle: 회전 각도 (도 단위, 시계방향 양수)
        output_path: 출력 이미지 경로

    Returns:
        output_path (회전된 이미지가 저장된 경로)
    """
    img = cv2.imread(str(image_path))
    if img is None:
        raise RuntimeError(f"이미지 로드 실패: {image_path}")

    h, w = img.shape[:2]
    center = (w / 2.0, h / 2.0)
    # cv2.getRotationMatrix2D: 양수 각도 = 반시계방향. deskew 각도를 그대로 전달하면
    # 기울어진 방향의 반대로 회전해 수평이 된다.
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    # 회전 후 캔버스가 원본 크기를 유지하도록 출력 크기를 원본과 동일하게 지정.
    rotated = cv2.warpAffine(
        img, matrix, (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=DESkew_BACKGROUND,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(output_path), rotated)
    logger.info(f"[image_deskew] {image_path.name} 회전({angle:.3f}°) → {output_path.name}")
    return output_path


def deskew_image(image_path: Path, output_dir: Path | None = None) -> Tuple[Path, float]:
    """이미지의 미세 기울기를 보정한 이미지를 반환한다.

    [Flow: Step 1 (각도 추정) -> Step 2 (임계값 미만이면 원본 반환) -> Step 3 (역회전 적용)]

    Args:
        image_path: 입력 이미지 경로
        output_dir: 보정된 이미지를 저장할 디렉터리. None이면 image_path와 같은 디렉터리.

    Returns:
        (보정된 이미지 경로, 적용된 각도). 임계값 미만이면 (image_path, 0.0).
        보정이 필요 없으면 원본 경로를 그대로 반환한다.
    """
    angle = determine_skew_angle(image_path)

    if abs(angle) < DESkew_MIN_ANGLE_DEG:
        logger.info(f"[image_deskew] {image_path.name} 기울기 미미({angle:.3f}°) — 원본 그대로 사용")
        return image_path, 0.0

    if output_dir is None:
        output_dir = image_path.parent
    output_path = output_dir / f"{image_path.stem}_deskew{image_path.suffix}"
    corrected_path = rotate_image(image_path, angle, output_path)
    return corrected_path, angle
