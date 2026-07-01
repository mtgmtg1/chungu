#!/usr/bin/env python3
# [Flow: Step 1 (PNG 업로드) -> Step 2 (폴링) -> Step 3 (JSONL 다운로드) -> Step 4 (markdown 출력)]
# PaddleOCR AI Studio API 테스트 — 단일 페이지 PNG
import json
import time
from pathlib import Path

import requests

API_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
API_TOKEN = "2819fc79a865386ea31e6ee09bfdc88096ae2505"
MODEL = "PaddleOCR-VL-1.6"


def test_image(image_path: Path) -> None:
    """AI Studio API에 이미지를 업로드하여 OCR 결과를 확인한다.

    [Flow: Step 1 (이미지 업로드 + job 제출) -> Step 2 (5초 간격 폴링) -> Step 3 (JSONL 다운로드) -> Step 4 (markdown 출력)]
    """
    print(f"[test] 이미지: {image_path.name} ({image_path.stat().st_size / 1024 / 1024:.1f}MB)")

    headers = {"Authorization": f"bearer {API_TOKEN}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    data = {"model": MODEL, "optionalPayload": json.dumps(optional_payload)}

    # Step 1: job 제출
    print("[test] Step 1: job 제출 중...")
    with open(image_path, "rb") as f:
        files = {"file": (image_path.name, f)}
        resp = requests.post(API_URL, headers=headers, data=data, files=files, timeout=300)

    if resp.status_code != 200:
        print(f"[test] FAIL: HTTP {resp.status_code}: {resp.text[:300]}")
        return

    job_id = resp.json().get("data", {}).get("jobId")
    if not job_id:
        print(f"[test] FAIL: jobId 없음: {resp.text[:300]}")
        return

    print(f"[test] job 제출 성공: jobId={job_id}")

    # Step 2: 폴링
    print("[test] Step 2: 폴링 시작...")
    poll_url = f"{API_URL}/{job_id}"
    start = time.monotonic()

    while True:
        elapsed = time.monotonic() - start
        if elapsed > 600:
            print(f"[test] FAIL: 타임아웃 {elapsed:.0f}s")
            return

        try:
            r = requests.get(poll_url, headers=headers, timeout=30)
        except Exception as e:
            print(f"[test] 폴링 실패, 재시도: {e}")
            time.sleep(5)
            continue

        if r.status_code != 200:
            print(f"[test] 폴링 HTTP {r.status_code}, 재시도...")
            time.sleep(5)
            continue

        d = r.json().get("data", {})
        state = d.get("state", "")

        if state == "done":
            json_url = d.get("resultUrl", {}).get("jsonUrl", "")
            print(f"[test] job 완료: elapsed={elapsed:.0f}s")
            print(f"[test] jsonUrl: {json_url[:100]}...")

            # Step 3: JSONL 다운로드
            print("[test] Step 3: JSONL 다운로드...")
            jr = requests.get(json_url, timeout=120)
            jr.raise_for_status()
            lines = [l.strip() for l in jr.text.strip().split("\n") if l.strip()]
            print(f"[test] JSONL 라인 수: {len(lines)}")

            # Step 4: 결과 출력
            print("[test] Step 4: 결과 파싱...")
            page_num = 0
            for line in lines:
                parsed = json.loads(line)
                result = parsed.get("result", {})
                if not isinstance(result, dict):
                    continue
                layout_results = result.get("layoutParsingResults", [])
                for lpr in layout_results:
                    page_num += 1
                    md = lpr.get("markdown", {})
                    md_text = md.get("text", "") if isinstance(md, dict) else ""
                    md_images = md.get("images", {}) if isinstance(md, dict) else {}
                    print(f"\n{'='*60}")
                    print(f"[test] Page {page_num} (text={len(md_text)} chars, images={len(md_images)})")
                    print(f"{'='*60}")
                    print(md_text[:1000])
                    if len(md_text) > 1000:
                        print(f"... ({len(md_text) - 1000} chars more)")

            print(f"\n[test] DONE: {page_num} pages")
            return

        if state == "failed":
            err = d.get("errorMsg", "unknown")
            print(f"[test] FAIL: job failed: {err}")
            return

        print(f"[test] 폴링: state={state}, elapsed={elapsed:.0f}s")
        time.sleep(5)


if __name__ == "__main__":
    img = Path("/tmp/test_2p_page1.png")
    if not img.exists():
        print(f"파일 없음: {img}")
        exit(1)
    test_image(img)
