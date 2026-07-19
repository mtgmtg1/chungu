#!/usr/bin/env python3
"""[Flow: Step 1 (가상 Job + 원본/searchable PDF + 주석 payload 모킹)
      -> Step 2 (save_user_annotations 호출)
      -> Step 3 (저장된 JSON의 _coordinate_context 및 좌표 검증)
      -> Step 4 (get_job_annotations로 역변환 round-trip 검증)]

save_user_annotations가 source_index에 따라 올바른 PDF를 좌표 변환 기준으로 사용하고,
 Coordinate_context 메타데이터를 주석 JSON에 저장하는지 검증한다.
searchable PDF와 원본 PDF의 페이지 높이가 다를 때도 y축이 반전되지 않아야 한다.
"""
import sys
import os
import io
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
import pytest

from backend.api.jobs import save_user_annotations, get_job_annotations
from backend.db.models import Job


def _make_pdf_bytes(width: float, height: float) -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> 지정 크기 페이지 -> 바이트 반환]"""
    doc = fitz.open()
    doc.new_page(width=width, height=height)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def _make_pdf_user_annotation(y0: float, y1: float) -> dict:
    """[Flow: PDF user-space rect 생성 -> AnnotationTransferItem 형태 반환]"""
    return {
        "annotation": {
            "id": "backend-1-0-highlight",
            "type": 9,
            "pageIndex": 0,
            "rect": {"origin": {"x": 100.0, "y": y0}, "size": {"width": 100.0, "height": y1 - y0}},
            "segmentRects": [{"origin": {"x": 100.0, "y": y0}, "size": {"width": 100.0, "height": y1 - y0}}],
            "strokeColor": "#FFEB3B",
            "color": "#FFEB3B",
            "opacity": 0.5,
            "contents": "test",
        }
    }


def _make_mock_db(job: Job):
    """[Flow: Job 인스턴스를 반환하는 최소 DB mock 생성]"""
    class MockDb:
        def get(self, model, key):
            if model is Job and key == job.id:
                return job
            return None

        def execute(self, stmt, *args, **kwargs):
            return SimpleNamespace(scalar_one=lambda: job)

        def commit(self):
            pass

        def rollback(self):
            pass

    return MockDb()


def _make_mock_storage(files: dict):
    """[Flow: 경로→bytes dict로 Storage mock 생성 -> upload 시 dict 갱신]"""

    class FakeBucket:
        def download(self, path: str) -> bytes:
            key = f"{self._bucket}:{path}"
            if key in files:
                return files[key]
            raise FileNotFoundError(f"not found: {key}")

        def upload(self, path: str, data: bytes, options: dict | None = None):
            key = f"{self._bucket}:{path}"
            files[key] = data

    class FakeStorage:
        def from_(self, bucket: str):
            self._bucket = bucket
            return self

        def download(self, path: str) -> bytes:
            key = f"{self._bucket}:{path}"
            if key in files:
                return files[key]
            raise FileNotFoundError(f"not found: {key}")

        def upload(self, path: str, data: bytes, options: dict | None = None):
            key = f"{self._bucket}:{path}"
            files[key] = data

    return FakeStorage()


class TestSaveUserAnnotationsMetadata:
    """save_user_annotations 좌표계 컨텍스트 메타데이터 검증."""

    def test_save_attaches_coordinate_context_and_round_trips(self, monkeypatch):
        """searchable PDF가 원본보다 클 때, pdf_user 저장 후 get 조회가 y를 반전시키지 않는다."""
        job_id = "test-save-ctx"
        original_pdf = _make_pdf_bytes(595.0, 842.0)
        tall_pdf = _make_pdf_bytes(595.0, 1684.0)

        job = Job()
        job.id = job_id
        job.user_id = "test-user"
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.searchable_pdf_storage_path = f"{job_id}/searchable.pdf"
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
            }
        ]

        files = {
            f"pdfs:{job_id}/original.pdf": original_pdf,
            f"pdfs:{job_id}/searchable.pdf": tall_pdf,
        }

        monkeypatch.setattr("backend.api.jobs.cache.invalidate_pattern", lambda *a, **k: None)
        monkeypatch.setattr(
            "backend.api.jobs.supabase_client.get_service_client",
            lambda: SimpleNamespace(storage=_make_mock_storage(files)),
        )

        class FakeUser:
            is_dev_bypass = True
            user_id = "admin"

        # tall searchable PDF 기준 PDF user-space: 상단 영역 y0=1642, y1=1662
        pdf_user_annot = _make_pdf_user_annotation(1642.0, 1662.0)
        payload = {
            "source_index": 1,
            "annotations": [pdf_user_annot],
            "input_space": "pdf_user",
        }

        response = save_user_annotations(
            job_id=job_id,
            payload=payload,
            user=FakeUser(),
            db=_make_mock_db(job),
        )

        assert response["ok"] is True
        assert response["annotations_json_storage_path"] == f"{job_id}/annotated.annotations.json"

        # 저장된 JSON 확인
        saved_bytes = files[f"results:{job_id}/annotated.annotations.json"]
        saved = json.loads(saved_bytes.decode("utf-8"))
        assert len(saved) == 1
        item = saved[0]
        context = item.get("_coordinate_context")
        assert context is not None
        assert context["pdf_storage_path"] == f"{job_id}/searchable.pdf"
        assert context["bucket"] == "pdfs"
        assert context["input_space"] == "device"
        assert context["page_dimensions"]["1"]["height"] == 1684.0

        # device-space로 변환되었는지 확인: tall PDF에서 origin.y = 1684 - 1662 = 22
        rect = item["annotation"]["rect"]
        assert rect["origin"]["y"] == pytest.approx(22.0, abs=0.01)
        assert rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        assert rect["size"]["height"] == pytest.approx(20.0, abs=0.01)

        # get_job_annotations로 다시 PDF user-space를 받을 때 원래 좌표로 복원
        response_get = get_job_annotations(
            job_id=job_id,
            source_index=1,
            page_no=None,
            user=FakeUser(),
            db=_make_mock_db(job),
        )
        data = response_get["annotations"]
        assert len(data) == 1
        pdf_rect = data[0]["annotation"]["rect"]
        assert pdf_rect["origin"]["y"] == pytest.approx(1642.0, abs=0.01)
        assert pdf_rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
        assert pdf_rect["size"]["height"] == pytest.approx(20.0, abs=0.01)

    def test_save_without_context_fallback_to_original_pdf(self, monkeypatch):
        """_coordinate_context가 없는 기존 JSON은 job.pdf_storage_path로 폴백한다."""
        job_id = "test-save-fallback"
        original_pdf = _make_pdf_bytes(595.0, 842.0)

        job = Job()
        job.id = job_id
        job.user_id = "test-user"
        job.pdf_storage_path = f"{job_id}/original.pdf"
        job.searchable_pdf_storage_path = f"{job_id}/searchable.pdf"
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "done",
                "storage_path": f"{job_id}/searchable.pdf",
                "annotations_json_storage_path": f"{job_id}/annotated.annotations.json",
            }
        ]

        # _coordinate_context가 없는 device-space 주석 (A4 기준)
        device_annot = {
            "annotation": {
                "id": "legacy-1",
                "type": 9,
                "pageIndex": 0,
                "rect": {"origin": {"x": 100.0, "y": 22.0}, "size": {"width": 100.0, "height": 20.0}},
                "segmentRects": [{"origin": {"x": 100.0, "y": 22.0}, "size": {"width": 100.0, "height": 20.0}}],
                "strokeColor": "#FFEB3B",
                "color": "#FFEB3B",
                "opacity": 0.5,
                "contents": "legacy",
            }
        }
        annotations_json = json.dumps([device_annot], ensure_ascii=False).encode("utf-8")

        files = {
            f"pdfs:{job_id}/original.pdf": original_pdf,
            f"results:{job_id}/annotated.annotations.json": annotations_json,
        }

        monkeypatch.setattr("backend.api.jobs.cache.invalidate_pattern", lambda *a, **k: None)
        monkeypatch.setattr(
            "backend.api.jobs.supabase_client.get_service_client",
            lambda: SimpleNamespace(storage=_make_mock_storage(files)),
        )

        class FakeUser:
            is_dev_bypass = True
            user_id = "admin"

        response = get_job_annotations(
            job_id=job_id,
            source_index=0,
            page_no=None,
            user=FakeUser(),
            db=_make_mock_db(job),
        )

        data = response["annotations"]
        assert len(data) == 1
        rect = data[0]["annotation"]["rect"]
        # 원본 A4 842pt 기준 device origin.y=22, height=20 -> PDF user y0=800
        assert rect["origin"]["y"] == pytest.approx(800.0, abs=0.01)
        assert rect["origin"]["x"] == pytest.approx(100.0, abs=0.01)
