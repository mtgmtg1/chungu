#!/usr/bin/env python3
# [Flow: Step 1 (HTML 파일 읽기) -> Step 2 (BeautifulSoup으로 모든 <table> 파싱) -> Step 3 (첫 번째 요약 표 건너뛰고 9열 표만 수집) -> Step 4 (9열로 정규화 후 단일 DataFrame 생성) -> Step 5 (Excel 저장)]

import pandas as pd
from bs4 import BeautifulSoup
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "gukwonlist.pdf_by_PaddleOCR-VL-1.6 (1).md"
OUTPUT_FILE = Path(__file__).parent / "gukwonlist_tables_v2.xlsx"

# 정규화된 헤더 (9열 고정)
FIXED_HEADER = ["연변", "구분", "계좌번호", "거래일자", "출금금액(원)", "입금금액(원)", "거래기록사항", "이체해요", "계정"]
NUM_COLS = 9


def normalize_row(row_data: list[str]) -> list[str]:
    # 9열로 맞춤: 부족하면 빈 문자열 패딩, 초과하면 앞 9개만 사용
    if len(row_data) >= NUM_COLS:
        return row_data[:NUM_COLS]
    return row_data + [""] * (NUM_COLS - len(row_data))


def is_header_row(row_data: list[str]) -> bool:
    # 헤더 행인지 확인: 첫 셀이 "연변"이고 둘째 셀이 "구분"인 행
    if len(row_data) < 2:
        return False
    return row_data[0] == "연변" and row_data[1] == "구분"


def is_summary_table(first_row: list[str]) -> bool:
    # 요약 표인지 확인: 헤더가 "연변", "계정", "지출 금액", "비고" (4열)
    if len(first_row) < 2:
        return False
    return first_row[0] == "연변" and first_row[1] == "계정"


def extract_tables_to_excel(input_path: Path, output_path: Path) -> None:
    # Step 1: HTML 파일 읽기
    html_content = input_path.read_text(encoding="utf-8")

    # Step 2: BeautifulSoup으로 모든 <table> 파싱
    soup = BeautifulSoup(html_content, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        print("표가 없습니다.")
        return

    # Step 3: 요약 표 건너뛰고 9열 데이터 표만 수집
    all_rows = []

    for idx, table in enumerate(tables):
        rows = table.find_all("tr")
        if not rows:
            continue

        # 첫 행으로 요약 표 여부 확인
        first_row_cells = rows[0].find_all(["td", "th"])
        first_row = [c.get_text(strip=True) for c in first_row_cells]

        if is_summary_table(first_row):
            print(f"표 {idx + 1} 건너뜀 (요약 표)")
            continue

        for row in rows:
            cells = row.find_all(["td", "th"])
            row_data = [cell.get_text(strip=True) for cell in cells]
            if not row_data:
                continue

            # 헤더 행 건너뜀
            if is_header_row(row_data):
                continue

            # "합계" 행 건너뜀
            if row_data[0] == "합계":
                continue

            # 9열로 정규화
            normalized = normalize_row(row_data)
            all_rows.append(normalized)

        print(f"표 {idx + 1} 처리 완료 (누적 {len(all_rows)}행)")

    if not all_rows:
        print("데이터 행이 없습니다.")
        return

    # Step 4: 단일 DataFrame 생성 (9열 고정 헤더)
    df = pd.DataFrame(all_rows, columns=FIXED_HEADER)

    # Step 5: Excel 저장
    df.to_excel(output_path, engine="openpyxl", index=False)

    print(f"\n완료: {output_path} (총 {len(df)}행, {NUM_COLS}열)")


if __name__ == "__main__":
    extract_tables_to_excel(INPUT_FILE, OUTPUT_FILE)
