#!/usr/bin/env python3
# [Flow: Step 1 (CLI parse) -> Step 2 (PNG -> Tesseract raw text) -> Step 3 (resume scan) -> Step 4 (text -> qwer3.6 CSV structuring) -> Step 5 (merge CSVs)]
import argparse
import base64
import csv
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

DEFAULT_PDF = "/Users/jun16/repo/chungu/거래내역서.pdf"
DEFAULT_OUT = "/Users/jun16/repo/chungu/ocr_output"
DEFAULT_ENDPOINT = "http://192.168.1.69:18000/v1/chat/completions"
DEFAULT_MODEL = "cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit"

STRUCTURE_PROMPT = (
    "아래는 한 금융 거래내역 PDF 페이지의 OCR 원문입니다. "
    "이를 9개 컬럼(연번, 구분, 계좌번호, 거래일자, 출금금액, 입금금액, 거래기록사항, 이체메모, 계정)의 CSV로 변환하세요.\n"
    "규칙:\n"
    "- CSV 헤더는: 연번,구분,계좌번호,거래일자,출금금액,입금금액,거래기록사항,이체메모,계정\n"
    "- 설명, 마크다운, 코드 블록은 절대 출력하지 마세요. CSV 데이터만 출력하세요.\n"
    "- 각 행은 한 줄의 CSV 레코드입니다.\n"
    "- 금액의 콤마는 유지하세요.\n"
    "- 빈 셀은 공백 또는 비워두세요.\n"
    "- OCR 오류가 있으면 가능한 한 바로잡아 표에 담으세요.\n"
    "- 거래내역 데이터가 없으면 헤더만 출력하세요.\n\n"
    "OCR 원문:\n"
    "{text}"
)

SUMMARY_PROMPT = (
    "아래는 한 금융 거래내역 PDF 1페이지의 OCR 원문입니다. "
    "상단 요약표(연번, 계정, 지출 금액, 비고)를 CSV로 변환하세요.\n"
    "규칙:\n"
    "- CSV 헤더는: 연번,계정,지출금액,비고\n"
    "- 설명, 마크다운, 코드 블록은 절대 출력하지 마세요. CSV 데이터만 출력하세요.\n"
    "- 요약표가 없으면 헤더만 출력하세요.\n\n"
    "OCR 원문:\n"
    "{text}"
)


def parse_args():
    parser = argparse.ArgumentParser(description="Hybrid OCR: Tesseract raw + Qwen3.6 structuring")
    parser.add_argument("--pdf", default=DEFAULT_PDF)
    parser.add_argument("--out", default=DEFAULT_OUT)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--ocr-workers", type=int, default=4, help="Tesseract parallel workers")
    parser.add_argument("--llm-workers", type=int, default=2, help="b1 LLM parallel workers")
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--page-start", type=int, default=1)
    parser.add_argument("--page-end", type=int, default=0)
    parser.add_argument("--no-render", action="store_true")
    parser.add_argument("--no-ocr", action="store_true", help="skip Tesseract, use existing text files")
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def render_pdf(pdf_path, img_dir, dpi=150, start=1, end=0):
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


def tesseract_ocr(image_path, text_path):
    """Run Tesseract on a PNG and save the raw text."""
    if text_path.exists():
        return text_path
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", "kor+eng"],
        capture_output=True,
        text=True,
    )
    text_path.write_text(result.stdout, encoding="utf-8")
    return text_path


def find_page_number(filename):
    m = re.search(r"page-(\d+)\.png", filename.name)
    if m:
        return int(m.group(1))
    return None


def call_llm(prompt, endpoint, model, max_tokens=2000, retries=3):
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            msg = result["choices"][0]["message"]
            return msg.get("content") or "", result["choices"][0].get("finish_reason")
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(last_err)


def extract_csv(content):
    """Extract CSV block from model output."""
    if not content:
        return ""
    # Remove markdown code fences
    content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content)
    lines = [line.strip() for line in content.strip().splitlines()]
    csv_lines = []
    for line in lines:
        if line.startswith("연번") or re.match(r"\d+,|[^,]+,", line):
            csv_lines.append(line)
    return "\n".join(csv_lines)


