#!/usr/bin/env python3
"""[Flow: Step 1 (Storage 가짜 클라이언트 구성) -> Step 2 (_source_files 호출)
      -> Step 3 (목록 조회 1회 / 파일별 merged 경로 분리 검증)]

_source_files 의 주석 병합 경로 회귀 테스트.

이전 구현은 "signed URL 생성이 성공하는가"로 파일 존재를 확인해, 문서 파일 수만큼
Supabase 왕복이 순차로 쌓였다. 또한 병합 결과를 단일 merged_annotations.json 에 써서
파일이 여러 개인 job 에서는 마지막 병합이 앞선 파일 결과를 덮어썼다.
이 테스트는 두 성질(목록 1회 조회, source_index 별 merged 경로)을 고정한다.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import MagicMock

from backend.api.jobs import _source_files
from backend.api.jobs._shared import _list_result_files
from backend.db.models import Job


def _make_job(job_id: str, n_files: int) -> Job:
    job = Job()
    job.id = job_id
    job.original_filename = "doc0.pdf"
    job.extracted_files = [
        {
            "filename": f"doc{i}.pdf",
            "path": f"doc{i}.pdf",
            "storage_path": f"pdfs/doc{i}.pdf",
            "bucket": "pdfs",
            "type": "pdf",
            "source_kind": "original",
            "source_index": i,
        }
        for i in range(n_files)
    ]
    job.annotated_pdf_files = []
    job.annotate_status = ""
    job.searchable_pdf_storage_path = ""
    return job


class FakeBucket:
    """results 버킷 흉내 — list/download/upload 를 지원하고 호출 횟수를 센다."""

    def __init__(self, files: dict[str, bytes], counters: dict[str, int]):
        self.files = files
        self.counters = counters

    def list(self, prefix: str, options: dict | None = None):
        self.counters["list"] += 1
        names = []
        for path in self.files:
            head, _, tail = path.partition("/")
            if head == prefix and tail:
                names.append({"name": tail})
        return names

    def download(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def upload(self, path: str, data: bytes, options: dict | None = None):
        self.counters["upload"] += 1
        self.files[path] = data


@pytest.fixture
def storage(monkeypatch):
    """_source_files 가 쓰는 Storage/서명 의존성을 가짜로 교체한다."""
    files: dict[str, bytes] = {}
    counters = {"list": 0, "upload": 0, "sign": 0}
    bucket = FakeBucket(files, counters)

    class FakeStorage:
        def from_(self, name: str):
            return bucket

    class FakeClient:
        storage = FakeStorage()

    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.get_service_client", lambda: FakeClient()
    )
    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.create_fresh_service_client", lambda: FakeClient()
    )

    # 파라미터명은 프로덕션 시그니처와 반드시 일치해야 한다. 호출부가 bucket= 키워드를
    # 쓰기 때문에, 이름이 다르면 TypeError 가 나고 호출부의 except 에 삼켜져
    # "파일 없음"으로 조용히 오해석된다.
    def _signed(path, bucket="results", expires_in=3600):
        counters["sign"] += 1
        if bucket == "results" and path not in files:
            raise FileNotFoundError(path)
        return f"https://signed.example/{bucket}/{path}"

    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.get_signed_download_url", _signed
    )
    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.get_signed_download_url_with_client",
        lambda client, path, bucket="results", expires_in=3600: _signed(path, bucket, expires_in),
    )
    # clean PDF 추출 경로는 이 테스트의 관심사가 아니므로 무력화한다.
    monkeypatch.setattr(
        "backend.api.jobs._shared._ensure_clean_source_pdf", lambda *a, **k: (None, None)
    )
    mock_pdf = MagicMock()
    mock_pdf.get_preview_pdf_url.return_value = "https://preview.example/doc.pdf"
    monkeypatch.setattr("backend.api.jobs._shared.pdf_preview_converter", mock_pdf)

    return {"files": files, "counters": counters}


def test_list_result_files_returns_names(storage):
    storage["files"]["job-1/user_annotations_0.json"] = b"[]"
    storage["files"]["job-1/other.json"] = b"[]"
    storage["files"]["job-2/elsewhere.json"] = b"[]"
    assert _list_result_files("job-1") == {"user_annotations_0.json", "other.json"}


def test_list_result_files_returns_none_on_failure(monkeypatch):
    """목록 조회가 실패하면 None 을 반환해 호출부가 개별 탐색으로 폴백하게 한다."""

    def _boom():
        raise RuntimeError("storage down")

    monkeypatch.setattr(
        "backend.api.jobs._shared.supabase_client.get_service_client", _boom
    )
    assert _list_result_files("job-1") is None


def test_listing_count_does_not_grow_with_file_count(storage):
    """존재 확인용 목록 조회 횟수는 버킷 수에만 비례하고, 문서 수에는 비례하지 않아야 한다.

    파일마다 signed URL 탐색이나 download() 확인을 돌리던 예전 구조로 되돌아가면
    이 값이 파일 수를 따라 늘어난다.
    """
    _source_files(_make_job("job-one", n_files=1))
    one = storage["counters"]["list"]

    storage["counters"]["list"] = 0
    _source_files(_make_job("job-many", n_files=8))
    many = storage["counters"]["list"]

    assert one == many, f"파일 수에 따라 목록 조회가 늘었다: 1개={one}, 8개={many}"
    assert many <= 2, f"버킷(results/pdfs)당 1회를 넘었다: {many}"


def test_no_user_annotations_skips_merge_entirely(storage):
    """사용자 주석이 없으면 병합 업로드가 한 번도 일어나지 않는다."""
    job = _make_job("job-clean", n_files=3)
    result = _source_files(job)
    assert storage["counters"]["upload"] == 0
    assert all("annotations_json_url" not in item for item in result)


def test_merged_path_is_per_source_index(storage):
    """파일마다 서로 다른 merged 경로를 써야 앞선 병합이 덮어써지지 않는다."""
    job = _make_job("job-multi", n_files=3)
    for i in range(3):
        storage["files"][f"job-multi/user_annotations_{i}.json"] = json.dumps(
            [{"annotation": {"id": f"a{i}", "pageIndex": i, "type": 1, "contents": f"note{i}"}}]
        ).encode()

    result = _source_files(job)

    urls = [item["annotations_json_url"] for item in result]
    assert len(set(urls)) == 3, f"merged URL 이 파일별로 분리되지 않았다: {urls}"
    for i in range(3):
        assert f"job-multi/merged_annotations_{i}.json" in urls[i]
        merged = json.loads(storage["files"][f"job-multi/merged_annotations_{i}.json"])
        assert merged[0]["annotation"]["contents"] == f"note{i}"


def test_shared_user_annotations_fallback_applies_to_first_file_only(storage):
    """파일별 JSON 이 없을 때 공유 user_annotations.json 은 source_index 0 에만 적용된다."""
    job = _make_job("job-legacy", n_files=2)
    storage["files"]["job-legacy/user_annotations.json"] = json.dumps(
        [{"annotation": {"id": "legacy", "pageIndex": 0, "type": 1, "contents": "old"}}]
    ).encode()

    result = _source_files(job)

    assert "annotations_json_url" in result[0]
    assert "annotations_json_url" not in result[1]
