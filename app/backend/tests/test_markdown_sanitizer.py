#!/usr/bin/env python3
# [Flow: Step 1 (base64 이미지 포함 마크다운 샘플 생성) -> Step 2 (sanitize_markdown_for_llm 호출)
#       -> Step 3 (base64 제거 및 텍스트 보존 검증)]
"""markdown_sanitizer.py의 data:image base64 제거 기능을 테스트한다."""
import base64
import io
import sys
import os

# [Flow: backend 패키지 루트를 sys.path에 추가]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".."))

import pytest
from PIL import Image as PILImage

from backend.core.markdown_sanitizer import sanitize_markdown_for_llm


def _make_small_base64_png() -> str:
    """1x1 픽셀 PNG를 base64 data URI로 반환한다."""
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _make_small_base64_jpeg() -> str:
    """1x1 픽셀 JPEG를 base64 data URI로 반환한다."""
    img = PILImage.new("RGB", (1, 1), color=(0, 255, 0))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


class TestSanitizeMarkdownForLLM:
    """LLM prompt용 마크다운에서 base64 인라인 이미지를 제거하는 테스트."""

    def test_removes_html_img_with_base64_double_quote(self):
        """src="data:image..." 형태의 HTML 이미지 태그를 placeholder로 치환한다."""
        b64_uri = _make_small_base64_png()
        markdown = f'문서 내용\n\n<img src="{b64_uri}" alt="테스트">\n\n뒷내용'
        result = sanitize_markdown_for_llm(markdown)

        assert "data:image" not in result
        assert b64_uri not in result
        assert "[image]" in result
        assert "문서 내용" in result
        assert "뒷내용" in result

    def test_removes_html_img_with_base64_single_quote(self):
        """src='data:image...' 형태의 HTML 이미지 태그도 처리한다."""
        b64_uri = _make_small_base64_png()
        markdown = f"<img src='{b64_uri}' alt='테스트'>"
        result = sanitize_markdown_for_llm(markdown)

        assert "data:image" not in result
        assert "[image]" in result

    def test_removes_markdown_img_with_base64(self):
        """![alt](data:image...) 형태의 마크다운 이미지를 placeholder로 치환한다."""
        b64_uri = _make_small_base64_png()
        markdown = f'![테스트 이미지]({b64_uri})'
        result = sanitize_markdown_for_llm(markdown)

        assert "data:image" not in result
        assert b64_uri not in result
        assert "[image]" in result
        assert "![테스트 이미지]" in result or "[image]" in result

    def test_removes_multiple_base64_images(self):
        """여러 개의 base64 이미지를 모두 제거한다."""
        png_uri = _make_small_base64_png()
        jpeg_uri = _make_small_base64_jpeg()
        markdown = f"{png_uri}\n\n![alt]({jpeg_uri})\n\n<img src=\"{png_uri}\">"
        result = sanitize_markdown_for_llm(markdown)

        assert result.count("data:image") == 0
        assert result.count("[image]") >= 2

    def test_leaves_normal_urls_unchanged(self):
        """일반 http(s) 이미지 URL은 변경하지 않는다."""
        markdown = '![external](https://example.com/img.png)\n\n<img src="/api/jobs/123/ocr-images/results/123/images/abc.png">'
        result = sanitize_markdown_for_llm(markdown)

        assert "https://example.com/img.png" in result
        assert "/api/jobs/123/ocr-images/results/123/images/abc.png" in result
        assert result == markdown

    def test_preserves_tables_and_page_markers(self):
        """표와 페이지 마커는 그대로 유지한다."""
        b64_uri = _make_small_base64_png()
        markdown = (
            "<!-- Page 1 -->\n\n"
            "| 이름 | 나이 |\n| --- | --- |\n| 홍길동 | 25 |\n\n"
            f'<img src="{b64_uri}">'
        )
        result = sanitize_markdown_for_llm(markdown)

        assert "<!-- Page 1 -->" in result
        assert "| 이름 | 나이 |" in result
        assert "홍길동" in result
        assert "data:image" not in result

    def test_empty_string_returns_empty(self):
        """빈 문자열은 빈 문자열을 반환한다."""
        assert sanitize_markdown_for_llm("") == ""

    def test_no_base64_unchanged(self):
        """base64 이미지가 없으면 입력이 그대로 반환된다."""
        markdown = "# 제목\n\n일반 텍스트\n\n| a | b |\n| 1 | 2 |"
        assert sanitize_markdown_for_llm(markdown) == markdown

    def test_custom_placeholder(self):
        """placeholder 인자를 사용자 정의할 수 있다."""
        b64_uri = _make_small_base64_png()
        markdown = f'<img src="{b64_uri}">'
        result = sanitize_markdown_for_llm(markdown, placeholder="[IMAGE_PLACEHOLDER]")

        assert "[IMAGE_PLACEHOLDER]" in result
