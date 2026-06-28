#!/usr/bin/env python3
# [Flow: Step 1 (마크다운 블록 파싱) -> Step 2 (docx/pptx/xlsx 작성) -> Step 3 (파일 경로 반환)]
import re
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt, RGBColor
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from pptx import Presentation
from pptx.util import Inches as PptxInches


# ---------------------------------------------------------------------------
# Markdown block parser
# ---------------------------------------------------------------------------

def _parse_markdown_blocks(markdown: str) -> list[dict]:
    """마크다운 텍스트를 블록 단위로 파싱하여 모든 콘텐츠를 유실 없이 반환한다.

    반환 블록 형식:
      - {"type": "heading", "level": int, "text": str}
      - {"type": "paragraph", "text": str}
      - {"type": "list", "ordered": bool, "items": list[str]}
      - {"type": "table", "headers": list[str], "rows": list[list[str]]}
      - {"type": "code", "language": str, "text": str}
    """
    lines = markdown.splitlines()
    blocks: list[dict] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        # 코드 블록
        if stripped.startswith("```"):
            language = stripped[3:].strip()
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            i += 1  # 닫는 ``` 건너뜀
            blocks.append({"type": "code", "language": language, "text": "\n".join(code_lines)})
            continue

        # 제목
        if stripped.startswith("#"):
            level = 0
            while level < len(stripped) and stripped[level] == "#":
                level += 1
            text = stripped[level:].strip()
            blocks.append({"type": "heading", "level": level, "text": text})
            i += 1
            continue

        # 표
        if stripped.startswith("|"):
            table_lines: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            if len(table_lines) >= 2:
                headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]
                rows = []
                for row_line in table_lines[2:]:
                    cells = [c.strip() for c in row_line.split("|")[1:-1]]
                    rows.append(cells)
                blocks.append({"type": "table", "headers": headers, "rows": rows})
            continue

        # 목록
        list_match = re.match(r"^[-*+]\s+(.*)", stripped)
        ordered_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
        if list_match or ordered_match:
            items: list[str] = []
            ordered = bool(ordered_match)
            while i < len(lines):
                item_line = lines[i].strip()
                if not item_line:
                    break
                unordered_m = re.match(r"^[-*+]\s+(.*)", item_line)
                ordered_m = re.match(r"^\d+\.\s+(.*)", item_line)
                if unordered_m:
                    ordered = False
                    items.append(unordered_m.group(1))
                    i += 1
                elif ordered_m:
                    items.append(ordered_m.group(1))
                    i += 1
                else:
                    break
            blocks.append({"type": "list", "ordered": ordered, "items": items})
            continue

        # 문단
        para_lines = [line]
        i += 1
        while i < len(lines):
            next_line = lines[i]
            next_stripped = next_line.strip()
            if not next_stripped:
                break
            if (
                next_stripped.startswith("#")
                or next_stripped.startswith("```")
                or next_stripped.startswith("|")
                or re.match(r"^[-*+]\s", next_stripped)
                or re.match(r"^\d+\.\s", next_stripped)
            ):
                break
            para_lines.append(next_line)
            i += 1
        blocks.append({"type": "paragraph", "text": " ".join(para_lines).strip()})

    return blocks


def _split_text_inline(text: str) -> list[tuple[str, dict]]:
    """마크다운 인라인 서식(**굵게**, *기울임*, ~~취소선~~)을 분리한다."""
    pattern = r"(\*\*\*[^*]+\*\*\*|\*\*[^*]+\*\*|\*[^*]+\*|~~[^~]+~~)"
    parts = re.split(pattern, text)
    result = []
    for part in parts:
        if not part:
            continue
        fmt = {}
        if part.startswith("***") and part.endswith("***"):
            fmt = {"bold": True, "italic": True}
            part = part[3:-3]
        elif part.startswith("**") and part.endswith("**"):
            fmt = {"bold": True}
            part = part[2:-2]
        elif part.startswith("*") and part.endswith("*"):
            fmt = {"italic": True}
            part = part[1:-1]
        elif part.startswith("~~") and part.endswith("~~"):
            fmt = {"strike": True}
            part = part[2:-2]
        result.append((part, fmt))
    return result


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------

