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
