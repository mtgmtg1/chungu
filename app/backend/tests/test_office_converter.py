#!/usr/bin/env python3
# [Flow: Step 1 (테스트 케이스 정의) -> Step 2 (변환 실행) -> Step 3 (결과 검증)]
"""office_converter.py의 HTML→DOCX/PPTX 변환 및 순수 마크다운 변환을 테스트한다."""
import base64
import io
import re
import zipfile
from pathlib import Path

import pytest
from PIL import Image as PILImage

from core.office_converter import (
    _contains_html,
    markdown_to_docx,
    markdown_to_pptx,
)


# ---------------------------------------------------------------------------
# 헬퍼 함수
# ---------------------------------------------------------------------------

def _make_small_base64_png() -> str:
    """1x1 픽셀 PNG를 base64 data URI로 반환한다."""
    img = PILImage.new("RGB", (1, 1), color=(255, 0, 0))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _extract_docx_text(path: Path) -> str:
    """DOCX 파일에서 모든 w:t 텍스트를 추출한다."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", xml))


def _docx_has_table(path: Path) -> bool:
    """DOCX 파일에 표가 포함되어 있는지 확인한다."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml").decode("utf-8")
    return "<w:tbl>" in xml


def _docx_media_files(path: Path) -> list[str]:
    """DOCX 파일에 포함된 미디어 파일 목록을 반환한다."""
    with zipfile.ZipFile(path) as z:
        return [n for n in z.namelist() if n.startswith("word/media/")]


# ---------------------------------------------------------------------------
# _contains_html 테스트
# ---------------------------------------------------------------------------

class TestContainsHtml:
    """HTML 태그 감지 함수 테스트."""

    def test_pure_markdown_returns_false(self):
        assert _contains_html("# 제목\n\n일반 텍스트") is False

    def test_html_table_returns_true(self):
        assert _contains_html("<table><tr><td>데이터</td></tr></table>") is True

    def test_html_img_returns_true(self):
        assert _contains_html('<img src="data:image/png;base64,abc">') is True

    def test_html_div_returns_true(self):
        assert _contains_html("<div>내용</div>") is True

    def test_empty_string_returns_false(self):
        assert _contains_html("") is False
        assert _contains_html(None) is False


# ---------------------------------------------------------------------------
# HTML → DOCX 변환 테스트
# ---------------------------------------------------------------------------

class TestHtmlToDocx:
    """HTML 콘텐츠가 포함된 마크다운을 DOCX로 변환하는 테스트."""

    def test_html_table_converts_to_docx_table(self, tmp_path):
        html = "<table><tr><th>이름</th><th>나이</th></tr><tr><td>홍길동</td><td>25</td></tr></table>"
        out = tmp_path / "test.docx"
        markdown_to_docx(html, out)

        assert out.exists()
        text = _extract_docx_text(out)
        assert "홍길동" in text
        assert "25" in text
        assert "<table" not in text
        assert _docx_has_table(out)

    def test_html_img_embeds_image(self, tmp_path):
        b64_uri = _make_small_base64_png()
        html = f'<img src="{b64_uri}" alt="테스트 이미지">'
        out = tmp_path / "test_img.docx"
        markdown_to_docx(html, out)

        assert out.exists()
        media = _docx_media_files(out)
        assert len(media) >= 1
        text = _extract_docx_text(out)
        assert "base64" not in text
        assert "<img" not in text

    def test_html_headings_convert_to_docx_headings(self, tmp_path):
        html = "<h1>큰 제목</h1><h2>작은 제목</h2><p>본문</p>"
        out = tmp_path / "test_headings.docx"
        markdown_to_docx(html, out)

        text = _extract_docx_text(out)
        assert "큰 제목" in text
        assert "작은 제목" in text
        assert "본문" in text
        assert "<h1>" not in text
        assert "<h2>" not in text

    def test_html_list_converts_to_docx_list(self, tmp_path):
        html = "<ul><li>항목 1</li><li>항목 2</li></ul>"
        out = tmp_path / "test_list.docx"
        markdown_to_docx(html, out)

        text = _extract_docx_text(out)
        assert "항목 1" in text
        assert "항목 2" in text
        assert "<ul>" not in text
        assert "<li>" not in text

    def test_html_inline_formatting(self, tmp_path):
        html = "<p>이것은 <b>굵은</b> 텍스트와 <i>기울임</i>입니다.</p>"
        out = tmp_path / "test_inline.docx"
        markdown_to_docx(html, out)

        text = _extract_docx_text(out)
        assert "굵은" in text
        assert "기울임" in text
        assert "<b>" not in text
        assert "<i>" not in text

    def test_page_marker_creates_page_break(self, tmp_path):
        html = "<p>첫 페이지</p><!-- 페이지 2 --><p>두 번째 페이지</p>"
        out = tmp_path / "test_pagebreak.docx"
        markdown_to_docx(html, out)

        with zipfile.ZipFile(out) as z:
            xml = z.read("word/document.xml").decode("utf-8")
        assert "w:br" in xml or "lastRenderedPageBreak" in xml
        text = _extract_docx_text(out)
        assert "첫 페이지" in text
        assert "두 번째 페이지" in text
        assert "<!-- 페이지" not in text

    def test_mixed_html_and_text(self, tmp_path):
        html = "<p>소개 문단</p><table><tr><td>데이터</td></tr></table><p>결론</p>"
        out = tmp_path / "test_mixed.docx"
        markdown_to_docx(html, out)

        text = _extract_docx_text(out)
        assert "소개 문단" in text
        assert "데이터" in text
        assert "결론" in text
        assert _docx_has_table(out)

    def test_empty_html(self, tmp_path):
        out = tmp_path / "test_empty.docx"
        markdown_to_docx("", out)
        assert out.exists()
        text = _extract_docx_text(out)
        assert "변환할 콘텐츠가 없습니다" in text


