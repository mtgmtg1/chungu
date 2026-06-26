#!/usr/bin/env python3
# [Flow: Step 1 (scan page MD files) -> Step 2 (parse markdown tables) -> Step 3 (normalize rows) -> Step 4 (merge into DataFrame) -> Step 5 (write CSV)]
import csv
import json
import re
import sys
from pathlib import Path

# Expected columns for the detail transaction table
COLUMNS = [
    "페이지",
    "연번",
    "구분",
    "계좌번호",
    "거래일자",
    "출금금액(원)",
    "입금금액(원)",
    "거래기록사항",
    "이체메모",
    "계정",
]


def parse_markdown_table(text):
    """Parse a markdown table into a list of dicts."""
    if not text:
        return []
    lines = [line.strip() for line in text.strip().splitlines() if line.strip().startswith("|")]
    if not lines:
        return []
    # First row is header
    header = [cell.strip() for cell in lines[0].split("|")]
    header = [c for c in header if c]
    if len(header) < 2:
        return []
    # Second row is separator, skip
    data_lines = lines[2:] if len(lines) > 2 else lines[1:]
    rows = []
    for line in data_lines:
        cells = [cell.strip() for cell in line.split("|")]
        # Remove leading/trailing empty cells caused by leading/trailing pipes
        while cells and cells[0] == "":
            cells = cells[1:]
        while cells and cells[-1] == "":
            cells = cells[:-1]
        # If more cells than header, trim; if fewer, pad
        if len(cells) > len(header):
            cells = cells[: len(header)]
        elif len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append(dict(zip(header, cells)))
    return rows


def normalize_page_rows(page_num, rows):
    """Map page table rows to the unified schema."""
    mapped = []
    for row in rows:
        # Determine serial index: prefer '연번', '순번', '번호'
        serial = row.get("연번", row.get("순번", row.get("번호", "")))
        # Account number
        account = row.get("계좌번호", row.get("계좌", ""))
        # Date
        date_val = row.get("거래일자", row.get("일자", ""))
        # Withdrawal amount
        out_amt = row.get("출금금액(원)", row.get("출금금액", row.get("출금", "")))
        # Deposit amount
        in_amt = row.get("입금금액(원)", row.get("입금금액", row.get("입금", "")))
        # Description / memo fields
        record = row.get("거래기록사항", row.get("거래내용", row.get("적요", "")))
        memo = row.get("이체메모", row.get("메모", ""))
        # Category (account classification)
        category = row.get("계정", row.get("구분", ""))
        # Source classification (bank/channel) — try to map from 구분 if available
        bank = row.get("구분", "")
        mapped.append(
            {
                "페이지": page_num,
                "연번": serial,
                "구분": bank,
                "계좌번호": account,
                "거래일자": date_val,
                "출금금액(원)": out_amt,
                "입금금액(원)": in_amt,
                "거래기록사항": record,
                "이체메모": memo,
                "계정": category,
            }
        )
    return mapped


def main():
    out_dir = Path("/Users/jun16/repo/chungu/ocr_output")
    pages_dir = out_dir / "pages"
    if not pages_dir.exists():
        print(f"[error] pages directory not found: {pages_dir}")
        sys.exit(1)

    all_rows = []
    page_files = sorted(pages_dir.glob("page_*.md"))
    # Exclude summary files
    detail_files = [f for f in page_files if "_summary" not in f.name]

    for f in detail_files:
        m = re.search(r"page_(\d+)\.md", f.name)
        if not m:
            continue
        page_num = int(m.group(1))
        text = f.read_text(encoding="utf-8")
        rows = parse_markdown_table(text)
        if not rows:
            print(f"[warn] no table found in {f.name}")
            continue
        normalized = normalize_page_rows(page_num, rows)
        # Skip empty rows and total rows
        valid_rows = [r for r in normalized if r["거래일자"] and r["연번"] != "합계"]
        all_rows.extend(valid_rows)
        print(f"[merged] page {page_num:03d}: {len(valid_rows)} row(s)")

    csv_path = out_dir / "거래내역_통합.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"[done] wrote {csv_path} with {len(all_rows)} rows")
    # Print summary stats
    pages = sorted({r["페이지"] for r in all_rows})
    if pages:
        print(f"[summary] pages with rows: {len(pages)} (first={pages[0]}, last={pages[-1]})")


if __name__ == "__main__":
    main()
