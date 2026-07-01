#!/usr/bin/env python3
# [Flow: Step 1 (test_2p.pdf 로드) -> Step 2 (paddleocr_service /api/convert 호출) -> Step 3 (폴링) -> Step 4 (결과 출력)]
# PaddleOCR AI Studio API 폴백 테스트 스크립트
import sys
import time
from pathlib import Path

import requests

# AI Studio API 직접 호출 (paddleocr_service 없이 테스트)
API_URL = "https://paddleocr.aistudio-app.com/api/v2/ocr/jobs"
API_TOKEN = "2819fc79a865386ea31e6ee09bfdc88096ae2505"
MODEL = "PaddleOCR-VL-1.6"

def test_aistudio_direct(pdf_path: Path) -> None:
    """AI Studio API에 직접 PDF를 업로드하여 폴백 결과를 확인한다.

    [Flow: Step 1 (PDF 업로드 + job 제출) -> Step 2 (5초 간격 폴링) -> Step 3 (JSONL 다운로드) -> Step 4 (markdown 출력)]
    """
    print(f"[test] AI Studio API 직접 호출 테스트: {pdf_path.name}")
    print(f"[test] 파일 크기: {pdf_path.stat().st_size / 1024 / 1024:.1f}MB")

    headers = {"Authorization": f"bearer {API_TOKEN}"}
    optional_payload = {
        "useDocOrientationClassify": False,
        "useDocUnwarping": False,
        "useChartRecognition": False,
    }
    data = {"model": MODEL, "optionalPayload": __import__("json").dumps(optional_payload)}

    # Step 1: job 제출
    print("[test] Step 1: job 제출 중...")
    with open(pdf_path, "rb") as f:
        files = {"file": (pdf_path.name, f)}
        resp = requests.post(API_URL, headers=headers, data=data, files=files, timeout=300)

    if resp.status_code != 200:
        print(f"[test] FAIL: job 제출 실패 HTTP {resp.status_code}: {resp.text[:300]}")
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
        if elapsed > 1800:
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
            print(f"[test] job 완료: elapsed={elapsed:.0f}s, jsonUrl={json_url[:80]}...")
            # Step 3: JSONL 다운로드
            print("[test] Step 3: JSONL 다운로드...")
            jr = requests.get(json_url, timeout=120)
            jr.raise_for_status()
            lines = [l.strip() for l in jr.text.strip().split("\n") if l.strip()]
            print(f"[test] JSONL 라인 수: {len(lines)}")

            # Step 4: 결과 출력
            print("[test] Step 4: 결과 파싱...")
            import json
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
                    print(f"\n{'='*60}")
                    print(f"[test] Page {page_num} (text length={len(md_text)})")
                    print(f"{'='*60}")
                    # 처음 500자만 출력
                    print(md_text[:500])
                    if len(md_text) > 500:
                        print(f"... ({len(md_text) - 500}자 더 있음)")

            print(f"\n[test] 총 {page_num}페이지 변환 완료")
            return

        if state == "failed":
            err = d.get("errorMsg", "알 수 없는 오류")
            print(f"[test] FAIL: job 실패: {err}")
            return

        print(f"[test] 폴링 중: state={state}, elapsed={elapsed:.0f}s")
        time.sleep(5)


if __name__ == "__main__":
    pdf = Path("/Users/jun16/repo/chungu/test_2p.pdf")
    if not pdf.exists():
        print(f"파일을 찾을 수 없음: {pdf}")
        sys.exit(1)
    test_aistudio_direct(pdf)