# ---------------------------------------------------------------------------
# 순수 마크다운 회귀 테스트
# ---------------------------------------------------------------------------

class TestPureMarkdownDocx:
    """HTML이 없는 순수 마크다운 변환이 기존대로 작동하는지 확인."""

    def test_pure_markdown_heading(self, tmp_path):
        md = "# 제목\n\n본문 내용"
        out = tmp_path / "test_md.docx"
        markdown_to_docx(md, out)

        text = _extract_docx_text(out)
        assert "제목" in text
        assert "본문 내용" in text
        assert "#" not in text

    def test_pure_markdown_table(self, tmp_path):
        md = "| 이름 | 나이 |\n|------|------|\n| 홍길동 | 25 |"
        out = tmp_path / "test_md_table.docx"
        markdown_to_docx(md, out)

        text = _extract_docx_text(out)
        assert "홍길동" in text
        assert "25" in text
        assert _docx_has_table(out)

    def test_pure_markdown_bold(self, tmp_path):
        md = "이것은 **굵은 텍스트**입니다."
        out = tmp_path / "test_md_bold.docx"
        markdown_to_docx(md, out)

        text = _extract_docx_text(out)
        assert "굵은 텍스트" in text
        assert "**" not in text


# ---------------------------------------------------------------------------
# HTML → PPTX 변환 테스트
# ---------------------------------------------------------------------------

class TestHtmlToPptx:
    """HTML 콘텐츠가 포함된 마크다운을 PPTX로 변환하는 테스트."""

    def test_html_pptx_creates_slides_from_page_markers(self, tmp_path):
        html = "<!-- 페이지 1 --><h1>제목 1</h1><p>내용 1</p><!-- 페이지 2 --><h2>제목 2</h2><p>내용 2</p>"
        out = tmp_path / "test.pptx"
        markdown_to_pptx(html, out)

        assert out.exists()
        with zipfile.ZipFile(out) as z:
            slides = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            assert len(slides) == 2

    def test_html_pptx_table(self, tmp_path):
        html = "<table><tr><th>이름</th></tr><tr><td>홍길동</td></tr></table>"
        out = tmp_path / "test_pptx_table.pptx"
        markdown_to_pptx(html, out)

        assert out.exists()
        with zipfile.ZipFile(out) as z:
            slides = [n for n in z.namelist() if n.startswith("ppt/slides/slide") and n.endswith(".xml")]
            assert len(slides) >= 1
