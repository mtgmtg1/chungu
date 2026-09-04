#!/usr/bin/env python3
"""[Flow: Step 1 (Storage/캐시 가짜 구성) -> Step 2 (_ensure_clean_source_pdf 두 번 호출)
      -> Step 3 (2회차에 원본 재다운로드가 없는지 검증)]

_ensure_clean_source_pdf 회귀 테스트.

예전 구현은 (1) clean PDF 존재 확인을 download() 로 해서 파일 전체를 받아 버렸고,
(2) "내장 주석 없음" 판정을 어디에도 남기지 않아 preview 캐시가 만료될 때마다
원본 PDF 를 다시 내려받아 다시 파싱했다. 두 성질을 모두 고정한다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from backend.api.jobs import _shared


@pytest.fixture
def storage(monkeypatch):
    files: dict[str, bytes] = {"pdfs/doc.pdf": b"%PDF-1.4 fake"}
    counters = {"download": 0, "list": 0}

    class FakeBucket:
        def list(self, prefix, options=None):
            counters["list"] += 1
            out = []
            for path in files:
                head, _, tail = path.partition("/")
                if head == prefix and tail:
                    out.append({"name": tail})
            return out

        def download(self, path):
            counters["download"] += 1
            if path not in files:
                raise FileNotFoundError(path)
            return files[path]

        def upload(self, path, data, options=None):
            files[path] = data

    class FakeStorage:
        def from_(self, name):
            return FakeBucket()

    class FakeClient:
        storage = FakeStorage()

    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.get_service_client", lambda: FakeClient()
    )
    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.get_signed_download_url",
        lambda path, bucket="results", expires_in=3600: f"https://signed/{bucket}/{path}",
    )

    # Redis 대신 프로세스 내 dict 를 쓴다.
    store: dict[str, object] = {}
    monkeypatch.setattr("backend.api.jobs._shared.cache.get", lambda k: store.get(k))
    monkeypatch.setattr(
        "backend.api.jobs._shared.cache.set", lambda k, v, ttl_seconds=0: store.__setitem__(k, v)
    )
    monkeypatch.setattr(
        "backend.api.jobs._shared.cache.invalidate_pattern",
        lambda pattern: [store.pop(k) for k in list(store) if k.startswith(pattern.rstrip("*"))],
    )

    return {"files": files, "counters": counters, "cache": store}


def test_no_embedded_annotations_is_remembered(storage, monkeypatch):
    """내장 주석이 없다는 판정을 캐시해, 두 번째 호출은 원본을 다시 받지 않는다."""
    monkeypatch.setattr(
        "backend.api.jobs._shared.pdf_user_annotator.extract_pdf_annotations", lambda b: []
    )

    first = _shared._ensure_clean_source_pdf("job-1", "pdfs/doc.pdf", "pdfs")
    assert first == (None, [])
    downloads_after_first = storage["counters"]["download"]
    assert downloads_after_first == 1, "원본 1회 다운로드가 기대값"

    second = _shared._ensure_clean_source_pdf("job-1", "pdfs/doc.pdf", "pdfs")
    assert second == (None, [])
    assert storage["counters"]["download"] == downloads_after_first, (
        "판정이 캐시되지 않아 원본을 다시 내려받았다"
    )


def test_existing_clean_pdf_is_not_downloaded(storage, monkeypatch):
    """clean PDF 존재 확인은 목록 조회로 해야 하며, 파일을 내려받아선 안 된다."""
    import hashlib

    path_hash = hashlib.md5(b"pdfs/doc.pdf").hexdigest()[:12]
    storage["files"][f"job-1/clean_{path_hash}.pdf"] = b"%PDF clean"

    def _boom(_bytes):
        raise AssertionError("clean PDF 가 있으면 주석 추출까지 가면 안 된다")

    monkeypatch.setattr(
        "backend.api.jobs._shared.pdf_user_annotator.extract_pdf_annotations", _boom
    )

    url, annotations = _shared._ensure_clean_source_pdf("job-1", "pdfs/doc.pdf", "pdfs")

    assert url == f"https://signed/pdfs/job-1/clean_{path_hash}.pdf"
    assert annotations is None
    assert storage["counters"]["download"] == 0, "존재 확인에 download() 를 썼다"


def test_verdict_is_cleared_by_preview_invalidation(storage, monkeypatch):
    """판정 캐시는 preview 네임스페이스에 있어 기존 무효화 호출에 함께 지워져야 한다."""
    monkeypatch.setattr(
        "backend.api.jobs._shared.pdf_user_annotator.extract_pdf_annotations", lambda b: []
    )
    _shared._ensure_clean_source_pdf("job-1", "pdfs/doc.pdf", "pdfs")
    assert any(k.startswith("preview:job-1:") for k in storage["cache"])

    _shared.cache.invalidate_pattern("preview:job-1:*")
    assert not any(k.startswith("preview:job-1:") for k in storage["cache"])

    _shared._ensure_clean_source_pdf("job-1", "pdfs/doc.pdf", "pdfs")
    assert storage["counters"]["download"] == 2, "무효화 후에는 다시 판정해야 한다"
