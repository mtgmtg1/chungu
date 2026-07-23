#!/usr/bin/env python3
"""core/job_helpers.py의 공통 헬퍼 함수 단위 테스트.

[Flow: Step 1 (순수 함수 테스트) -> Step 2 (Storage/DB 모킹 테스트) -> Step 3 (엣지 케이스)]

이 테스트는 api/jobs.py, api/v1/jobs.py, workers/tasks.py에서 중복되던
3개 헬퍼(_parse_columns, _convert_format_alias, _upload_ocr_layout)의
단일 진실 원천(core/job_helpers.py)을 검증한다.
"""
import json
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest

from backend.core.job_helpers import (
    convert_format_alias,
    parse_columns,
    upload_ocr_layout,
)


# ---------------------------------------------------------------------------
# parse_columns 테스트
# ---------------------------------------------------------------------------
class TestParseColumns:
    """[Flow: 빈 입력 -> JSON 배열 -> 쉼표 구분 -> 기본값]"""

    def test_empty_string_returns_default_columns(self):
        """빈 문자열이면 DEFAULT_COLUMNS를 반환한다."""
        from backend.core.prompts import DEFAULT_COLUMNS

        result = parse_columns("")
        assert result == list(DEFAULT_COLUMNS)

    def test_none_returns_default_columns(self):
        """None이면 DEFAULT_COLUMNS를 반환한다."""
        from backend.core.prompts import DEFAULT_COLUMNS

        result = parse_columns(None)
        assert result == list(DEFAULT_COLUMNS)

    def test_json_array_parsed_correctly(self):
        """JSON 배열 문자열을 파싱한다."""
        result = parse_columns('["이름", "날짜", "금액"]')
        assert result == ["이름", "날짜", "금액"]

    def test_json_array_strips_whitespace(self):
        """JSON 배열 항목의 앞뒤 공백을 제거한다."""
        result = parse_columns('["  이름  ", " 날짜 "]')
        assert result == ["이름", "날짜"]

    def test_json_array_filters_empty_strings(self):
        """빈 문자열 항목은 필터링한다."""
        result = parse_columns('["이름", "", "  "]')
        assert result == ["이름"]

    def test_comma_separated_parsed(self):
        """JSON이 아닌 쉼표 구분 문자열을 파싱한다."""
        result = parse_columns("이름,날짜,금액")
        assert result == ["이름", "날짜", "금액"]

    def test_comma_separated_strips_whitespace(self):
        """쉼표 구분 문자열의 앞뒤 공백을 제거한다."""
        result = parse_columns("  이름 , 날짜 , 금액  ")
        assert result == ["이름", "날짜", "금액"]

    def test_invalid_json_falls_back_to_comma_split(self):
        """잘못된 JSON은 쉼표 구분으로 폴백한다."""
        result = parse_columns("이름,날짜,금액")
        assert result == ["이름", "날짜", "금액"]


# ---------------------------------------------------------------------------
# convert_format_alias 테스트
# ---------------------------------------------------------------------------
class TestConvertFormatAlias:
    """[Flow: 구형 alias -> 신형 포맷 매핑 -> 알 수 없는 포맷는 그대로]"""

    def test_xlsx_alias_mapped_to_xlsx_basic(self):
        """구형 'xlsx' 요청을 'xlsx_basic'으로 매핑한다."""
        assert convert_format_alias("xlsx") == "xlsx_basic"

    def test_csv_alias_mapped_to_csv_basic(self):
        """구형 'csv' 요청을 'csv_basic'으로 매핑한다."""
        assert convert_format_alias("csv") == "csv_basic"

    def test_unknown_format_passed_through(self):
        """알 수 없는 포맷는 그대로 반환한다."""
        assert convert_format_alias("xlsx_advanced") == "xlsx_advanced"

    def test_already_new_format_passed_through(self):
        """이미 신형 포맷이면 그대로 반환한다."""
        assert convert_format_alias("xlsx_basic") == "xlsx_basic"


# ---------------------------------------------------------------------------
# upload_ocr_layout 테스트
# ---------------------------------------------------------------------------
class TestUploadOcrLayout:
    """[Flow: layout 직렬화 -> Storage 업로드 -> DB 경로 저장 -> 예외 처리]"""

    def test_empty_layout_returns_early(self):
        """빈 layout_by_page는 업로드하지 않고 조용히 반환한다."""
        db = MagicMock()
        job = MagicMock()
        job.id = "test-job-id"

        upload_ocr_layout(db, job, {})

        db.commit.assert_not_called()

    def test_none_layout_returns_early(self):
        """None layout_by_page도 업로드하지 않고 반환한다."""
        db = MagicMock()
        job = MagicMock()
        job.id = "test-job-id"

        upload_ocr_layout(db, job, None)

        db.commit.assert_not_called()

    @patch("backend.core.job_helpers.supabase_client")
    def test_valid_layout_uploaded_and_path_saved(self, mock_supabase):
        """유효한 layout은 Storage에 업로드하고 DB에 경로를 저장한다."""
        mock_client = MagicMock()
        mock_supabase.get_service_client.return_value = mock_client
        db = MagicMock()
        job = MagicMock()
        job.id = "job-123"
        layout = {1: {"blocks": [{"text": "hello"}]}}

        upload_ocr_layout(db, job, layout)

        mock_client.storage.from_("results").upload.assert_called_once()
        call_args = mock_client.storage.from_("results").upload.call_args
        assert call_args.args[0] == "job-123/ocr_layout.json"
        assert call_args.args[2] == {"content-type": "application/json", "upsert": "true"}
        assert job.result_ocr_layout_storage_path == "job-123/ocr_layout.json"
        db.commit.assert_called_once()

    @patch("backend.core.job_helpers.supabase_client")
    def test_upload_failure_does_not_raise(self, mock_supabase):
        """Storage 업로드 실패 시 예외를 발생시키지 않고 로그만 남긴다."""
        mock_client = MagicMock()
        mock_client.storage.from_("results").upload.side_effect = Exception("Network error")
        mock_supabase.get_service_client.return_value = mock_client
        db = MagicMock()
        job = MagicMock()
        job.id = "job-fail"

        # 예외가 전파되지 않아야 함
        upload_ocr_layout(db, job, {1: {"text": "data"}})
