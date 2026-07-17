#!/usr/bin/env python3
"""[Flow: Step 1 (pdf_annotate_converter.run 의존성 모킹)
      -> Step 2 (하위 호환 job으로 실행) -> Step 3 (annotated.annotations.json 업로드 및 entry 상태 검증)]

pdf_annotate_converter.run이 하위 호환 job(annotated_pdf_files가 비어 있고
result_annotated_pdf_storage_path만 있는 경우)에서도 entry_found=true를 통과하고
annotated.annotations.json을 Storage에 업로드하는지 검증한다.
"""
import sys
import os
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

# [Flow: app 디렉토리를 sys.path에 추가 -> backend 패키지 루트 임포트 가능]
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
from PIL import Image
import pytest

from backend.db.models import Job


def _make_a4_pdf_bytes() -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> A4 페이지 -> 바이트 반환]"""
    doc = fitz.open()
    doc.new_page(width=595.0, height=842.0)
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


def _make_dummy_png(path: Path, width: int = 1240, height: int = 1754) -> None:
    """[Flow: 단색 PNG 이미지 생성 -> 지정 경로 저장]"""
    img = Image.new("RGB", (width, height), color="white")
    img.save(path)


class MockStorage:
    """[Flow: Supabase Storage 모킹 -> download/upload 호출 기록]"""

    def __init__(self):
        self.uploaded = {}
        self.files = {}

    def from_(self, bucket: str):
        return self

    def download(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(f"Storage path not found: {path}")
        return self.files[path]

    def upload(self, path: str, data: bytes, options: dict | None = None):
        if isinstance(data, bytes):
            self.uploaded[path] = data
        else:
            self.uploaded[path] = data


def _make_mock_db(job: Job):
    """[Flow: SQLAlchemy session 모킹 -> job 반환 및 commit/close 무효화]"""
    db = MagicMock()

    def _get(model, key):
        return job if model is Job and key == job.id else None

    db.get.side_effect = _get

    class ScalarOneResult:
        def scalar_one(self):
            return job

    db.execute.return_value = ScalarOneResult()
    return db


class TestPdfAnnotateConverterRunBackwardCompat:
    """하위 호환 job에서 pdf_annotate_converter.run이 정상 완료한다."""

    def test_run_uploads_annotations_json_and_marks_done(self, tmp_path, monkeypatch):
        # [Flow: Job 인스턴스 생성 -> 하위 호환 상태 설정]
        job = Job()
        job.id = "test-job-abc"
        job.searchable_pdf_storage_path = "searchable.pdf"
        job.result_annotated_pdf_storage_path = f"{job.id}/annotated.pdf"
        job.annotated_pdf_files = []
        job.annotate_instruction = "test instruction"
        job.annotate_mode = "highlight"
        job.annotate_comment_mode = "llm_summary"
        job.endpoint = None
        job.model = None

        db = _make_mock_db(job)

        # [Flow: 의존성 모킹]
        mock_storage = MockStorage()
        mock_client = MagicMock()
        mock_client.storage = mock_storage

        # searchable PDF 다운로드 -> A4 PDF
        def _download_pdf(path: str):
            return io.BytesIO(_make_a4_pdf_bytes())

        def _render_pdf(input_path: str, output_dir: str, dpi: int = 300):
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            _make_dummy_png(out_dir / "page-1.png")

        def _settings_get(db, key: str):
            defaults = {
                "llm_endpoint": "http://test-llm",
                "llm_model": "test-model",
                "llm_api_key": "test-key",
            }
            return defaults.get(key, "")

        import backend.core.pdf_annotate_converter as pac
        from backend.core.pdf_annotator import AnnotationTarget

        monkeypatch.setattr(pac, "SessionLocal", lambda: db)
        monkeypatch.setattr(pac.supabase_client, "download_pdf", _download_pdf)
        monkeypatch.setattr(pac.supabase_client, "get_service_client", lambda: mock_client)
        monkeypatch.setattr(pac.ocr_client, "render_pdf", _render_pdf)
        monkeypatch.setattr(pac.settings_store, "get_setting", _settings_get)
        monkeypatch.setattr(pac, "flag_modified", lambda *args, **kwargs: None)
        monkeypatch.setattr(pac.cache, "invalidate_pattern", lambda *args, **kwargs: None)

        # Vision LLM 경로를 모킹: AnnotationTarget 1개 반환
        def _collect_targets_with_vision_llm(*args, **kwargs):
            return [
                AnnotationTarget(
                    page_no=1,
                    bbox_pdf=(100.0, 700.0, 200.0, 720.0),
                    comment="AI 주석",
                )
            ], "highlight", "llm_summary"

        monkeypatch.setattr(pac, "_collect_targets_with_vision_llm", _collect_targets_with_vision_llm)

        # [Flow: run 실행 -> 결과 검증]
        result = pac.run(
            job_id=job.id,
            instruction="test instruction",
            mode="highlight",
            comment_mode="llm_summary",
            language="ko",
            advanced=True,
            annotation_index=1,
            page_range=None,
        )

        assert result["status"] == "done"
        assert result["matched_rows"] == 1

        # [Flow: Storage 업로드 검증 -> annotated.annotations.json 존재 여부 및 내용 확인]
        json_path = f"{job.id}/annotated.annotations.json"
        assert json_path in mock_storage.uploaded, f"{json_path} not uploaded. uploaded keys: {list(mock_storage.uploaded.keys())}"
        uploaded_json = json.loads(mock_storage.uploaded[json_path])
        assert isinstance(uploaded_json, list)
        assert len(uploaded_json) == 1
        ann = uploaded_json[0]["annotation"]
        assert ann["type"] == 9
        assert ann["contents"] == "AI 주석"

        # [Flow: DB entry 상태 검증 -> index=1인 entry가 done이고 annotations_json_storage_path 설정]
        assert job.annotated_pdf_files is not None
        assert len(job.annotated_pdf_files) == 1
        entry = job.annotated_pdf_files[0]
        assert entry["index"] == 1
        assert entry["status"] == "done"
        assert entry["storage_path"] == f"{job.id}/annotated.pdf"
        assert entry["annotations_json_storage_path"] == json_path


def _make_searchable_pdf_with_duplicate_text() -> bytes:
    """[Flow: PyMuPDF 문서 생성 -> 동일한 텍스트를 2회 삽입 -> 바이트 반환]"""
    doc = fitz.open()
    page = doc.new_page(width=595.0, height=842.0)
    page.insert_text((100, 750), "CONFIDENTIAL")
    page.insert_text((100, 700), "CONFIDENTIAL")
    stream = io.BytesIO()
    doc.save(stream)
    doc.close()
    return stream.getvalue()


class TestPdfAnnotateConverterSearchableTextPipeline:
    """searchable PDF가 있을 때 LLM이 text만 반환하면 모든 발생 위치를 highlight한다."""

    def test_run_searchable_pdf_highlight_all_occurrences(self, tmp_path, monkeypatch):
        # [Flow: Job 인스턴스 생성 -> searchable PDF 설정]
        job = Job()
        job.id = "test-job-searchable"
        job.searchable_pdf_storage_path = "searchable.pdf"
        job.annotated_pdf_files = [
            {
                "index": 1,
                "status": "processing",
                "storage_path": "",
                "annotations_json_storage_path": "",
            }
        ]
        job.annotate_instruction = "highlight confidential"
        job.annotate_mode = "highlight"
        job.annotate_comment_mode = "llm_summary"
        job.endpoint = None
        job.model = None

        db = _make_mock_db(job)

        # [Flow: 의존성 모킹]
        mock_storage = MockStorage()
        mock_client = MagicMock()
        mock_client.storage = mock_storage

        searchable_pdf_bytes = _make_searchable_pdf_with_duplicate_text()

        def _download_pdf(path: str):
            return io.BytesIO(searchable_pdf_bytes)

        def _render_pdf(input_path: str, output_dir: str, dpi: int = 300):
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            _make_dummy_png(out_dir / "page-1.png")
            return {1: out_dir / "page-1.png"}

        def _settings_get(db, key: str):
            defaults = {
                "llm_endpoint": "http://test-llm",
                "llm_model": "test-model",
                "llm_api_key": "test-key",
            }
            return defaults.get(key, "")

        import backend.core.pdf_annotate_converter as pac

        monkeypatch.setattr(pac, "SessionLocal", lambda: db)
        monkeypatch.setattr(pac.supabase_client, "download_pdf", _download_pdf)
        monkeypatch.setattr(pac.supabase_client, "get_service_client", lambda: mock_client)
        monkeypatch.setattr(pac, "_render_pdf_to_image_paths", _render_pdf)
        monkeypatch.setattr(pac.settings_store, "get_setting", _settings_get)
        monkeypatch.setattr(pac, "flag_modified", lambda *args, **kwargs: None)
        monkeypatch.setattr(pac.cache, "invalidate_pattern", lambda *args, **kwargs: None)

        # [Flow: LLM이 text만 반환하도록 모킹]
        def _call_text(prompt, endpoint, model, api_key, max_tokens=None):
            return (
                '{"mode": "highlight", "comment_mode": "llm_summary", "matches": ['
                '{"text": "CONFIDENTIAL", "comment": "secret", "color": "red", "opacity": 0.5}'
                ']}'
            ), None

        monkeypatch.setattr(pac.ocr_client, "call_text", _call_text)

        # [Flow: run 실행 -> 검증]
        result = pac.run(
            job_id=job.id,
            instruction="highlight confidential",
            mode="highlight",
            comment_mode="llm_summary",
            language="en",
            advanced=False,
            annotation_index=1,
            page_range=None,
        )

        assert result["status"] == "done"

        json_path = f"{job.id}/annotated.annotations.json"
        assert json_path in mock_storage.uploaded
        uploaded_json = json.loads(mock_storage.uploaded[json_path])
        assert isinstance(uploaded_json, list)
        assert len(uploaded_json) == 1
        ann = uploaded_json[0]["annotation"]
        assert ann["type"] == 9
        # 같은 텍스트가 한 페이지에 2회 있으므로 segmentRects가 2개여야 한다.
        assert "segmentRects" in ann
        assert len(ann["segmentRects"]) == 2
        assert ann["custom"] == {"searchText": "CONFIDENTIAL"}
        # bounding rect는 두 세그먼트를 모두 감싸므로, 세그먼트 하나보다 높이가 커야 한다.
        assert ann["rect"]["size"]["height"] > ann["segmentRects"][0]["size"]["height"]
