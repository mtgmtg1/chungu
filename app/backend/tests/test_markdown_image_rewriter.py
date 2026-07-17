#!/usr/bin/env python3
# [Flow: Step 1 (mock Supabase client 준비) -> Step 2 (base64 이미지 포함 마크다운 입력)
#       -> Step 3 (rewrite_inline_images_to_storage 호출) -> Step 4 (proxy URL 치환 및 업로드 데이터 검증)]
"""markdown_image_rewriter.py의 base64 이미지 Storage 외부화 기능을 테스트한다."""
import base64
import hashlib
import io
import sys
import os

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PILImage

from backend.core.markdown_image_rewriter import rewrite_inline_images_to_storage


def _make_small_base64_png() -> str:
    """1x1 픽셀 PNG를 base64 data URI로 반환한다."""
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _expected_storage_path(image_bytes: bytes, job_id: str, ext: str) -> str:
    """rewriter가 생성할 storage_path를 예상한다."""
    content_hash = hashlib.md5(image_bytes).hexdigest()[:16]
    return f"{job_id}/images/{content_hash}.{ext}"


def _make_mock_supabase_client():
    """업로드된 내용을 기록하는 mock Supabase Storage client를 만든다."""
    uploaded: dict[str, bytes] = {}

    def _upload(path, data, _opts=None):
        uploaded[path] = data
        return {"path": path}

    mock_bucket = MagicMock()
    mock_bucket.upload.side_effect = _upload

    mock_storage = MagicMock()
    mock_storage.from_.return_value = mock_bucket

    mock_client = MagicMock()
    mock_client.storage = mock_storage

    return mock_client, uploaded


class TestRewriteInlineImagesToStorage:
    """마크다운 내 base64 이미지를 Supabase Storage에 업로드하고 proxy URL로 치환하는 테스트."""

    def test_html_img_base64_replaced_with_proxy_url(self, monkeypatch):
        """<img src=\"data:image...\">를 /api/jobs/{job_id}/ocr-images/{storage_path}로 치환한다."""
        mock_client, uploaded = _make_mock_supabase_client()
        monkeypatch.setattr(
            "backend.core.markdown_image_rewriter.supabase_client.get_service_client",
            lambda: mock_client,
        )

        b64_uri = _make_small_base64_png()
        image_bytes = base64.b64decode(b64_uri.split(",")[-1])
        job_id = "job-abc-123"
        markdown = f'문서\n\n<img src="{b64_uri}" alt="테스트">\n\n끝'

        result = rewrite_inline_images_to_storage(markdown, job_id)

        expected_path = _expected_storage_path(image_bytes, job_id, "png")
        expected_url = f"/api/jobs/{job_id}/ocr-images/{expected_path}"

        assert expected_url in result
        assert "data:image" not in result
        assert uploaded.get(expected_path) == image_bytes
        assert "문서" in result
        assert "끝" in result

    def test_markdown_img_base64_replaced_with_proxy_url(self, monkeypatch):
        """![alt](data:image...)를 ![alt](/api/...)로 치환한다."""
        mock_client, uploaded = _make_mock_supabase_client()
        monkeypatch.setattr(
            "backend.core.markdown_image_rewriter.supabase_client.get_service_client",
            lambda: mock_client,
        )

        b64_uri = _make_small_base64_png()
        image_bytes = base64.b64decode(b64_uri.split(",")[-1])
        job_id = "job-abc-123"
        markdown = f'![테스트 이미지]({b64_uri})'

        result = rewrite_inline_images_to_storage(markdown, job_id)

        expected_path = _expected_storage_path(image_bytes, job_id, "png")
        expected_url = f"/api/jobs/{job_id}/ocr-images/{expected_path}"

        assert expected_url in result
        assert "data:image" not in result
        assert uploaded.get(expected_path) == image_bytes

    def test_multiple_images_replaced(self, monkeypatch):
        """여러 base64 이미지가 각각 업로드되고 모두 치환된다."""
        mock_client, uploaded = _make_mock_supabase_client()
        monkeypatch.setattr(
            "backend.core.markdown_image_rewriter.supabase_client.get_service_client",
            lambda: mock_client,
        )

        png_uri = _make_small_base64_png()
        png_bytes = base64.b64decode(png_uri.split(",")[-1])

        img2 = PILImage.new("RGB", (1, 1), color=(0, 255, 0))
        buf2 = io.BytesIO()
        img2.save(buf2, format="PNG")
        png2_uri = f"data:image/png;base64,{base64.b64encode(buf2.getvalue()).decode('ascii')}"
        png2_bytes = buf2.getvalue()

        job_id = "job-multi"
        markdown = f'{png_uri}\n\n![alt]({png2_uri})\n\n<img src="{png_uri}">'

        result = rewrite_inline_images_to_storage(markdown, job_id)

        assert result.count("data:image") == 0
        assert result.count("/api/jobs/job-multi/ocr-images/") == 3
        assert len(uploaded) == 2
        assert uploaded[_expected_storage_path(png_bytes, job_id, "png")] == png_bytes
        assert uploaded[_expected_storage_path(png2_bytes, job_id, "png")] == png2_bytes

    def test_no_images_unchanged(self, monkeypatch):
        """base64 이미지가 없으면 입력이 그대로 반환되고 업로드가 일어나지 않는다."""
        mock_client, uploaded = _make_mock_supabase_client()
        monkeypatch.setattr(
            "backend.core.markdown_image_rewriter.supabase_client.get_service_client",
            lambda: mock_client,
        )

        markdown = "# 제목\n\n일반 텍스트\n\n| a | b |\n| 1 | 2 |"
        result = rewrite_inline_images_to_storage(markdown, "job-noimg")

        assert result == markdown
        assert len(uploaded) == 0

    def test_normal_image_url_unchanged(self, monkeypatch):
        """일반 http(s) 또는 proxy URL 이미지는 업로드하지 않고 그대로 둔다."""
        mock_client, uploaded = _make_mock_supabase_client()
        monkeypatch.setattr(
            "backend.core.markdown_image_rewriter.supabase_client.get_service_client",
            lambda: mock_client,
        )

        markdown = '![external](https://example.com/img.png)\n\n<img src="/api/jobs/job-x/ocr-images/job-x/images/abc.png">'
        result = rewrite_inline_images_to_storage(markdown, "job-normal")

        assert result == markdown
        assert len(uploaded) == 0

    def test_upload_failure_falls_back_to_placeholder(self, monkeypatch):
        """Storage 업로드 실패 시 base64를 placeholder로 치환하여 prompt를 깨끗이 유지한다."""
        mock_bucket = MagicMock()
        mock_bucket.upload.side_effect = Exception("storage error")

        mock_storage = MagicMock()
        mock_storage.from_.return_value = mock_bucket

        mock_client = MagicMock()
        mock_client.storage = mock_storage

        monkeypatch.setattr(
            "backend.core.markdown_image_rewriter.supabase_client.get_service_client",
            lambda: mock_client,
        )

        b64_uri = _make_small_base64_png()
        markdown = f'<img src="{b64_uri}" alt="테스트">'
        result = rewrite_inline_images_to_storage(markdown, "job-fail")

        assert "data:image" not in result
        assert "[image]" in result
