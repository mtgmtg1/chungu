"""SelectiveGZipMiddleware 회귀 테스트.

[Flow: Step 1 (경로별 압축 제외 판정 검증) -> Step 2 (미들웨어 통합 동작 검증)]

전역 GZipMiddleware 를 붙이면 SSE 스트리밍이 deflate 버퍼에 갇힌다.
이 테스트는 스트리밍 경로가 압축 대상에서 빠지는지, 반대로 번들 자산은
확실히 압축되는지를 고정한다.
"""
import asyncio

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from backend.main import SelectiveGZipMiddleware, _should_skip_compression


def _scope(path: str) -> dict:
    return {"type": "http", "path": path}


@pytest.mark.parametrize(
    "path",
    [
        "/api/ai/chat",
        "/api/v1/ai/complete",
        "/supabase/storage/v1/object/sign/bucket/a.pdf",
        "/assets/logo.png",
        "/assets/font-abc.woff2",
        "/assets/clip.mp4",
        "/downloads/result.xlsx",
        "/ASSETS/LOGO.PNG",
    ],
)
def test_skips_streaming_and_precompressed(path):
    assert _should_skip_compression(_scope(path)) is True


@pytest.mark.parametrize(
    "path",
    [
        "/assets/index-abc.js",
        "/assets/index-abc.css",
        "/assets/pdfium-abc.wasm",  # 압축 안 된 바이트코드 — 실측 2.17배
        "/assets/icon.svg",
        "/assets/index.js.map",
        "/api/jobs",
        "/",
        "/jobs/abc123",
    ],
)
def test_compresses_text_and_wasm(path):
    assert _should_skip_compression(_scope(path)) is False


def _build_app() -> Starlette:
    big = "x" * 50_000

    async def bundle(request):
        return PlainTextResponse(big, media_type="application/javascript")

    async def api(request):
        return PlainTextResponse(big, media_type="application/json")

    async def tiny(request):
        return PlainTextResponse("ok")

    async def sse(request):
        async def gen():
            for i in range(3):
                yield f"data: {i}\n\n".encode()
                await asyncio.sleep(0)

        return StreamingResponse(gen(), media_type="text/event-stream")

    app = Starlette(
        routes=[
            Route("/assets/index-abc.js", bundle),
            Route("/api/jobs", api),
            Route("/api/health", tiny),
            Route("/api/ai/chat", sse),
        ]
    )
    app.add_middleware(SelectiveGZipMiddleware)
    return app


def test_bundle_and_api_are_compressed():
    client = TestClient(_build_app())
    for path in ("/assets/index-abc.js", "/api/jobs"):
        resp = client.get(path, headers={"accept-encoding": "gzip"})
        assert resp.status_code == 200
        assert resp.headers["content-encoding"] == "gzip"
        assert int(resp.headers["content-length"]) < 50_000
        assert resp.text == "x" * 50_000


def test_sse_stream_is_not_compressed():
    client = TestClient(_build_app())
    resp = client.get("/api/ai/chat", headers={"accept-encoding": "gzip"})
    assert resp.status_code == 200
    assert "content-encoding" not in resp.headers
    assert resp.text == "data: 0\n\ndata: 1\n\ndata: 2\n\n"


def test_small_response_is_not_compressed():
    client = TestClient(_build_app())
    resp = client.get("/api/health", headers={"accept-encoding": "gzip"})
    assert "content-encoding" not in resp.headers
