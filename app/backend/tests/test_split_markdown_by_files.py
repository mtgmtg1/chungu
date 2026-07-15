#!/usr/bin/env python3
# [Flow: Step 1 (backend 패키지 경로 설정) -> Step 2 (파일 마커/단일 파일 시나리오 정의) -> Step 3 (_split_markdown_by_files 호출) -> Step 4 (결과 검증)]
"""api/jobs.py의 _split_markdown_by_files 파일 분할 로직을 테스트한다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest

from backend.api.jobs import _split_markdown_by_files


def test_file_markers():
    """파일 마커를 기준으로 분할한다."""
    md = "<!-- 파일 1 -->\n\n첫 파일\n\n---\n\n<!-- 파일 2 -->\n\n두 파일"
    files = _split_markdown_by_files(md)
    assert len(files) == 2
    assert files[0] == (1, "첫 파일")
    assert files[1] == (2, "두 파일")


def test_single_file_without_marker():
    """파일 마커가 없으면 전체를 1개 파일로 반환한다."""
    md = "single file content"
    files = _split_markdown_by_files(md)
    assert len(files) == 1
    assert files[0] == (1, "single file content")


def test_empty_markdown():
    """빈 마크다운은 빈 리스트를 반환한다."""
    assert _split_markdown_by_files("") == []
    assert _split_markdown_by_files("   \n\n  ") == []


def test_file_marker_strips_hrule_separator():
    """파일 마커 사이의 Horizontal Rule 구분자를 제거한다."""
    md = "<!-- 파일 1 -->\n\n내용\n\n---\n\n<!-- 파일 2 -->\n\n또 다른 내용"
    files = _split_markdown_by_files(md)
    assert files[0] == (1, "내용")
    assert files[1] == (2, "또 다른 내용")
