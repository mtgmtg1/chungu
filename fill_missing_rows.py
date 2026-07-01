#!/usr/bin/env python3
# [Flow: Step 1 (병합된 Excel에서 기존 데이터 로드) -> Step 2 (ocr_output/pages/page_305.md, page_325.md에서 마크다운 표 파싱) -> Step 3 (누락된 연변 11564, 12301-12329 채움) -> Step 4 (완성된 Excel 저장)]

import pandas as pd
import re
from pathlib import Path

MERGED_FILE = Path(__file__).parent / "gukwonlist_tables_merged.xlsx"
OUTPUT_FILE = Path(__file__).parent / "gukwonlist_tables_final.xlsx"
PAGES_DIR = Path(__file__).parent / "ocr_output" / "pages"

FIXED_HEADER = ["연변", "구분", "계좌번호", "거래일자", "출금금액(원)", "입금금액(원)", "거래기록사항", "이체해요", "계정"]
NUM_COLS = 9
MISSING_NUMS = {11564} | set(range(12301, 12330))


def normalize_row(row_data: list[str]) -> list[str]:
    if len(row_data) >= NUM_COLS:
        return row_data[:NUM_COLS]
    return row_data + [""] * (NUM_COLS - len(row_data))


def parse_markdown_table(file_path: Path) -> dict[int, list[str]]:
    # 마크다운 표에서 9열 데이터 추출
    rows_by_num = {}
    lines = file_path.read_text(encoding="utf-8").splitlines()

    for line in lines:
        line = line.strip()
        if not line.startswith("|"):
            continue
        if re.match(r"\|[:\- ]+\|", line):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if cells[0] == "연번":
            continue

        try:
            num = int(cells[0])
        except (ValueError, TypeError):
            continue

        if num in MISSING_NUMS:
            normalized = normalize_row(cells)
            rows_by_num[num] = normalized

    return rows_by_num


def fill_missing_rows() -> None:
    # Step 1: 기존 데이터 로드, 모든 값을 문자열로 처리
    df = pd.read_excel(MERGED_FILE, dtype=str)
    print(f"기존 데이터: {len(df)}행")

    # Step 2: 페이지 파일에서 누락 행 추출
    missing_rows = {}
    for page_file in ["page_305.md", "page_325.md"]:
        file_path = PAGES_DIR / page_file
        if file_path.exists():
            extracted = parse_markdown_table(file_path)
            missing_rows.update(extracted)
            print(f"{page_file}: {len(extracted)}개 누락 행 추출")

    print(f"추출된 누락 행: {len(missing_rows)}개 / {len(MISSING_NUMS)}개 필요")

    # Step 3: 연변 값이 일치하는 행 찾아서 채움
    filled_count = 0
    for idx, row in df.iterrows():
        try:
            num = int(row["연변"])
        except (ValueError, TypeError):
            continue
        if num in missing_rows:
            df.loc[idx] = missing_rows[num]
            filled_count += 1

    print(f"채워진 행: {filled_count}개")

    # Step 4: 저장
    df.to_excel(OUTPUT_FILE, engine="openpyxl", index=False)
    print(f"\n완료: {OUTPUT_FILE} (총 {len(df)}행, {NUM_COLS}열)")

    # Step 5: 최종 누락 확인
    nums = df["연변"].apply(lambda x: int(x) if str(x).isdigit() else None).dropna().astype(int)
    expected = set(range(1, 13790))
    actual = set(nums.tolist())
    final_missing = expected - actual
    print(f"최종 누락: {len(final_missing)}개")
    if final_missing:
        print(f"  {sorted(final_missing)}")


if __name__ == "__main__":
    fill_missing_rows()
