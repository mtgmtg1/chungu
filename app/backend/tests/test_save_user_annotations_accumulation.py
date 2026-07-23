# [Flow: Step 1 (save_user_annotations 누적 병합 단위 테스트) -> Step 2 (다중 주석 추가 시 기존 주석 보존 검증) -> Step 3 (명시적 removals 삭제 검증)]
"""save_user_annotations 엔드포인트가 기존 주석을 덮어쓰지 않고 ID 기반으로 누적 병합(Accumulative Merge)하는지 검증하는 테스트."""

import sys
import os
import json
from unittest.mock import patch, MagicMock
from pytest import fixture

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.api.jobs import save_user_annotations
from backend.db.models import Job


def make_annotation(annot_id: str, page_index: int = 0, contents: str = "Test") -> dict:
    """[Flow: EmbedPDF AnnotationTransferItem 객체 생성]"""
    return {
        "annotation": {
            "id": annot_id,
            "type": 9,
            "pageIndex": page_index,
            "rect": {"origin": {"x": 10, "y": 20}, "size": {"width": 100, "height": 30}},
            "contents": contents,
        }
    }


class FakeStorage:
    """[Flow: Step 1 (인메모리 바이트 저장소) -> Step 2 (download / upload 지원)]"""
    def __init__(self):
        self.files = {}

    def from_(self, bucket: str):
        storage_self = self
        class FakeBucket:
            def download(self, path: str) -> bytes:
                if path not in storage_self.files:
                    raise FileNotFoundError(f"Path not found: {path}")
                return storage_self.files[path]

            def upload(self, path: str, data: bytes, options: dict = None):
                storage_self.files[path] = data
                return True
        return FakeBucket()


def test_save_user_annotations_accumulates_previous_annotations():
    """[Flow: Step 1 (첫 번째 주석 ai-1 저장) -> Step 2 (두 번째 주석 ai-2 저장) -> Step 3 (두 주석 모두 보존 확인)]"""
    fake_storage = FakeStorage()
    mock_client = MagicMock()
    mock_client.storage = fake_storage

    job = Job()
    job.id = "job-accumulate-test"
    job.annotated_pdf_files = []
    job.pdf_storage_path = "job-accumulate-test/input.pdf"

    mock_db = MagicMock()
    mock_db.get.return_value = job
    mock_db.execute.return_value.scalar_one.return_value = job

    with patch("backend.api.jobs.annotations.supabase_client.get_service_client", return_value=mock_client), \
         patch("backend.api.jobs.annotations._require_job_access"), \
         patch("backend.api.jobs.annotations._require_job_not_expired"), \
         patch("backend.api.jobs.annotations.cache"):

        # 1. 첫 번째 주석 ai-1 저장
        payload1 = {
            "source_index": 0,
            "annotations": [make_annotation("ai-1", 0, "First annotation")],
            "input_space": "device",
        }
        res1 = save_user_annotations(
            job_id="job-accumulate-test",
            payload=payload1,
            user=MagicMock(),
            db=mock_db,
        )
        assert res1["ok"] is True

        # Storage 확인: ai-1 존재
        path = res1["annotations_json_storage_path"]
        saved_bytes1 = fake_storage.files[path]
        saved_data1 = json.loads(saved_bytes1.decode("utf-8"))
        assert len(saved_data1) == 1
        assert saved_data1[0]["annotation"]["id"] == "ai-1"

        # 2. 두 번째 주석 ai-2 저장 (ai-1은 전송 목록에 포함하지 않고 신규만 전달)
        payload2 = {
            "source_index": 0,
            "annotations": [make_annotation("ai-2", 0, "Second annotation")],
            "input_space": "device",
        }
        res2 = save_user_annotations(
            job_id="job-accumulate-test",
            payload=payload2,
            user=MagicMock(),
            db=mock_db,
        )
        assert res2["ok"] is True

        # Storage 확인: ai-1 과 ai-2 모두 누적 보존되어야 함!
        saved_bytes2 = fake_storage.files[path]
        saved_data2 = json.loads(saved_bytes2.decode("utf-8"))
        saved_ids = [item["annotation"]["id"] for item in saved_data2]
        assert "ai-1" in saved_ids, "이전 주석 ai-1이 삭제되지 않고 누적 보존되어야 합니다."
        assert "ai-2" in saved_ids, "신규 주석 ai-2가 추가되어야 합니다."
        assert len(saved_data2) == 2


def test_save_user_annotations_removals_deletes_specified_id():
    """[Flow: Step 1 (ai-1, ai-2 존재 상태 준비) -> Step 2 (removals: ['ai-1'] 전달) -> Step 3 (ai-1 삭제, ai-2 보존 확인)]"""
    fake_storage = FakeStorage()
    mock_client = MagicMock()
    mock_client.storage = fake_storage

    job = Job()
    job.id = "job-removals-test"
    job.annotated_pdf_files = []
    job.pdf_storage_path = "job-removals-test/input.pdf"

    mock_db = MagicMock()
    mock_db.get.return_value = job
    mock_db.execute.return_value.scalar_one.return_value = job

    path = "job-removals-test/user_annotations_0.json"
    initial_annots = [
        make_annotation("ai-1", 0, "First"),
        make_annotation("ai-2", 0, "Second"),
    ]
    fake_storage.files[path] = json.dumps(initial_annots).encode("utf-8")

    with patch("backend.api.jobs.annotations.supabase_client.get_service_client", return_value=mock_client), \
         patch("backend.api.jobs.annotations._require_job_access"), \
         patch("backend.api.jobs.annotations._require_job_not_expired"), \
         patch("backend.api.jobs.annotations.cache"):

        payload = {
            "source_index": 0,
            "annotations": [], # 신규 추가 없음
            "removals": ["ai-1"], # ai-1 만 명시적으로 삭제
            "input_space": "device",
        }
        res = save_user_annotations(
            job_id="job-removals-test",
            payload=payload,
            user=MagicMock(),
            db=mock_db,
        )
        assert res["ok"] is True

        saved_bytes = fake_storage.files[path]
        saved_data = json.loads(saved_bytes.decode("utf-8"))
        saved_ids = [item["annotation"]["id"] for item in saved_data]
        assert "ai-1" not in saved_ids, "removals에 지정된 ai-1은 삭제되어야 합니다."
        assert "ai-2" in saved_ids, "removals에 지정되지 않은 ai-2는 보존되어야 합니다."
        assert len(saved_data) == 1
