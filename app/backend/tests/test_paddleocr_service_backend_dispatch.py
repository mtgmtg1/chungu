#!/usr/bin/env python3
# [Flow: Step 1 (FastAPI TestClient 준비) -> Step 2 (PADDLEOCR_BACKEND=local_v5로 전환)
#       -> Step 3 (/api/convert, /api/convert/batch, /api/convert/pdf 호출)
#       -> Step 4 (task 완료 폴링) -> Step 5 (AI Studio 경로와 동일한 응답 스키마 검증)]
"""paddleocr_service의 OCR 백엔드 디스패치 통합 테스트.

로컬 PP-OCRv5 전환의 핵심은 "클라이언트가 보는 /api/convert* 계약이 백엔드와 무관하게
동일하다"는 것이다. 이 파일은 실제 추론을 가짜 파이프라인으로 대체한 상태에서
세 엔드포인트가 모두 로컬 백엔드로 라우팅되고, core/paddleocr_client.py가 읽는 필드
(markdown / layout / page_angles / pages)가 채워지는지를 검증한다.
"""
import io
import os
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import fitz
from fastapi.testclient import TestClient

from backend.paddleocr_service import main as svc
from backend.paddleocr_service import ocr_v5

POLL_TIMEOUT_SECONDS = 20.0


class _FakeRes:
    """PP-StructureV3 결과 객체 더블."""

    def __init__(self, text: str):
        self.json = {
            "parsing_res_list": [
                {"block_label": "text", "block_content": text, "block_bbox": [10, 20, 110, 60]}
            ],
            "overall_ocr_res": {"rec_texts": [text], "rec_boxes": [[10, 20, 110, 60]]},
            "doc_preprocessor_res": {"angle": 0},
        }
        self.markdown = {"markdown_texts": text}


@pytest.fixture
def local_v5(monkeypatch):
    """백엔드를 local_v5로 고정하고, 추론을 가짜 파이프라인으로 대체한다."""
    monkeypatch.setattr(svc, "OCR_BACKEND", svc.BACKEND_LOCAL_V5)
    # 로컬 실패 시 외부 API로 새는 경로를 차단해, 테스트가 네트워크를 타지 않게 한다.
    monkeypatch.setattr(svc, "LOCAL_FALLBACK_TO_AISTUDIO", False)
    monkeypatch.setattr(svc, "AISTUDIO_API_TOKEN", "")

    counter = {"n": 0}

    class _Pipeline:
        def predict(self, path, **_kwargs):
            counter["n"] += 1
            return [_FakeRes(f"page{counter['n']}")]

    pipeline = _Pipeline()

    class _Lease:
        def __enter__(self):
            return pipeline

        def __exit__(self, *_exc):
            return None

    monkeypatch.setattr(ocr_v5, "_Lease", _Lease)
    return counter


@pytest.fixture
def client():
    return TestClient(svc.app)


def _png_bytes(size=(200, 100)) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, "white").save(buf, "PNG")
    return buf.getvalue()


def _pdf_bytes(pages: int) -> bytes:
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=100)
    data = doc.tobytes()
    doc.close()
    return data


def _poll(client: TestClient, url: str) -> dict:
    """task가 done/error가 될 때까지 폴링하고 최종 payload를 반환한다."""
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        resp = client.get(url)
        assert resp.status_code == 200, resp.text
        payload = resp.json()
        if payload["status"] in ("done", "error"):
            return payload
        time.sleep(0.05)
    pytest.fail(f"task did not finish within {POLL_TIMEOUT_SECONDS}s: {url}")


def test_health_reports_selected_backend(client, local_v5):
    """/health가 현재 백엔드와 인식 모델을 노출해 배포 확인에 쓸 수 있어야 한다."""
    payload = client.get("/health").json()
    assert payload["status"] == "ok"
    assert payload["backend"] == svc.BACKEND_LOCAL_V5
    assert payload["rec_model"] == ocr_v5.V5_REC_MODEL


