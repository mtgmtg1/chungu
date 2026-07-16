#!/usr/bin/env python3
# [Flow: Step 1 (확장자/타입 매핑 케이스 정의) -> Step 2 (sandbox collector 및 sandboxes.py 매핑 검증)]
"""sandbox 결과 수집 시 pptx/hwp/docx 확장자 매핑 및 MIME 추정을 검증한다."""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.sandboxes import _ext_to_file_type
from backend.core.sandbox.collector import COLLECT_EXTENSIONS, _guess_content_type


def test_ext_to_file_type_maps_documents():
    """sandboxes.py의 확장자-타입 매핑이 문서 미리보기 타입을 올바르게 반환한다."""
    assert _ext_to_file_type(".pptx") == "pptx"
    assert _ext_to_file_type(".ppt") == "pptx"
    assert _ext_to_file_type(".ppsx") == "pptx"
    assert _ext_to_file_type(".pps") == "pptx"
    assert _ext_to_file_type(".hwp") == "hwp"
    assert _ext_to_file_type(".hwpx") == "hwp"
    assert _ext_to_file_type(".docx") == "docx"
    assert _ext_to_file_type(".doc") == "docx"


def test_collect_extensions_include_documents():
    """ResultCollector가 pptx/hwp/docx 파일을 수집 대상에 포함한다."""
    for ext in (".pptx", ".ppt", ".ppsx", ".pps", ".hwp", ".hwpx", ".docx", ".doc"):
        assert ext in COLLECT_EXTENSIONS, f"{ext} not in COLLECT_EXTENSIONS"


def test_guess_content_type_for_documents():
    """_guess_content_type이 문서 확장자에 대해 적절한 MIME을 반환한다."""
    assert _guess_content_type(".pptx") == "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    assert _guess_content_type(".hwp") == "application/x-hwp"
    assert _guess_content_type(".hwpx") == "application/vnd.hancom.hwpx"
    assert _guess_content_type(".docx") == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
