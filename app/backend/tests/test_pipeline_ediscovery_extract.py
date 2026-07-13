#!/usr/bin/env python3
"""[Flow: Step 1 (필요한 모듈 import) -> Step 2 (Job mock 생성)
      -> Step 3 (extract_page_texts/_extract_all_source_files 시나리오 테스트)]

e-Discovery 파이프라인이 job에 속한 모든 자료를 페이지 단위로 추출하는지 검증한다.
"""
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from backend.core.pipeline_ediscovery import (
    _build_extraction_prompt,
    _extract_all_source_files,
    extract_page_texts,
)
from backend.db.models import Job


def _make_job(extracted_files=None, pdf_storage_path="", searchable_pdf_storage_path=""):
    """테스트용 Job mock 객체를 생성한다.

    매개변수:
        extracted_files: extracted_files JSONB 리스트
        pdf_storage_path: 단일 파일 폴백 경로
        searchable_pdf_storage_path: 단일 파일 searchable PDF 경로
    반환값: MagicMock Job 객체
    """
    job = MagicMock()
    job.extracted_files = extracted_files or []
    job.pdf_storage_path = pdf_storage_path
    job.searchable_pdf_storage_path = searchable_pdf_storage_path
    job.result_edited_md_storage_path = ""
    job.result_md_storage_path = ""
    return job


def test_extract_all_source_files_combines_multiple_pdfs():
    """extracted_files에 여러 PDF가 있으면 전역 페이지 번호로 통합한다."""
    job = _make_job(extracted_files=[
        {"type": "pdf", "path": "1.a.pdf", "storage_path": "pdfs/1.a.pdf"},
        {"type": "pdf", "path": "1.b.pdf", "storage_path": "pdfs/1.b.pdf"},
    ])

    def fake_extract(info: dict, passed_job: Job) -> dict:
        path = info.get("path", "")
        if "1.a.pdf" in path:
            return {1: "a 페이지1", 2: "a 페이지2"}
        if "1.b.pdf" in path:
            return {1: "b 페이지1"}
        return {}

    with patch(
        "backend.core.pipeline_ediscovery._extract_page_texts_from_source_file",
        side_effect=fake_extract,
    ):
        result, page_meta = _extract_all_source_files(job)

    assert len(result) == 3
    assert result[1].startswith("[출처: 1.a.pdf 원본 1페이지]")
    assert "a 페이지1" in result[1]
    assert result[2].startswith("[출처: 1.a.pdf 원본 2페이지]")
    assert result[3].startswith("[출처: 1.b.pdf 원본 1페이지]")
    assert page_meta[1] == {"source_file": "1.a.pdf", "original_page": 1}
    assert page_meta[2] == {"source_file": "1.a.pdf", "original_page": 2}
    assert page_meta[3] == {"source_file": "1.b.pdf", "original_page": 1}


def test_extract_page_texts_prefers_extracted_files():
    """extracted_files가 있으면 단일 PDF 폴백을 무시하고 전체 소스 파일을 사용한다."""
    job = _make_job(
        extracted_files=[{"type": "pdf", "path": "evidence.pdf", "storage_path": "pdfs/evidence.pdf"}],
        pdf_storage_path="pdfs/job.zip",
    )

    with patch(
        "backend.core.pipeline_ediscovery._extract_all_source_files",
        return_value=({1: "combined"}, {1: {"source_file": "evidence.pdf", "original_page": 1}}),
    ) as mock_all, patch("backend.core.pipeline_ediscovery._download_pdf_bytes") as mock_download:
        result, page_meta = extract_page_texts(job)

    assert result == {1: "combined"}
    assert page_meta[1] == {"source_file": "evidence.pdf", "original_page": 1}
    mock_all.assert_called_once_with(job)
    mock_download.assert_not_called()


def test_extract_page_texts_fallback_to_main_pdf():
    """extracted_files가 비어 있으면 기존 단일 PDF 경로를 사용한다."""
    job = _make_job(pdf_storage_path="pdfs/job.pdf")

    with patch(
        "backend.core.pipeline_ediscovery._download_pdf_bytes",
        return_value=b"pdfbytes",
    ), patch(
        "backend.core.pipeline_ediscovery._extract_page_texts_from_pdf",
        return_value={1: "page1", 2: "page2"},
    ):
        result, page_meta = extract_page_texts(job)

    assert result == {1: "page1", 2: "page2"}
    assert page_meta[1] == {"source_file": "job.pdf", "original_page": 1}
    assert page_meta[2] == {"source_file": "job.pdf", "original_page": 2}


