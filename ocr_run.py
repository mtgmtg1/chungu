#!/usr/bin/env python3
# [Flow: Step 1 (CLI parse + env) -> Step 2 (PDF -> PNG rendering) -> Step 3 (resume scan) -> Step 4 (OCR pages concurrently) -> Step 5 (log errors)]
import argparse
import base64
import io
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# Configuration constants
DEFAULT_PDF = "/Users/jun16/repo/chungu/거래내역서.pdf"
DEFAULT_OUT = "/Users/jun16/repo/chungu/ocr_output"
DEFAULT_ENDPOINT = "http://192.168.1.69:18080/v1/chat/completions"
DEFAULT_MODEL = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"

# OCR prompt for the detailed transaction table
DETAIL_PROMPT = (
    "이 페이지의 입출금 거래내역 표를 아래 9개 컬럼을 그대로 유지하는 마크다운 표로만 출력하세요. "
    "컬럼: 연번, 구분, 계좌번호, 거래일자, 출금금액(원), 입금금액(원), 거래기록사항, 이체메모, 계정. "
    "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
    "빈 셀은 공백으로 두고, 금액은 원본 숫자와 콤마를 그대로 쓰세요. "
    "헤더가 없는 페이지는 데이터만 표로 만드세요. "
    "표가 여러 개면 주 거래 상세표 하나만 출력하세요."
)

SUMMARY_PROMPT = (
    "이 페이지의 상단 요약표(연번, 계정, 지출 금액, 비고)를 마크다운 표로만 출력하세요. "
    "설명, 머리말, 마무리 문구는 절대 넣지 마세요. "
    "요약표가 없으면 빈 표(| 연번 | 계정 | 지출 금액 | 비고 |)만 출력하세요."
)


def parse_args():
    parser = argparse.ArgumentParser(description="OCR PDF pages via Qwen3.6 on b1")
    parser.add_argument("--pdf", default=DEFAULT_PDF, help="input PDF path")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output directory")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="vLLM chat completions endpoint")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model name")
    parser.add_argument("--dpi", type=int, default=150, help="rendering DPI (default 150)")
    parser.add_argument("--workers", type=int, default=6, help="concurrent OCR workers")
    parser.add_argument("--max-tokens", type=int, default=10000, help="max tokens per request")
    parser.add_argument("--page-start", type=int, default=1, help="first page to process")
    parser.add_argument("--page-end", type=int, default=0, help="last page (0 = all)")
    parser.add_argument("--pages", type=str, default="", help="comma-separated list of specific pages to process (e.g. 72,82,156)")
    parser.add_argument("--force", action="store_true", help="overwrite existing page files")
    parser.add_argument("--no-render", action="store_true", help="skip re-rendering PDF")
    return parser.parse_args()


