#!/usr/bin/env python3
"""[Flow: Step 1 (가상 Job + device-space 주석 JSON + 원본/기준 PDF 모킹)
      -> Step 2 (get_job_result_json 호출)
      -> Step 3 (반환된 annotations이 PDF user-space로 변환되었는지 검증)]

read_job_json 도구가 사용하는 /api/jobs/{id}/result-json?kind=annotations 엔드포인트가
get_annotations과 동일하게 PDF user-space 좌표계를 반환하는지 검증한다.
AI 백엔드가 read_job_json 결과를 save_annotations으로 재사용할 때
좌표계 불일치로 상하 반전이 발생하지 않도록 하기 위한 회귀 테스트다.

추가로 _coordinate_context 메타데이터가 있을 때 기준 PDF의 페이지 크기를 사용하고,
없을 때는 job.pdf_storage_path로 폴백하는지 검증한다.
"""
import sys
import os
import io
import json
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.api.jobs import get_job_result_json
from backend.db.models import Job


def _make_a4_pdf_bytes() -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> A4 페이지 -> 바이트 반환]"""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def _make_tall_pdf_bytes(width: float = 595.0, height: float = 1684.0) -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> 지정 크기 페이지 -> 바이트 반환]"""
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def _make_device_annotation() -> dict:
    """[Flow: A4 페이지 상단 device-space rect 생성 -> AnnotationTransferItem 형태 반환]

    device-space origin.y=22, height=20이면 PDF user-space origin.y=842-22-20=800이어야 한다.
    """
    return {
        "annotation": {
            "id": "backend-1-0-highlight",
            "type": 9,
            "pageIndex": 0,
            "rect": {"origin": {"x": 100.0, "y": 22.0}, "size": {"width": 100.0, "height": 20.0}},
            "segmentRects": [{"origin": {"x": 100.0, "y": 22.0}, "size": {"width": 100.0, "height": 20.0}}],
            "strokeColor": "#FFEB3B",
            "color": "#FFEB3B",
            "opacity": 0.5,
            "contents": "test",
        }
    }


def _make_context(pdf_storage_path: str, bucket: str, width: float, height: float) -> dict:
    """[Flow: 페이지 크기 dict 생성 -> _coordinate_context dict 반환]"""
    return {
        "pdf_storage_path": pdf_storage_path,
        "bucket": bucket,
        "page_dimensions": {
            "1": {"width": width, "height": height, "x0": 0.0, "y0": 0.0, "rotation": 0}
        },
        "input_space": "device",
    }