def test_extract_all_source_files_skips_empty_and_media():
    """비어 있는 PDF와 오디오/비디오 파일은 제외하고 추출한다."""
    job = _make_job(extracted_files=[
        {"type": "pdf", "path": "empty.pdf", "storage_path": "pdfs/empty.pdf"},
        {"type": "audio", "path": "recording.mp3", "storage_path": "pdfs/recording.mp3"},
        {"type": "pdf", "path": "content.pdf", "storage_path": "pdfs/content.pdf"},
    ])

    def fake_extract(info: dict, passed_job: Job) -> dict:
        if info.get("path") == "content.pdf":
            return {1: "content"}
        return {}

    with patch(
        "backend.core.pipeline_ediscovery._extract_page_texts_from_source_file",
        side_effect=fake_extract,
    ):
        result, page_meta = _extract_all_source_files(job)

    assert len(result) == 1
    assert "content.pdf" in result[1]
    assert page_meta[1] == {"source_file": "content.pdf", "original_page": 1}


def test_extract_all_source_files_uses_markdown_fallback():
    """PDF 추출이 비어 있으면 result_markdown 폴백을 사용한다."""
    job = _make_job(extracted_files=[
        {
            "type": "file",
            "path": "scan.md",
            "storage_path": "pdfs/scan.pdf",
            "result_markdown": "results/scan.md",
        },
    ])

    with patch(
        "backend.core.pipeline_ediscovery._extract_page_texts_from_source_file",
        return_value={1: "markdown page 1", 2: "markdown page 2"},
    ):
        result, page_meta = _extract_all_source_files(job)

    assert len(result) == 2
    assert "markdown page 1" in result[1]
    assert page_meta[1] == {"source_file": "scan.md", "original_page": 1}


def test_extract_page_texts_resolves_folder_upload_without_storage_path():
    """extracted_files 항목에 storage_path가 없고 pdf_storage_path가 폴더일 때
    pdfs/{job.id}/{path} 또는 pdf_storage_path 폴더에서 파일을 찾는다."""
    job = _make_job(
        extracted_files=[{"type": "pdf", "path": "evidence.pdf"}],
        pdf_storage_path="pdfs/job-123/",
    )
    job.id = "job-123"

    downloaded_paths: list[tuple[str, str]] = []

    def fake_download_storage_bytes(bucket: str, path: str) -> bytes | None:
        downloaded_paths.append((bucket, path))
        if path == "pdfs/job-123/evidence.pdf":
            return b"pdfbytes"
        return None

    with patch(
        "backend.core.pipeline_ediscovery._download_storage_bytes",
        side_effect=fake_download_storage_bytes,
    ), patch(
        "backend.core.pipeline_ediscovery._extract_page_texts_from_pdf",
        return_value={1: "page from folder"},
    ):
        result, page_meta = extract_page_texts(job)

    assert result == {1: "[출처: evidence.pdf 원본 1페이지]\npage from folder"}
    assert page_meta[1] == {"source_file": "evidence.pdf", "original_page": 1}
    assert ("pdfs", "pdfs/job-123/evidence.pdf") in downloaded_paths


def test_build_extraction_prompt_includes_context():
    """_build_extraction_prompt에 context가 주어지면 프롬프트에 추가 맥락 섹션을 포함한다."""
    chunk_text = "2023년 4월 5일 A가 B에게 1천만 원을 대여했다."
    context = "대여금 반환 청구 사건, A가 채권자, B가 채무자"
    prompt = _build_extraction_prompt(chunk_text, page_no=1, context=context)
    assert context in prompt
    assert "추가 맥락" in prompt


def test_build_extraction_prompt_without_context():
    """_build_extraction_prompt에 context가 없으면 추가 맥락 섹션을 포함하지 않는다."""
    chunk_text = "2023년 4월 5일 A가 B에게 1천만 원을 대여했다."
    prompt = _build_extraction_prompt(chunk_text, page_no=1)
    assert "추가 맥락" not in prompt
