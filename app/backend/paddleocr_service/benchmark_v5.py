#!/usr/bin/env python3
# [Flow: Step 1 (샘플 이미지 수집) -> Step 2 (설정별 파이프라인 풀 재초기화)
#       -> Step 3 (페이지 병렬 추론 + 시간 측정) -> Step 4 (한국어/표 품질 지표 집계)
#       -> Step 5 (설정 비교 표 출력 + 선택적 JSON 저장)]
"""PaddleOCR v5 로컬 CPU OCR 벤치마크 / 한국어 품질 A-B 도구.

두 가지 질문에 답하기 위한 도구다:
  1. **품질**: 표 셀·도장 인식기까지 한국어 모델로 교체(`PADDLEOCR_V5_PATCH_ALL_RECOGNIZERS`)하면
     표 안의 한국어가 실제로 살아나는가? (`--compare-korean-patch`)
  2. **처리량**: `PADDLEOCR_V5_POOL_SIZE`를 몇으로 두어야 하는가? (`--pool-sizes`)

사용 예 (컨테이너 안에서):
    python benchmark_v5.py --images /samples --compare-korean-patch
    python benchmark_v5.py --images /samples --pool-sizes 1,2,4,8,16 --json /tmp/bench.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tiff", ".tif", ".webp"}
HANGUL = re.compile(r"[가-힣]")
TAG = re.compile(r"<[^>]+>")


def _collect_images(paths: list[str], limit: int | None) -> list[Path]:
    """디렉터리/파일 목록에서 이미지 경로를 정렬해 수집한다."""
    found: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            found.extend(
                sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
            )
        elif path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES:
            found.append(path)
    if limit is not None:
        found = found[:limit]
    return found


def _hangul_count(text: str) -> int:
    """문자열의 한글 음절 수."""
    return len(HANGUL.findall(text or ""))


def _table_text(layout: dict) -> str:
    """layout의 표 블록에서 태그를 제거한 텍스트만 이어붙인다.

    표 셀 인식기가 한국어를 지원하는지 판별하는 핵심 지표다 — 본문(GeneralOCR)과
    표(TableRecognition.GeneralOCR)는 서로 다른 인식 모델을 쓸 수 있기 때문이다.
    """
    parts: list[str] = []
    for block in (layout or {}).get("parsing_res_list", []) or []:
        if not isinstance(block, dict) or block.get("block_label") != "table":
            continue
        content = block.get("block_content") or ""
        if isinstance(content, str):
            parts.append(TAG.sub(" ", content))
    return " ".join(parts)


def _page_metrics(page: dict[str, Any]) -> dict[str, int]:
    """한 페이지 결과에서 품질 지표를 뽑는다."""
    layout = page.get("layout") or {}
    blocks = layout.get("parsing_res_list") or []
    table_text = _table_text(layout)
    rec_texts = ((layout.get("overall_ocr_res") or {}).get("rec_texts")) or []
    return {
        "blocks": len(blocks),
        "table_blocks": sum(
            1 for b in blocks if isinstance(b, dict) and b.get("block_label") == "table"
        ),
        "rec_lines": len(rec_texts),
        "markdown_chars": len(page.get("markdown") or ""),
        "hangul_markdown": _hangul_count(page.get("markdown") or ""),
        "hangul_tables": _hangul_count(table_text),
        "table_chars": len(table_text.strip()),
    }


def _run_once(
    images: list[Path],
    pool_size: int,
    cpu_threads: int | None = None,
    capture_layout: bool = True,
) -> dict[str, Any]:
    """주어진 pool_size/cpu_threads로 전체 페이지를 추론하고 시간/품질 지표를 반환한다."""
    import ocr_v5

    ocr_v5.V5_POOL_SIZE = pool_size
    if cpu_threads is not None:
        ocr_v5.V5_CPU_THREADS = cpu_threads
    ocr_v5.reset_pool()

    # 워밍업: pool_size 개의 인스턴스를 **모두** 만들어둔다.
    # 인스턴스 하나만 워밍업하면 pool_size가 큰 설정은 측정 구간에 나머지 인스턴스의
    # 모델 로딩(인스턴스당 13개 모델)이 섞여 들어와 불리하게 나온다.
    warm_start = time.monotonic()
    warm_pages = [images[i % len(images)] for i in range(pool_size)]
    ocr_v5.predict_pages(warm_pages, layout_extractor=None, max_workers=pool_size)
    warmup_seconds = time.monotonic() - warm_start

    from main import _extract_layout_from_result

    start = time.monotonic()
    pages = ocr_v5.predict_pages(
        images,
        layout_extractor=_extract_layout_from_result if capture_layout else None,
        max_workers=pool_size,
    )
    elapsed = time.monotonic() - start

    per_page = [_page_metrics(p) for p in pages]
    totals = {k: sum(m[k] for m in per_page) for k in per_page[0]} if per_page else {}
    failed = sum(1 for p in pages if not (p.get("markdown") or "").strip())

    return {
        "pool_size": pool_size,
        "cpu_threads": ocr_v5.V5_CPU_THREADS,
        "spec": f"{pool_size}x{ocr_v5.V5_CPU_THREADS}",
        "pages": len(images),
        "warmup_seconds": round(warmup_seconds, 2),
        "elapsed_seconds": round(elapsed, 2),
        "seconds_per_page": round(elapsed / len(images), 2) if images else 0.0,
        "pages_per_minute": round(len(images) / elapsed * 60, 1) if elapsed else 0.0,
        "empty_pages": failed,
        "totals": totals,
    }


def _print_table(rows: list[dict[str, Any]], label_key: str, label_title: str) -> None:
    """결과 행들을 정렬된 표로 출력한다."""
    header = (
        f"{label_title:<22} {'pages':>6} {'sec':>8} {'sec/pg':>8} {'pg/min':>8} "
        f"{'empty':>6} {'rec_lines':>10} {'hangul_md':>10} {'hangul_tbl':>11} {'tables':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in rows:
        t = row.get("totals") or {}
        print(
            f"{str(row[label_key]):<22} {row['pages']:>6} {row['elapsed_seconds']:>8} "
            f"{row['seconds_per_page']:>8} {row['pages_per_minute']:>8} {row['empty_pages']:>6} "
            f"{t.get('rec_lines', 0):>10} {t.get('hangul_markdown', 0):>10} "
            f"{t.get('hangul_tables', 0):>11} {t.get('table_blocks', 0):>7}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="PaddleOCR v5 CPU 벤치마크 / 한국어 품질 A-B")
    parser.add_argument("--images", nargs="+", required=True, help="이미지 파일 또는 디렉터리")
    parser.add_argument("--limit", type=int, default=None, help="사용할 최대 페이지 수")
    parser.add_argument(
        "--pool-sizes",
        default="",
        help="쉼표로 구분한 pool size 목록 (예: 1,2,4,8). 생략하면 현재 설정으로 1회만 실행",
    )
    parser.add_argument(
        "--pool-specs",
        default="",
        help=(
            "pool_size x cpu_threads 조합 목록 (예: 4x16,8x8,16x5). "
            "총 스레드 수를 물리 코어에 맞춰 고정한 채 인스턴스 수를 바꿔볼 때 사용"
        ),
    )
    parser.add_argument(
        "--compare-korean-patch",
        action="store_true",
        help="표/도장 인식기 한국어 교체 ON/OFF를 비교한다",
    )
    parser.add_argument("--json", dest="json_path", default="", help="결과 JSON 저장 경로")
    parser.add_argument("--quiet", action="store_true", help="paddle 로그 억제")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.ERROR if args.quiet else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    images = _collect_images(args.images, args.limit)
    if not images:
        print("이미지를 찾지 못했다", file=sys.stderr)
        return 1
    print(f"샘플 {len(images)}장: {images[0].name} … {images[-1].name}\n")

    import ocr_v5

    results: dict[str, Any] = {"pages": len(images), "runs": []}

    if args.compare_korean_patch:
        rows = []
        for patch_all in (False, True):
            ocr_v5.V5_PATCH_ALL_RECOGNIZERS = patch_all
            # 설정 캐시를 지워 다음 빌드에서 새로 만들도록 한다.
            ocr_v5._patched_config_path = None
            ocr_v5._patched_config_failed = False
            label = "표/도장까지 한국어" if patch_all else "본문만 한국어(기본)"
            print(f"── {label} ──")
            row = _run_once(images, ocr_v5.V5_POOL_SIZE)
            row["variant"] = label
            row["patch_all_recognizers"] = patch_all
            rows.append(row)
            results["runs"].append(row)
            print()
        _print_table(rows, "variant", "설정")
        if len(rows) == 2:
            before, after = rows[0]["totals"], rows[1]["totals"]
            delta = after.get("hangul_tables", 0) - before.get("hangul_tables", 0)
            print(
                f"\n표 안 한글: {before.get('hangul_tables', 0)} → {after.get('hangul_tables', 0)} "
                f"({delta:+d})"
            )

    specs: list[tuple[int, int]] = []
    for raw in args.pool_specs.split(","):
        raw = raw.strip()
        if not raw:
            continue
        pool_text, _, threads_text = raw.partition("x")
        specs.append((int(pool_text), int(threads_text) if threads_text else ocr_v5.V5_CPU_THREADS))
    if specs:
        rows = []
        for pool_size, cpu_threads in specs:
            print(f"── pool_size={pool_size} cpu_threads={cpu_threads} (총 {pool_size * cpu_threads} 스레드) ──")
            row = _run_once(images, pool_size, cpu_threads)
            rows.append(row)
            results["runs"].append(row)
            print()
        _print_table(rows, "spec", "pool x threads")
        best = max(rows, key=lambda r: r["pages_per_minute"])
        print(f"\n최고 처리량: {best['spec']} ({best['pages_per_minute']} pages/min)")

    pool_sizes = [int(v) for v in args.pool_sizes.split(",") if v.strip()]
    if pool_sizes:
        rows = []
        for size in pool_sizes:
            print(f"── pool_size={size} ──")
            row = _run_once(images, size)
            rows.append(row)
            results["runs"].append(row)
            print()
        _print_table(rows, "pool_size", "pool_size")
        best = max(rows, key=lambda r: r["pages_per_minute"])
        print(f"\n최고 처리량: pool_size={best['pool_size']} ({best['pages_per_minute']} pages/min)")

    if not pool_sizes and not specs and not args.compare_korean_patch:
        row = _run_once(images, ocr_v5.V5_POOL_SIZE)
        results["runs"].append(row)
        _print_table([row], "pool_size", "pool_size")

    if args.json_path:
        Path(args.json_path).write_text(json.dumps(results, ensure_ascii=False, indent=2))
        print(f"\nJSON 저장: {args.json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
