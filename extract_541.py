#!/usr/bin/env python3
# [Flow: Step 1 (load 통합 CSV) -> Step 2 (build 연번 index) -> Step 3 (대장 구간 순서대로 행 수집) -> Step 4 (541행 검증) -> Step 5 (CSV+MD 저장)]
import csv
from pathlib import Path

BASE = Path("/Users/jun16/repo/chungu")
SRC_CSV = BASE / "ocr_output" / "거래내역_통합.csv"
OUT_CSV = BASE / "신탁전환금_541행.csv"
OUT_MD = BASE / "신탁전환금_541행.md"

COLUMNS = [
    "페이지", "연번", "구분", "계좌번호", "거래일자",
    "출금금액(원)", "입금금액(원)", "거래기록사항", "이체메모", "계정",
]
OUT_COLUMNS = ["대장순번"] + COLUMNS

# 대장 25개 구간: (순번, 시작, 끝, [추가번호])
LEDGER = [
    (1, 2439, 2458, []),
    (2, 3706, 3806, []),
    (3, 3825, 3891, []),
    (4, 3937, 3954, []),
    (5, 3990, 4007, []),
    (6, 4068, 4077, []),
    (7, 4208, 4267, []),
    (8, 4853, 4855, []),
    (9, 4980, 5031, []),
    (10, 5038, 5067, []),
    (11, 5086, 5115, []),
    (12, 5135, 5143, []),
    (13, 5148, 5155, []),
    (14, 5187, 5192, []),
    (15, 5224, 5227, []),
    (16, 5267, 5282, []),
    (17, 5791, 5794, []),
    (18, 5790, 5829, [5831]),
    (19, 5832, 5837, []),
    (20, 5870, 5874, []),
    (21, 5891, 5896, []),
    (22, 6742, 6743, []),
    (23, 6744, 6745, []),
    (24, 8199, 8210, []),
    (25, 9299, 9309, []),
]


def to_int(s):
    s = (s or "").strip().replace(",", "")
    return int(s) if s.isdigit() else None


def load_rows():
    with open(SRC_CSV, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def build_index(rows):
    # 연번 -> 첫 번째 매칭 행 (테이블 중복은 첫 행만 사용)
    index = {}
    for row in rows:
        serial = to_int(row["연번"])
        if serial is None or serial in index:
            continue
        index[serial] = row
    return index


def collect_ledger_rows(index):
    collected = []
    per_group = []
    for group_no, start, end, extras in LEDGER:
        serials = list(range(start, end + 1)) + extras
        count = 0
        for serial in serials:
            row = index.get(serial)
            if row is None:
                continue
            out = {"대장순번": group_no}
            out.update({c: row.get(c, "") for c in COLUMNS})
            collected.append(out)
            count += 1
        per_group.append((group_no, start, end, extras, len(serials), count))
    return collected, per_group


def write_csv(rows):
    with open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_md(rows):
    lines = ["| " + " | ".join(OUT_COLUMNS) + " |",
             "| " + " | ".join([":---"] * len(OUT_COLUMNS)) + " |"]
    for r in rows:
        cells = [str(r.get(c, "")).replace("|", "\\|") for c in OUT_COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    rows = load_rows()
    index = build_index(rows)
    collected, per_group = collect_ledger_rows(index)

    print("[구간별 개수] 순번 | 범위 | 기대 | 추출")
    for g, s, e, ex, expected, actual in per_group:
        extra_str = f"+{ex}" if ex else ""
        flag = "" if expected == actual else "  <-- 불일치"
        print(f"  {g:2d} | {s}~{e}{extra_str} | {expected} | {actual}{flag}")

    write_csv(collected)
    write_md(collected)

    print(f"\n[done] 총 추출 행: {len(collected)}")
    print(f"[done] CSV -> {OUT_CSV}")
    print(f"[done] MD  -> {OUT_MD}")
    # 겹침(5791~5794) 2회 등장 검증
    from collections import Counter
    serial_cnt = Counter(to_int(r["연번"]) for r in collected)
    overlap = {s: serial_cnt[s] for s in (5791, 5792, 5793, 5794)}
    print(f"[verify] 겹침 연번 등장 횟수: {overlap}")


if __name__ == "__main__":
    main()
