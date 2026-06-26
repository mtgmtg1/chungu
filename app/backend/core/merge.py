#!/usr/bin/env python3
# [Flow: Step 1 (페이지 표 파싱) -> Step 2 (동적 컬럼 정규화) -> Step 3 (페이지 순서대로 병합)]
# 기존 merge_csv.py 를 컬럼 하드코딩 없이 일반화.
import re


def parse_markdown_table(text: str) -> list[dict]:
    """마크다운 표를 dict 리스트로 파싱한다."""
    if not text:
        return []
    lines = [ln.strip() for ln in text.strip().splitlines() if ln.strip().startswith("|")]
    if not lines:
        return []
    header = [c.strip() for c in lines[0].split("|") if c.strip()]
    if len(header) < 2:
        return []
    data_lines = lines[2:] if len(lines) > 2 else lines[1:]
    rows = []
    for line in data_lines:
        cells = [c.strip() for c in line.split("|")]
        while cells and cells[0] == "":
            cells = cells[1:]
        while cells and cells[-1] == "":
            cells = cells[:-1]
        if len(cells) > len(header):
            cells = cells[: len(header)]
        elif len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return rows


def parse_csv_block(text: str) -> list[dict]:
    """LLM이 만든 CSV 블록을 dict 리스트로 파싱한다 (첫 줄은 헤더)."""
    if not text:
        return []
    import csv
    import io

    reader = csv.reader(io.StringIO(text.strip()))
    rows = list(reader)
    if len(rows) < 2:
        return []
    header = [h.strip() for h in rows[0]]
    out = []
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        out.append(dict(zip(header, r[: len(header)])))
    return out


def normalize_row(page_num: int, row: dict, columns: list[str]) -> dict:
    """페이지 행을 통합 스키마(페이지 + 사용자 컬럼)로 매핑한다."""
    mapped = {"페이지": page_num}
    for col in columns:
        mapped[col] = row.get(col, "")
    return mapped


def is_skippable(row: dict, columns: list[str]) -> bool:
    """완전히 빈 행이나 '합계' 행을 거른다."""
    values = [str(row.get(c, "")).strip() for c in columns]
    if not any(values):
        return True
    if any(v == "합계" for v in values):
        return True
    return False


def merge_pages(page_tables: list[tuple[int, str]], columns: list[str], fmt: str = "markdown") -> list[dict]:
    """[(page_num, raw_table_text)] 를 통합 행 리스트로 병합한다.

    fmt: 'markdown'(vision) | 'csv'(hybrid)
    """
    parser = parse_markdown_table if fmt == "markdown" else parse_csv_block
    all_rows: list[dict] = []
    for page_num, text in sorted(page_tables, key=lambda x: x[0]):
        for row in parser(text):
            norm = normalize_row(page_num, row, columns)
            if is_skippable(norm, columns):
                continue
            all_rows.append(norm)
    return all_rows
