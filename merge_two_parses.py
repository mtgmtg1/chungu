#!/usr/bin/env python3
# [Flow: Step 1 (세 MD 파일에서 각각 표 추출) -> Step 2 (연변 번호를 키로 dict 생성) -> Step 3 (세 dict 병합, 첫 파일 우선) -> Step 4 (1~13789 순서대로 정렬 후 Excel 저장)]

import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path

FILE_1 = Path(__file__).parent / "gukwonlist.pdf_by_PaddleOCR-VL-1.6.md"
FILE_2 = Path(__file__).parent / "gukwonlist.pdf_by_PaddleOCR-VL-1.6 (1).md"
FILE_3 = Path(__file__).parent / "gukwonlist.pdf_by_PaddleOCR-VL-1.6-2.md"
OUTPUT_FILE = Path(__file__).parent / "gukwonlist_tables_merged.xlsx"

FIXED_HEADER = ["연변", "구분", "계좌번호", "거래일자", "출금금액(원)", "입금금액(원)", "거래기록사항", "이체해요", "계정"]
NUM_COLS = 9


def normalize_row(row_data: list[str]) -> list[str]:
    if len(row_data) >= NUM_COLS:
        return row_data[:NUM_COLS]
    return row_data + [""] * (NUM_COLS - len(row_data))


def is_header_row(row_data: list[str]) -> bool:
    if len(row_data) < 2:
        return False
    return row_data[0] == "연변" and row_data[1] == "구분"


def is_summary_table(first_row: list[str]) -> bool:
    if len(first_row) < 2:
        return False
    return first_row[0] == "연변" and first_row[1] == "계정"


def extract_rows_from_file(file_path: Path) -> dict[int, list[str]]:
    # 파일에서 모든 행을 추출하여 {연변번호: row_data} dict 반환
    html_content = file_path.read_text(encoding="utf-8")
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")

    rows_by_num = {}
    for table in tables:
        trs = table.find_all("tr")
        if not trs:
            continue

        first_cells = trs[0].find_all(["td", "th"])
        first_row = [c.get_text(strip=True) for c in first_cells]
        if is_summary_table(first_row):
            continue

        for tr in trs:
            cells = tr.find_all(["td", "th"])
            row_data = [c.get_text(strip=True) for c in cells]
            if not row_data:
                continue
            if is_header_row(row_data):
                continue
            if row_data[0] == "합계":
                continue

            try:
                num = int(row_data[0])
            except (ValueError, TypeError):
                continue

            normalized = normalize_row(row_data)
            if num not in rows_by_num:
                rows_by_num[num] = normalized

    return rows_by_num


def merge_and_export(file1: Path, file2: Path, file3: Path, output: Path) -> None:
    # Step 1: 세 파일에서 각각 추출
    rows1 = extract_rows_from_file(file1)
    rows2 = extract_rows_from_file(file2)
    rows3 = extract_rows_from_file(file3)
    print(f"파일1: {len(rows1)}행")
    print(f"파일2: {len(rows2)}행")
    print(f"파일3: {len(rows3)}행")

    # Step 2: 병합 (파일1 우선, 없으면 파일2, 그래도 없으면 파일3)
    merged = {}
    merged.update(rows3)
    merged.update(rows2)
    merged.update(rows1)

    # Step 3: 1~13789 순서대로 정렬
    all_rows = []
    missing = []
    for num in range(1, 13790):
        if num in merged:
            all_rows.append(merged[num])
        else:
            missing.append(num)
            # 빈 행이라도 번호는 채워넣음
            all_rows.append([str(num)] + [""] * (NUM_COLS - 1))

    print(f"병합 후: {len(merged)}행")
    print(f"누락: {len(missing)}개")

    if missing:
        ranges = []
        start = missing[0]
        prev = missing[0]
        for n in missing[1:]:
            if n == prev + 1:
                prev = n
            else:
                ranges.append((start, prev) if start != prev else (start,))
                start = n
                prev = n
        ranges.append((start, prev) if start != prev else (start,))
        print("누락된 구간:")
        for r in ranges:
            if len(r) == 1:
                print(f"  {r[0]}")
            else:
                print(f"  {r[0]} ~ {r[1]} ({r[1]-r[0]+1}개)")

    # Step 4: Excel 저장
    df = pd.DataFrame(all_rows, columns=FIXED_HEADER)
    df.to_excel(output, engine="openpyxl", index=False)
    print(f"\n완료: {output} (총 {len(df)}행, {NUM_COLS}열)")


if __name__ == "__main__":
    merge_and_export(FILE_1, FILE_2, FILE_3, OUTPUT_FILE)