def render_pdf(pdf_path, img_dir, dpi=150, start=1, end=0):
    """Convert PDF pages to PNG images."""
    print(f"[render] {pdf_path} @ {dpi} DPI -> {img_dir}", flush=True)
    img_dir = Path(img_dir)
    img_dir.mkdir(parents=True, exist_ok=True)
    args = ["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(img_dir / "page")]
    if end > 0:
        args = ["pdftoppm", "-f", str(start), "-l", str(end), "-r", str(dpi), "-png", str(pdf_path), str(img_dir / "page")]
    subprocess.run(args, check=True)
    files = sorted(img_dir.glob("page-*.png"))
    print(f"[render] generated {len(files)} image(s)", flush=True)
    return files


def find_page_number(filename):
    """Extract page number from rendered filenames like page-001.png"""
    m = re.search(r"page-(\d+)\.png", filename.name)
    if m:
        return int(m.group(1))
    return None


def encode_image(image_path, jpeg_quality=95):
    """Encode page image to base64 JPEG for smaller payload."""
    jpeg_path = image_path.with_suffix(".jpg")
    if not jpeg_path.exists():
        subprocess.run(
            ["magick", "convert", str(image_path), "-quality", str(jpeg_quality), str(jpeg_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    with open(jpeg_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_markdown_table(content):
    """Extract only the first markdown table from model output."""
    if not content:
        return ""
    content = content.strip()
    # Find first |...| line and capture until the table ends
    lines = content.splitlines()
    table_lines = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            table_lines.append(stripped)
            in_table = True
        elif in_table and not stripped:
            # blank line after table is acceptable; continue a few more lines
            continue
        elif in_table:
            # if we hit non-table line after table, stop
            break
    if table_lines:
        return "\n".join(table_lines)
    # Fallback: if no table found, return trimmed content
    return content


def call_ocr(image_path, endpoint, model, prompt, max_tokens=8000, retries=3):
    b64 = encode_image(image_path)
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=1200) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            msg = result["choices"][0]["message"]
            content = msg.get("content") or ""
            return content, result["choices"][0].get("finish_reason")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}"
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(last_err)


def process_one_page(page_num, image_path, endpoint, model, max_tokens, out_dir, force):
    """Process a single page: OCR detail table (and summary if page 1)."""
    md_path = Path(out_dir) / "pages" / f"page_{page_num:03d}.md"
    summary_path = Path(out_dir) / "pages" / f"page_{page_num:03d}_summary.md"
    if not force and md_path.exists():
        return {"page": page_num, "status": "skipped", "detail_path": str(md_path)}
    try:
        detail, finish = call_ocr(image_path, endpoint, model, DETAIL_PROMPT, max_tokens)
        detail_table = extract_markdown_table(detail)
        md_path.write_text(detail_table, encoding="utf-8")

        # For page 1, also extract the summary table at the top
        if page_num == 1:
            summary, _ = call_ocr(image_path, endpoint, model, SUMMARY_PROMPT, max_tokens)
            summary_table = extract_markdown_table(summary)
            summary_path.write_text(summary_table, encoding="utf-8")

        return {"page": page_num, "status": "ok", "finish_reason": finish, "detail_path": str(md_path)}
    except Exception as e:
        return {"page": page_num, "status": "error", "error": str(e)}


def log_error(error_path, record):
    with open(error_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main():
    args = parse_args()
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "pages").mkdir(exist_ok=True)
    (out_dir / "img").mkdir(exist_ok=True)
    error_log = out_dir / "_errors.log"

    # Render PDF to images
    if not args.no_render:
        start = args.page_start if args.page_start > 1 else 1
        end = args.page_end if args.page_end > 0 else 0
        render_pdf(args.pdf, out_dir / "img", args.dpi, start, end)
    else:
        print("[render] skipped (--no-render)", flush=True)

    images = sorted((out_dir / "img").glob("page-*.png"))
    if not images:
        print("[error] no images found", flush=True)
        sys.exit(1)

    # Filter page range
    target_pages = None
    if args.pages:
        target_pages = {int(p.strip()) for p in args.pages.split(",") if p.strip().isdigit()}
    pages = []
    for img in images:
        pn = find_page_number(img)
        if pn is None:
            continue
        if target_pages and pn not in target_pages:
            continue
        if pn < args.page_start:
            continue
        if args.page_end > 0 and pn > args.page_end:
            continue
        pages.append((pn, img))
    pages.sort(key=lambda x: x[0])
    print(f"[ocr] {len(pages)} page(s) to process (workers={args.workers}, max_tokens={args.max_tokens})", flush=True)

    completed = 0
    failed = 0
    skipped = 0
    start_time = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_one_page, pn, img, args.endpoint, args.model, args.max_tokens, out_dir, args.force): pn
            for pn, img in pages
        }
        for future in as_completed(futures):
            pn = futures[future]
            try:
                result = future.result()
                if result["status"] == "ok":
                    completed += 1
                    print(f"[ok] page {pn:03d} ({result.get('finish_reason')}) -> {result['detail_path']}", flush=True)
                elif result["status"] == "skipped":
                    skipped += 1
                    print(f"[skip] page {pn:03d} exists", flush=True)
                else:
                    failed += 1
                    err = result.get("error", "unknown")
                    print(f"[ERR] page {pn:03d}: {err}", flush=True)
                    log_error(error_log, {"page": pn, "error": err, "timestamp": time.time()})
            except Exception as e:
                failed += 1
                print(f"[ERR] page {pn:03d}: {e}", flush=True)
                log_error(error_log, {"page": pn, "error": str(e), "timestamp": time.time()})
            elapsed = time.time() - start_time
            done = completed + skipped + failed
            pct = done / len(pages) * 100
            print(f"[progress] {done}/{len(pages)} ({pct:.1f}%) | ok={completed} skip={skipped} err={failed} | elapsed={elapsed:.0f}s", flush=True)

    print(f"[done] completed={completed} skipped={skipped} failed={failed}", flush=True)
    if failed:
        print(f"[retry] re-run with: python3 ocr_run.py --no-render  (failed pages are in {error_log})", flush=True)


if __name__ == "__main__":
    main()
