#!/usr/bin/env python3
# [Flow: Step 1 (대상 이름 리스트 정의) -> Step 2 (이름에서 2글자 이상 연속 부분문자열 생성) -> Step 3 (최종 Excel을 읽어 각 행 검사) -> Step 4 (부분문자열이 포함된 행 수집) -> Step 5 (매칭된 행과 매칭 정보를 Excel로 저장)]

import pandas as pd
from pathlib import Path

INPUT_FILE = Path(__file__).parent / "gukwonlist_tables_final.xlsx"
OUTPUT_EXACT_FILE = Path(__file__).parent / "gukwonlist_filtered_by_name_exact.xlsx"
OUTPUT_WILDCARD_FILE = Path(__file__).parent / "gukwonlist_filtered_by_name_wildcard.xlsx"

TARGET_NAMES = [
    "강영석", "조영하", "정용재", "이영주", "민대홍", "임상희", "임홍석", "정희정",
    "윤정애", "김선필", "김수중", "박덕희", "고성찬", "서병기", "이민혁", "이승은",
    "최희남", "이나영", "오한주", "서정훈", "이우민", "이선기", "이완의", "박현준",
    "한창희", "정경윤", "조명희", "이재진", "노윤자", "정나경", "성연화",
]


def generate_substrings(name: str) -> list[str]:
    # 이름에서 길이 2 이상인 모든 연속 부분문자열 생성
    n = len(name)
    substrings = []
    for length in range(2, n + 1):
        for start in range(0, n - length + 1):
            substrings.append(name[start:start + length])
    return substrings


def generate_wildcard_patterns(name: str) -> list[str]:
    # 3글자 이상 이름에서 첫 글자와 끝 글자가 같은 패턴 생성 (가운데 틀림 허용)
    # 예: 이영주 -> 이?주
    n = len(name)
    patterns = []
    if n >= 3:
        patterns.append(name[0] + "?" + name[-1])
    return patterns


def find_exact_matches(df: pd.DataFrame, target_names: list[str]) -> dict[int, set[str]]:
    # 정확한 부분문자열 매칭: 연변(row index) -> set(매칭된 이름)
    name_to_substrings = {name: generate_substrings(name) for name in target_names}
    exact_matches: dict[int, set[str]] = {}

    for idx, row in df.iterrows():
        row_text = "|".join(str(v) for v in row.values if pd.notna(v))
        for name in target_names:
            if any(sub in row_text for sub in name_to_substrings[name]):
                exact_matches.setdefault(idx, set()).add(name)
    return exact_matches


def find_wildcard_matches(
    df: pd.DataFrame,
    target_names: list[str],
    exact_matches: dict[int, set[str]]
) -> dict[int, set[str]]:
    # 와일드카드 매칭: 첫/끝 글자만 일치 (이*주 형태), 정확한 매칭에 없던 행만 추가
    name_to_wildcards = {name: generate_wildcard_patterns(name) for name in target_names}
    wildcard_matches: dict[int, set[str]] = {}

    for idx, row in df.iterrows():
        if idx in exact_matches:
            continue

        row_text = "|".join(str(v) for v in row.values if pd.notna(v))
        for name in target_names:
            for pattern in name_to_wildcards[name]:
                first = pattern[0]
                last = pattern[-1]
                found = False
                for i in range(len(row_text) - 2):
                    if row_text[i] == first and row_text[i + 2] == last:
                        found = True
                        break
                if found:
                    wildcard_matches.setdefault(idx, set()).add(name)
                    break

    return wildcard_matches


def build_result_df(df: pd.DataFrame, matches: dict[int, set[str]]) -> pd.DataFrame:
    rows = []
    for idx in sorted(matches.keys()):
        row_data = [str(v) if pd.notna(v) else "" for v in df.loc[idx].tolist()]
        matched_names = ", ".join(sorted(matches[idx]))
        rows.append(row_data + [matched_names])
    return pd.DataFrame(rows, columns=list(df.columns) + ["매칭된_이름"])


def main() -> None:
    df = pd.read_excel(INPUT_FILE, dtype=str)
    print(f"전체 데이터: {len(df)}행")

    # Step 1: 정확한 매칭
    exact_matches = find_exact_matches(df, TARGET_NAMES)
    exact_df = build_result_df(df, exact_matches)
    print(f"정확한 매칭: {len(exact_df)}행")

    # Step 2: 와일드카드 매칭 (정확한 매칭에 잡히지 않은 행 대상)
    wildcard_matches = find_wildcard_matches(df, TARGET_NAMES, exact_matches)
    wildcard_df = build_result_df(df, wildcard_matches)
    print(f"와일드카드 매칭: {len(wildcard_df)}행")

    # Step 3: 저장
    exact_df.to_excel(OUTPUT_EXACT_FILE, engine="openpyxl", index=False)
    wildcard_df.to_excel(OUTPUT_WILDCARD_FILE, engine="openpyxl", index=False)

    print(f"\n정확한 매칭 파일: {OUTPUT_EXACT_FILE} ({len(exact_df)}행)")
    print(f"와일드카드 매칭 파일: {OUTPUT_WILDCARD_FILE} ({len(wildcard_df)}행)")

    # Step 4: 와일드카드에서 추가로 발견된 이름 요약
    from collections import Counter
    all_wildcard_names = []
    for names in wildcard_matches.values():
        all_wildcard_names.extend(names)
    wildcard_counts = Counter(all_wildcard_names)
    if wildcard_counts:
        print("\n와일드카드에서 추가 발견된 이름:")
        for name, cnt in wildcard_counts.most_common():
            print(f"  {name}: {cnt}")


if __name__ == "__main__":
    main()