def structure_page(page_num, text_path, endpoint, model, max_tokens, out_dir, force):
    csv_path = Path(out_dir) / "csv" / f"page_{page_num:03d}.csv"
    summary_csv_path = Path(out_dir) / "csv" / f"page_{page_num:03d}_summary.csv"
    if not force and csv_path.exists():
        return {"page": page_num, "status": "skipped"}
    try:
        text = text_path.read_text(encoding="utf-8")
        if not text.strip():
            csv_path.write_text("연번,구분,계좌번호,거래일자,출금금액,입금금액,거래기록사항,이체메모,계정\n", encoding="utf-8")
            return {"page": page_num, "status": "ok", "finish": "empty"}
        prompt = STRUCTURE_PROMPT.format(text=text)
        content, finish = call_llm(prompt, endpoint, model, max_tokens)
        csv_block = extract_csv(content)
        csv_path.write_text(csv_block + "\n", encoding="utf-8")
        if page_num == 1:
            summary_prompt = SUMMARY_PROMPT.format(text=text)
            summary_content, _ = call_llm(summary_prompt, endpoint, model, max_tokens)
            summary_csv = extract_csv(summary_content)
            summary_csv_path.write_text(summary_csv + "\n", encoding="utf-8")
        return {"page": page_num, "status": "ok", "finish": finish}
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
    (out_dir / "text").mkdir(exist_ok=True)
    (out_dir / "csv").mkdir(exist_ok=True)
    error_log = out_dir / "_errors_hybrid.log"

    if not args.no_render:
        start = args.page_start if args.page_start > 1 else 1
        end = args.page_end if args.page_end > 0 else 0
        render_pdf(args.pdf, out_dir / "img", args.dpi, start, end)

    images = sorted((out_dir / "img").glob("page-*.png"))
    if not images:
        print("[error] no images found", flush=True)
        sys.exit(1)

    pages = []
    for img in images:
        pn = find_page_number(img)
        if pn is None:
            continue
        if pn < args.page_start or (args.page_end > 0 and pn > args.page_end):
            continue
        pages.append((pn, img))
    pages.sort(key=lambda x: x[0])
    print(f"[ocr] {len(pages)} pages to OCR with Tesseract", flush=True)

    # Step 1: Tesseract OCR
    if not args.no_ocr:
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=args.ocr_workers) as executor:
            futures = {
                executor.submit(tesseract_ocr, img, out_dir / "text" / f"page_{pn:03d}.txt"): pn
                for pn, img in pages
            }
            for future in as_completed(futures):
                pn = futures[future]
                try:
                    future.result()
                except Exception as e:
                    print(f"[ERR tesseract] page {pn}: {e}", flush=True)
                    log_error(error_log, {"page": pn, "stage": "tesseract", "error": str(e)})
        print(f"[tesseract] done in {time.time() - t0:.0f}s", flush=True)
    else:
        print("[tesseract] skipped (--no-ocr)", flush=True)

    # Step 2: LLM structuring
    print(f"[llm] structuring {len(pages)} pages with {args.llm_workers} workers", flush=True)
    completed = 0
    skipped = 0
    failed = 0
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.llm_workers) as executor:
        futures = {
            executor.submit(
                structure_page, pn, out_dir / "text" / f"page_{pn:03d}.txt",
                args.endpoint, args.model, args.max_tokens, out_dir, args.force
            ): pn for pn, img in pages
        }
        for future in as_completed(futures):
            pn = futures[future]
            try:
                result = future.result()
                if result["status"] == "ok":
                    completed += 1
                    print(f"[ok] page {pn:03d} ({result.get('finish')})", flush=True)
                elif result["status"] == "skipped":
                    skipped += 1
                    print(f"[skip] page {pn:03d} exists", flush=True)
                else:
                    failed += 1
                    print(f"[ERR] page {pn:03d}: {result.get('error')}", flush=True)
                    log_error(error_log, {"page": pn, "stage": "llm", "error": result.get("error")})
            except Exception as e:
                failed += 1
                print(f"[ERR] page {pn:03d}: {e}", flush=True)
                log_error(error_log, {"page": pn, "stage": "llm", "error": str(e)})
            elapsed = time.time() - t0
            done = completed + skipped + failed
            pct = done / len(pages) * 100
            print(f"[progress] {done}/{len(pages)} ({pct:.1f}%) | ok={completed} skip={skipped} err={failed} | elapsed={elapsed:.0f}s", flush=True)

    print(f"[done] completed={completed} skipped={skipped} failed={failed}", flush=True)


if __name__ == "__main__":
    main()
