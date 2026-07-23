#!/usr/bin/env python3
"""PROOF Job 공통 헬퍼 함수 — api/jobs.py, api/v1/jobs.py, workers/tasks.py에서 공유.

[Flow: Step 1 (순수 유틸 함수 제공) -> Step 2 (Storage/DB 연동 헬퍼 제공)
      -> Step 3 (각 호출처에서 import하여 중복 제거)]

이 모듈은 3개 영역(api/jobs.py, api/v1/jobs.py, workers/tasks.py)에 중복 정의되었던
헬퍼 함수들의 단일 진실 원천(single source of truth)이다.

주의: _job_summary, _get_markdown_content, _ensure_xlsx_basic_bundle은
web/API 간 의도적 차이(필드 수, 결제 시스템 등)가 있으므로 이 모듈에 포함하지 않는다.
"""
from __future__ import annotations

import json
import logging

from . import supabase_client
from .prompts import DEFAULT_COLUMNS

logger = logging.getLogger(__name__)


def parse_columns(raw: str) -> list[str]:
    """사용자가 지정한 컬럼 문자열을 파싱하여 컬럼 리스트를 반환한다.

    [Flow: Step 1 (빈 입력 → 기본 컬럼) -> Step 2 (JSON 배열 시도)
          -> Step 3 (JSON 실패 시 쉼표 구분으로 폴백) -> Step 4 (빈 항목 필터링)]

    매개변수:
        raw: 컬럼 문자열. JSON 배열("['a','b']") 또는 쉼표 구분("a,b,c"). 빈 값이면 DEFAULT_COLUMNS.

    반환값:
        컬럼 이름 리스트. 빈 문자열 항목은 제거됨.
    """
    raw = (raw or "").strip()
    if not raw:
        return list(DEFAULT_COLUMNS)
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            return [str(c).strip() for c in parsed if str(c).strip()]
    except json.JSONDecodeError:
        pass
    return [c.strip() for c in raw.split(",") if c.strip()]


def convert_format_alias(fmt: str) -> str:
    """구형 'xlsx'/'csv' 요청을 새 기본 변환 포맷으로 매핑한다.

    매개변수:
        fmt: 포맷 문자열 (예: "xlsx", "csv", "xlsx_basic", "xlsx_advanced")

    반환값:
        매핑된 포맷. 알 수 없는 포맷는 그대로 반환.
    """
    return {"xlsx": "xlsx_basic", "csv": "csv_basic"}.get(fmt, fmt)


def upload_ocr_layout(db, job, layout_by_page: dict[int, dict]) -> None:
    """OCR layout_by_page를 Storage에 저장하고 Job DB에 경로를 기록한다.

    [Flow: Step 1 (빈 layout 가드) -> Step 2 (JSON 직렬화) -> Step 3 (results 버킷 업로드)
          -> Step 4 (Job.result_ocr_layout_storage_path 갱신 + commit)]

    PaddleOCR로 확보한 layout_by_page를 Storage에 저장해 이후
    get_elements/search_text 호출이 PaddleOCR을 재실행하지 않도록 한다.
    업로드 실패 시 예외를 전파하지 않고 경고 로그만 남긴다.

    매개변수:
        db: SQLAlchemy Session
        job: Job 모델 인스턴스
        layout_by_page: 페이지 번호 → layout 딕셔너리. 빈 값이면 조용히 반환.
    """
    if not layout_by_page:
        return
    try:
        data = json.dumps(layout_by_page, ensure_ascii=False, default=str).encode("utf-8")
        storage_path = f"{job.id}/ocr_layout.json"
        client = supabase_client.get_service_client()
        client.storage.from_("results").upload(
            storage_path,
            data,
            {"content-type": "application/json", "upsert": "true"},
        )
        job.result_ocr_layout_storage_path = storage_path
        db.commit()
        logger.info(f"[upload_ocr_layout] {job.id} OCR layout 저장 완료: {storage_path}")
    except Exception as e:
        logger.warning(f"[upload_ocr_layout] {job.id} OCR layout 저장 실패: {e}")