def test_api_convert_routes_to_local_v5(client, local_v5):
    """[Flow: Step 1 (이미지 1장 업로드) -> Step 2 (task 폴링)
          -> Step 3 (markdown/layout/page_angles가 채워졌는지 검증)]

    core/paddleocr_client.convert_image_with_layout()가 읽는 필드 3개가 모두 필요하다.
    """
    resp = client.post(
        "/api/convert",
        files={"file": ("page-001.png", _png_bytes(), "image/png")},
        data={"capture_layout": "true"},
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    payload = _poll(client, f"/api/convert/status/{task_id}")
    assert payload["status"] == "done", payload
    result = payload["result"]
    assert result["markdown"] == "page1"
    assert result["page_count"] == 1
    assert result["file_type"] == "image"
    assert len(result["layout"]) == 1
    assert result["page_angles"] == [0]
    # bbox는 0~1 정규화 좌표여야 한다 (AI Studio 경로와 동일 규약).
    bbox = result["layout"][0]["parsing_res_list"][0]["block_bbox"]
    assert all(0.0 <= v <= 1.0 for v in bbox), bbox


def test_api_convert_without_capture_layout_omits_layout(client, local_v5):
    """capture_layout=false면 layout을 싣지 않아 응답 크기를 낭비하지 않는다."""
    resp = client.post("/api/convert", files={"file": ("p.png", _png_bytes(), "image/png")})
    task_id = resp.json()["task_id"]
    result = _poll(client, f"/api/convert/status/{task_id}")["result"]
    assert result["layout"] == []


def test_api_convert_batch_returns_per_page_results(client, local_v5):
    """[Flow: Step 1 (이미지 3장 배치 업로드) -> Step 2 (폴링)
          -> Step 3 (업로드 순서대로 per-page 결과가 오는지 검증)]"""
    files = [("files", (f"page-{i:03d}.png", _png_bytes(), "image/png")) for i in range(1, 4)]
    resp = client.post("/api/convert/batch", files=files)
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    payload = _poll(client, f"/api/convert/batch/status/{task_id}")
    assert payload["status"] == "done", payload
    result = payload["result"]
    assert result["page_count"] == 3
    assert len(result["pages"]) == 3
    for page in result["pages"]:
        assert page["markdown"]
        assert page["layout"]
        assert page["page_angle"] == 0


def test_api_convert_pdf_renders_and_returns_per_page(client, local_v5):
    """[Flow: Step 1 (2페이지 PDF 업로드) -> Step 2 (서비스가 페이지 이미지로 렌더링)
          -> Step 3 (페이지 수만큼 per-page 결과 반환)]

    로컬 백엔드는 PDF도 항상 이미지로 렌더링하므로 bbox 좌표 규약이 이미지 경로와 같아진다.
    """
    resp = client.post(
        "/api/convert/pdf",
        files={"file": ("doc.pdf", _pdf_bytes(2), "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    task_id = resp.json()["task_id"]

    payload = _poll(client, f"/api/convert/pdf/status/{task_id}")
    assert payload["status"] == "done", payload
    assert payload["result"]["page_count"] == 2


def test_local_backend_allows_batches_beyond_aistudio_limit(client, local_v5):
    """로컬 백엔드는 AI Studio의 10페이지/job 제한을 받지 않는다."""
    assert svc._effective_batch_max_pages() > svc.BATCH_MAX_PAGES
    files = [("files", (f"p{i}.png", _png_bytes(), "image/png")) for i in range(svc.BATCH_MAX_PAGES + 2)]
    resp = client.post("/api/convert/batch", files=files)
    assert resp.status_code == 200, resp.text


def test_aistudio_backend_still_requires_token(client, monkeypatch):
    """백엔드를 aistudio로 되돌리면 토큰 없이는 503을 돌려준다 (기존 동작 유지)."""
    monkeypatch.setattr(svc, "OCR_BACKEND", svc.BACKEND_AISTUDIO)
    monkeypatch.setattr(svc, "AISTUDIO_API_TOKEN", "")
    resp = client.post("/api/convert", files={"file": ("p.png", _png_bytes(), "image/png")})
    assert resp.status_code == 503


def test_api_convert_rejects_non_image(client, local_v5):
    """/api/convert는 이미지 전용 계약을 유지한다 (PDF는 /api/convert/pdf)."""
    resp = client.post("/api/convert", files={"file": ("doc.pdf", _pdf_bytes(1), "application/pdf")})
    assert resp.status_code == 400


def test_local_failure_sets_error_without_external_fallback(client, local_v5, monkeypatch):
    """[Flow: Step 1 (추론이 예외를 던지도록 설정) -> Step 2 (폴백 비활성)
          -> Step 3 (task가 error로 끝나는지 검증)]"""

    def _boom(*_a, **_k):
        raise RuntimeError("engine down")

    monkeypatch.setattr(ocr_v5, "predict_pages", _boom)
    resp = client.post("/api/convert", files={"file": ("p.png", _png_bytes(), "image/png")})
    task_id = resp.json()["task_id"]
    payload = _poll(client, f"/api/convert/status/{task_id}")
    assert payload["status"] == "error"
    assert "engine down" in (payload["error"] or "")