class TestGetJobResultJsonAnnotations:
    """get_job_result_json(kind=annotations)이 PDF user-space를 반환한다."""

    def test_result_json_annotations_converted_to_pdf_user(self, monkeypatch):
        # [Flow: Job 인스턴스 생성 및 필드 설정]
        job_id = "test-job-result-json"
        job = Job()
        job.id = job_id
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.user_id = "test-user"
        job.created_at = None
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
            }
        ]

        # [Flow: DB 의존성 모킹 -> get_job_result_json 호출 시 job 반환]
        class MockDb:
            def get(self, model, key):
                if model is Job and key == job_id:
                    return job
                return None

        # [Flow: Storage 의존성 모킹 -> device-space 주석 JSON + 원본 PDF 반환]
        annotations_json = json.dumps([_make_device_annotation()], ensure_ascii=False).encode("utf-8")
        pdf_bytes = _make_a4_pdf_bytes()
        bucket_files = {
            f"results:{job_id}/annotated.annotations.json": annotations_json,
            f"pdfs:{job_id}/original.pdf": pdf_bytes,
        }

        class FakeBucket:
            def download(self, path: str) -> bytes:
                for key, data in bucket_files.items():
                    if key.endswith(path):
                        return data
                raise FileNotFoundError(f"not found: {path}")

            def upload(self, path: str, data: bytes, options: dict | None = None):
                pass

        class FakeStorage:
            def from_(self, bucket: str):
                self._bucket = bucket
                return self

            def download(self, path: str) -> bytes:
                key = f"{self._bucket}:{path}"
                if key in bucket_files:
                    return bucket_files[key]
                raise FileNotFoundError(f"not found: {key}")

            def upload(self, path: str, data: bytes, options: dict | None = None):
                pass

        class FakeClient:
            storage = FakeStorage()

        monkeypatch.setattr("backend.api.jobs.supabase_client.get_service_client", lambda: FakeClient())

        # [Flow: 현재 사용자 의존성 모킹 -> 소유자 검증 통과]
        class FakeUser:
            is_dev_bypass = False
            user_id = "test-user"

        # [Flow: 엔드포인트 직접 호출 -> 응답 검증]
        response = get_job_result_json(
            job_id=job_id,
            kind="annotations",
            source_index=0,
            page_no=None,
            user=FakeUser(),
            db=MockDb(),
        )

        assert response["kind"] == "annotations"
        assert response["total"] == 1
        data = response["data"]
        assert isinstance(data, list)
        assert len(data) == 1
        annotation = data[0]["annotation"]
        rect = annotation["rect"]
        # A4 842pt 기준 device origin.y=22, height=20 -> PDF user origin.y=800
        assert rect["origin"]["y"] == pytest.approx(800.0, abs=0.01)
        assert rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        assert rect["size"]["width"] == pytest.approx(100.0, abs=0.01)
        assert rect["size"]["height"] == pytest.approx(20.0, abs=0.01)

    def test_result_json_uses_coordinate_context_pdf(self, monkeypatch):
        """_coordinate_context가 있으면 해당 PDF의 페이지 크기로 변환한다."""
        job_id = "test-job-context"
        job = Job()
        job.id = job_id
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.user_id = "test-user"
        job.created_at = None

        original_pdf = _make_a4_pdf_bytes()
        tall_pdf = _make_tall_pdf_bytes(width=595.0, height=1684.0)

        annot = _make_device_annotation()
        # _coordinate_context를 tall searchable PDF로 설정
        annot["_coordinate_context"] = _make_context(
            pdf_storage_path=f"{job_id}/searchable.pdf",
            bucket="pdfs",
            width=595.0,
            height=1684.0,
        )
        annotations_json = json.dumps([annot], ensure_ascii=False).encode("utf-8")

        bucket_files = {
            f"results:{job_id}/annotated.annotations.json": annotations_json,
            f"pdfs:{job_id}/original.pdf": original_pdf,
            f"pdfs:{job_id}/searchable.pdf": tall_pdf,
        }
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
            }
        ]

        class MockDb:
            def get(self, model, key):
                if model is Job and key == job_id:
                    return job
                return None

        class FakeStorage:
            def from_(self, bucket: str):
                self._bucket = bucket
                return self

            def download(self, path: str) -> bytes:
                key = f"{self._bucket}:{path}"
                if key in bucket_files:
                    return bucket_files[key]
                raise FileNotFoundError(f"not found: {key}")

            def upload(self, path: str, data: bytes, options: dict | None = None):
                pass

        class FakeClient:
            storage = FakeStorage()

        monkeypatch.setattr("backend.api.jobs.supabase_client.get_service_client", lambda: FakeClient())

        class FakeUser:
            is_dev_bypass = False
            user_id = "test-user"

        response = get_job_result_json(
            job_id=job_id,
            kind="annotations",
            source_index=0,
            page_no=None,
            user=FakeUser(),
            db=MockDb(),
        )

        data = response["data"]
        assert len(data) == 1
        annotation = data[0]["annotation"]
        rect = annotation["rect"]
        # tall 1684pt 기준 device origin.y=22, height=20 -> PDF user origin.y=1642
        assert rect["origin"]["y"] == pytest.approx(1642.0, abs=0.01)
        assert rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        assert rect["size"]["width"] == pytest.approx(100.0, abs=0.01)
        assert rect["size"]["height"] == pytest.approx(20.0, abs=0.01)

    def test_result_json_annotation_has_coordinate_context(self, monkeypatch):
        """get_job_result_json이 _coordinate_context 메타데이터를 유지한다."""
        job_id = "test-job-ctx-preserve"
        job = Job()
        job.id = job_id
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.user_id = "test-user"
        job.created_at = None

        original_pdf = _make_a4_pdf_bytes()
        annot = _make_device_annotation()
        context = _make_context(
            pdf_storage_path=f"{job_id}/searchable.pdf",
            bucket="pdfs",
            width=595.0,
            height=842.0,
        )
        annot["_coordinate_context"] = context
        annotations_json = json.dumps([annot], ensure_ascii=False).encode("utf-8")

        bucket_files = {
            f"results:{job_id}/annotated.annotations.json": annotations_json,
            f"pdfs:{job_id}/original.pdf": original_pdf,
        }
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
            }
        ]

        class MockDb:
            def get(self, model, key):
                if model is Job and key == job_id:
                    return job
                return None

        class FakeStorage:
            def from_(self, bucket: str):
                self._bucket = bucket
                return self

            def download(self, path: str) -> bytes:
                key = f"{self._bucket}:{path}"
                if key in bucket_files:
                    return bucket_files[key]
                raise FileNotFoundError(f"not found: {key}")

            def upload(self, path: str, data: bytes, options: dict | None = None):
                pass

        class FakeClient:
            storage = FakeStorage()

        monkeypatch.setattr("backend.api.jobs.supabase_client.get_service_client", lambda: FakeClient())

        class FakeUser:
            is_dev_bypass = False
            user_id = "test-user"

        response = get_job_result_json(
            job_id=job_id,
            kind="annotations",
            source_index=0,
            page_no=None,
            user=FakeUser(),
            db=MockDb(),
        )

        data = response["data"]
        assert len(data) == 1
        assert data[0].get("_coordinate_context") == context
