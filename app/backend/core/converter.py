#!/usr/bin/env python3
# [Flow: Step 1 (통합 행 입력) -> Step 2 (CSV 작성) -> Step 3 (MD 표 작성) -> Step 4 (파일 경로 반환)]
import csv
from pathlib import Path


def write_csv(rows: list[dict], columns: list[str], out_path: Path) -> Path:
    """통합 행을 UTF-8-SIG CSV로 저장한다 (엑셀 호환)."""
    fields = ["페이지"] + columns
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return out_path


def write_markdown(rows: list[dict], columns: list[str], out_path: Path) -> Path:
    """통합 행을 마크다운 표로 저장한다."""
    fields = ["페이지"] + columns
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["| " + " | ".join(fields) + " |", "| " + " | ".join([":---"] * len(fields)) + " |"]
    for row in rows:
        cells = [str(row.get(c, "")).replace("|", "\\|") for c in fields]
        lines.append("| " + " | ".join(cells) + " |")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def build_layout_markdown_string(page_contents: list[tuple[int, str]]) -> str:
    """페이지별 마크다운 레이아웃을 문자열로 반환한다."""
    parts: list[str] = []
    for page_num, content in sorted(page_contents, key=lambda x: x[0]):
        if not content.strip():
            continue
        parts.append(f"<!-- 페이지 {page_num} -->\n\n{content.strip()}")
    return "\n\n---\n\n".join(parts)


def write_layout_markdown(page_contents: list[tuple[int, str]], out_path: Path) -> Path:
    """페이지별 마크다운 레이아웃을 페이지 구분선과 함께 저장한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_layout_markdown_string(page_contents), encoding="utf-8")
    return out_path


def build_combined_file_markdowns(file_markdowns: list[str]) -> str:
    """파일별 마크다운을 파일 구분자와 함께 하나의 문자열로 조합한다."""
    parts: list[str] = []
    for idx, fm in enumerate(file_markdowns, start=1):
        if not fm.strip():
            continue
        parts.append(f"<!-- 파일 {idx} -->\n\n{fm.strip()}")
    return "\n\n---\n\n".join(parts)


def write_combined_file_markdowns(file_markdowns: list[str], out_path: Path) -> Path:
    """파일별 마크다운을 파일 구분자와 함께 저장한다."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(build_combined_file_markdowns(file_markdowns), encoding="utf-8")
    return out_path