def _add_docx_runs(paragraph, text: str) -> None:
    """문단에 인라인 서식을 적용한 run을 추가한다."""
    for part, fmt in _split_text_inline(text):
        run = paragraph.add_run(part)
        if fmt.get("bold"):
            run.bold = True
        if fmt.get("italic"):
            run.italic = True
        if fmt.get("strike"):
            run.font.strike = True


def markdown_to_docx(markdown: str, out_path: Path) -> Path:
    """마크다운 전체 콘텐츠를 Word 문서로 변환한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = _parse_markdown_blocks(markdown)
    doc = Document()

    if not blocks:
        doc.add_paragraph("변환할 콘텐츠가 없습니다.")
        doc.save(out_path)
        return out_path

    table_idx = 0
    for block in blocks:
        if block["type"] == "heading":
            doc.add_heading(block["text"], level=min(block["level"], 6))
        elif block["type"] == "paragraph":
            p = doc.add_paragraph()
            _add_docx_runs(p, block["text"])
        elif block["type"] == "list":
            style = "List Number" if block["ordered"] else "List Bullet"
            for item in block["items"]:
                p = doc.add_paragraph(style=style)
                _add_docx_runs(p, item)
        elif block["type"] == "table":
            table_idx += 1
            headers = block["headers"]
            rows = block["rows"]
            if not headers and not rows:
                continue
            cols = max(len(headers), max((len(r) for r in rows), default=1), 1)
            doc_table = doc.add_table(rows=1 + len(rows), cols=cols)
            doc_table.style = "Table Grid"
            for i, h in enumerate(headers):
                cell = doc_table.rows[0].cells[i]
                cell.text = h
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        run.font.bold = True
            for r_idx, row in enumerate(rows):
                for c_idx, val in enumerate(row):
                    if c_idx < cols:
                        doc_table.rows[r_idx + 1].cells[c_idx].text = val
            doc.add_paragraph()
        elif block["type"] == "code":
            p = doc.add_paragraph()
            run = p.add_run(block["text"])
            run.font.name = "Courier New"
            run.font.size = Pt(10)
            p.paragraph_format.left_indent = Inches(0.25)

    doc.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# PPTX
# ---------------------------------------------------------------------------

def _blocks_to_slide_text(blocks: list[dict]) -> str:
    """블록 목록을 슬라이드 본문 텍스트로 변환한다."""
    lines = []
    for block in blocks:
        if block["type"] == "paragraph":
            lines.append(block["text"])
        elif block["type"] == "heading":
            lines.append("" + ("#" * block["level"]) + " " + block["text"])
        elif block["type"] == "list":
            for idx, item in enumerate(block["items"], start=1):
                prefix = f"{idx}. " if block["ordered"] else "• "
                lines.append(prefix + item)
        elif block["type"] == "table":
            headers = " | ".join(block["headers"])
            rows = [" | ".join(r) for r in block["rows"]]
            lines.append(headers)
            lines.append("-" * len(headers))
            lines.extend(rows)
            lines.append("")
        elif block["type"] == "code":
            lines.append("```" + block["language"])
            lines.append(block["text"])
            lines.append("```")
    return "\n".join(lines)


def markdown_to_pptx(markdown: str, out_path: Path) -> Path:
    """마크다운 전체 콘텐츠를 PowerPoint로 변환한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = _parse_markdown_blocks(markdown)
    prs = Presentation()

    if not blocks:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_textbox(
            PptxInches(0.5), PptxInches(0.5), PptxInches(9), PptxInches(1)
        ).text_frame.text = "변환할 콘텐츠가 없습니다."
        prs.save(out_path)
        return out_path

    # 제목을 기준으로 슬라이드 그룹화
    slides: list[dict] = []
    current_title = ""
    current_body: list[dict] = []

    for block in blocks:
        if block["type"] == "heading":
            if current_title or current_body:
                slides.append({"title": current_title, "body": current_body})
            current_title = block["text"]
            current_body = []
        else:
            current_body.append(block)

    if current_title or current_body:
        slides.append({"title": current_title, "body": current_body})

    # 제목이 하나도 없으면 모든 콘텐츠를 한 슬라이드에 담는다
    if not slides:
        slides = [{"title": "", "body": blocks}]

    for slide_data in slides:
        slide = prs.slides.add_slide(prs.slide_layouts[6])

        # 제목
        title_box = slide.shapes.add_textbox(
            PptxInches(0.5), PptxInches(0.3), PptxInches(9), PptxInches(0.8)
        )
        title_box.text_frame.text = slide_data["title"]
        for paragraph in title_box.text_frame.paragraphs:
            paragraph.font.size = Pt(20)
            paragraph.font.bold = True

        # 본문
        body_text = _blocks_to_slide_text(slide_data["body"])
        if body_text:
            body_box = slide.shapes.add_textbox(
                PptxInches(0.5), PptxInches(1.2), PptxInches(9), PptxInches(5.5)
            )
            tf = body_box.text_frame
            tf.text = body_text
            tf.word_wrap = True
            for paragraph in tf.paragraphs:
                paragraph.font.size = Pt(12)

    prs.save(out_path)
    return out_path


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------

