# [Flow: Step 1 (_publicize_url에 내부/외부 URL 샘플 입력) -> Step 2 (scheme/netloc 교환 검증)]
# Supabase signed URL이 내부 HTTP 주소일 때 외부 HTTPS 주소로 재작성되는지 검증.

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest

from backend.core import supabase_client
from backend.core.supabase_client import _publicize_url


@pytest.fixture(autouse=True)
def _patch_settings(monkeypatch):
    """테스트에서 settings.supabase_url/supabase_public_url이 .env 값을 덮어쓰지 않도록 비운다."""
    monkeypatch.setattr(supabase_client.settings, "supabase_url", "")
    monkeypatch.setattr(supabase_client.settings, "supabase_public_url", "")


def test_publicize_url_rewrites_internal_to_public():
    """내부 HTTP URL을 외부 HTTPS 공개 URL로 교환한다."""
    internal = "http://192.168.1.50:28000/storage/v1/object/sign/pdfs/job/file.pdf?token=abc"
    expected = "https://proof.teamcat.app/storage/v1/object/sign/pdfs/job/file.pdf?token=abc"
    assert (
        _publicize_url(internal, "http://192.168.1.50:28000", "https://proof.teamcat.app/supabase")
        == expected
    )


def test_publicize_url_keeps_empty_public_url():
    """public_url이 비어 있으면 원본 URL을 그대로 반환한다."""
    internal = "http://192.168.1.50:28000/storage/v1/object/sign/pdfs/job/file.pdf"
    assert _publicize_url(internal, "http://192.168.1.50:28000", "") == internal


def test_publicize_url_keeps_same_url():
    """internal과 public이 같으면 원본 URL을 그대로 반환한다."""
    internal = "http://192.168.1.50:28000/storage/v1/object/sign/pdfs/job/file.pdf"
    assert _publicize_url(internal, "http://192.168.1.50:28000", "http://192.168.1.50:28000") == internal


def test_publicize_url_preserves_path_and_query():
    """path와 query string은 그대로 유지된다."""
    internal = "http://internal:8000/storage/v1/object/sign/results/job/result.md?token=xyz&expires=123"
    expected = "https://external.example.com/storage/v1/object/sign/results/job/result.md?token=xyz&expires=123"
    assert _publicize_url(internal, "http://internal:8000", "https://external.example.com") == expected
