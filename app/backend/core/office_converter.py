#!/usr/bin/env python3
# [Flow: Step 1 (마크다운 표 파싱) -> Step 2 (docx/pptx 작성) -> Step 3 (파일 경로 반환)]
import re
from pathlib import Path

from docx import Document
from docx.shared import Inches, Pt
from pptx import Presentation
from pptx.util import Inches as PptxInches


def _parse_markdown_tables(markdown: str) -> list[dict]:
    """마크다운 텍스트에서 표를 파싱하여 {name, headers, rows} 리스트로 반환한다."""
    tables = []
    lines = markdown.splitlines()
    i = 0
    table_idx = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|"):
            table_lines = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                table_lines.append(lines[i].strip())
                i += 1
            if len(table_lines) >= 2:
                headers = [c.strip() for c in table_lines[0].split("|")[1:-1]]
                rows = []
                for row_line in table_lines[2:]:
                    cells = [c.strip() for c in row_line.split("|")[1:-1]]
                    rows.append(cells)
                table_idx += 1
                tables.append({
                    "name": f"Table{table_idx}",
                    "headers": headers,
                    "rows": rows,
                })
        else:
            i += 1
    return tables


def markdown_to_docx(markdown: str, out_path: Path) -> Path:
    """마크다운 표를 Word 문서로 변환한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    doc = Document()
    tables = _parse_markdown_tables(markdown)
    if not tables:
        doc.add_paragraph("표 데이터가 없습니다.")
        doc.save(out_path)
        return out_path
    for table in tables:
        doc.add_heading(table["name"], level=2)
        headers = table["headers"]
        rows = table["rows"]
        doc_table = doc.add_table(rows=1 + len(rows), cols=max(len(headers), 1))
        doc_table.style = "Table Grid"
        hdr_cells = doc_table.rows[0].cells
        for i, h in enumerate(headers):
            hdr_cells[i].text = h
            for paragraph in hdr_cells[i].paragraphs:
                for run in paragraph.runs:
                    run.font.bold = True
        for r_idx, row in enumerate(rows):
            cells = doc_table.rows[r_idx + 1].cells
            for c_idx, val in enumerate(row):
                if c_idx < len(cells):
                    cells[c_idx].text = val
        doc.add_paragraph()
    doc.save(out_path)
    return out_path


def markdown_to_pptx(markdown: str, out_path: Path) -> Path:
    """마크다운 표를 PowerPoint로 변환한다 (표 하나당 슬라이드 한 장)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    prs = Presentation()
    tables = _parse_markdown_tables(markdown)
    if not tables:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        slide.shapes.add_textbox(
            PptxInches(0.5), PptxInches(0.5), PptxInches(9), PptxInches(1)
        ).text_frame.text = "표 데이터가 없습니다."
        prs.save(out_path)
        return out_path
    for table in tables:
        slide = prs.slides.add_slide(prs.slide_layouts[6])
        title_box = slide.shapes.add_textbox(
            PptxInches(0.5), PptxInches(0.3), PptxInches(9), PptxInches(0.8)
        )
        title_box.text_frame.text = table["name"]
        for paragraph in title_box.text_frame.paragraphs:
            paragraph.font.size = Pt(18)
            paragraph.font.bold = True
        headers = table["headers"]
        rows = table["rows"]
        cols = max(len(headers), 1)
        rows_count = 1 + len(rows)
        left = PptxInches(0.5)
        top = PptxInches(1.2)
        width = PptxInches(9)
        height = PptxInches(5.5)
        ppt_table = slide.shapes.add_table(rows_count, cols, left, top, width, height).table
        for i, h in enumerate(headers):
            ppt_table.cell(0, i).text = h
            for paragraph in ppt_table.cell(0, i).text_frame.paragraphs:
                paragraph.font.bold = True
        for r_idx, row in enumerate(rows):
            for c_idx, val in enumerate(row):
                if c_idx < cols:
                    ppt_table.cell(r_idx + 1, c_idx).text = val
    prs.save(out_path)
    return out_path