def _safe_sheet_name(name: str, index: int) -> str:
    """openpyxl 시트 이름 규칙에 맞게 제한 길이 및 금지 문자를 처리한다."""
    name = re.sub(r"[\\/*?:\[\]]", "-", name).strip()[:28]
    if not name:
        name = f"Sheet{index}"
    return name


def markdown_to_xlsx(markdown: str, out_path: Path) -> Path:
    """마크다운 전체 콘텐츠를 Excel 파일로 변환한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = _parse_markdown_blocks(markdown)
    wb = Workbook()
    ws_content = wb.active
    ws_content.title = "Content"

    # 콘텐츠 시트에 텍스트/목록/제목/코드 기록
    row = 1
    table_count = 0
    for block in blocks:
        if block["type"] == "heading":
            cell = ws_content.cell(row, 1, block["text"])
            cell.font = Font(bold=True, size=16 - block["level"])
            row += 1
        elif block["type"] == "paragraph":
            ws_content.cell(row, 1, block["text"])
            row += 1
        elif block["type"] == "list":
            for idx, item in enumerate(block["items"], start=1):
                prefix = f"{idx}. " if block["ordered"] else "• "
                ws_content.cell(row, 1, prefix + item)
                row += 1
        elif block["type"] == "code":
            cell = ws_content.cell(row, 1, block["text"])
            cell.font = Font(name="Courier New")
            row += 1
        elif block["type"] == "table":
            table_count += 1
            headers = block["headers"]
            rows = block["rows"]
            sheet_name = _safe_sheet_name("Table " + " ".join(headers[:2]), table_count)
            ws_table = wb.create_sheet(title=sheet_name)
            for c_idx, h in enumerate(headers):
                cell = ws_table.cell(1, c_idx + 1, h)
                cell.font = Font(bold=True)
                cell.fill = PatternFill(start_color="E0E7FF", end_color="E0E7FF", fill_type="solid")
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            for r_idx, row_data in enumerate(rows):
                for c_idx, val in enumerate(row_data):
                    ws_table.cell(r_idx + 2, c_idx + 1, val)
            # 콘텐츠 시트에 표 위치 안내
            ws_content.cell(row, 1, f"[표 {table_count}: {sheet_name} 시트 참조]")
            row += 1

    # 표가 하나도 없으면 안내 문구 추가
    if table_count == 0 and row == 1:
        ws_content.cell(1, 1, "변환할 콘텐츠가 없습니다.")

    # 컬럼 너비 자동 조정
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                try:
                    if cell.value:
                        max_len = max(max_len, len(str(cell.value)))
                except Exception:
                    pass
            ws.column_dimensions[col_letter].width = min(max_len + 2, 60)

    wb.save(out_path)
    return out_path
