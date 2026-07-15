#!/usr/bin/env python3
# [Flow: Step 1 (backend 패키지 경로 설정) -> Step 2 (마커/구분자/길이 분할 시나리오 정의) -> Step 3 (_split_markdown_by_pages 호출) -> Step 4 (결과 검증)]
"""api/jobs.py의 _split_markdown_by_pages 페이지 분할 로직을 테스트한다."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest

from backend.api.jobs import _split_markdown_by_pages


def test_page_markers():
    """페이지 마커를 기준으로 분할한다."""
    md = "<!-- Page 1 -->\n\n첫 페이지\n\n---\n\n<!-- Page 2 -->\n\n두 페이지"
    pages = _split_markdown_by_pages(md)
    assert len(pages) == 2
    assert pages[0] == (1, "첫 페이지")
    assert pages[1] == (2, "두 페이지")


def test_legacy_korean_markers():
    """기존 한국어 마커도 하위 호환성을 위해 분할한다."""
    md = "<!-- 페이지 1 -->\n\nfirst\n\n---\n\n<!-- 페이지 2 -->\n\nsecond"
    pages = _split_markdown_by_pages(md)
    assert len(pages) == 2
    assert pages[0] == (1, "first")
    assert pages[1] == (2, "second")


def test_no_markers_with_horizontal_rule():
    """마커가 없고 Horizontal Rule로 분리되어 있으면 분할한다."""
    md = "첫 페이지\n\n---\n\n두 페이지"
    pages = _split_markdown_by_pages(md)
    assert len(pages) == 2
    assert pages[0][1] == "첫 페이지"
    assert pages[1][1] == "두 페이지"


def test_no_markers_with_asterisk_hrule():
    """'* * *' 형태의 Horizontal Rule로도 분할한다."""
    md = "첫 페이지\n\n* * *\n\n두 페이지"
    pages = _split_markdown_by_pages(md)
    assert len(pages) == 2


def test_no_markers_no_hrule_with_expected_pages():
    """마커/구분자가 없으면 expected_pages 개로 균등 분할한다."""
    md = "abcdefgh"
    pages = _split_markdown_by_pages(md, expected_pages=2)
    assert len(pages) == 2
    assert pages[0][1] == "abcd"
    assert pages[1][1] == "efgh"


def test_no_markers_default_to_single_page():
    """마커/구분자/expected_pages 모두 없으면 전체를 1페이지로 반환한다."""
    md = "single page content"
    pages = _split_markdown_by_pages(md)
    assert len(pages) == 1
    assert pages[0] == (1, "single page content")


def test_empty_markdown():
    """빈 마크다운은 빈 리스트를 반환한다."""
    assert _split_markdown_by_pages("") == []
    assert _split_markdown_by_pages("   \n\n  ") == []
