#!/usr/bin/env python3
# [Flow: Step 1 (외부 요청 수신) -> Step 2 (내부 Supabase로 전달) -> Step 3 (응답 중계)]
import httpx
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..config import settings

router = APIRouter(prefix="/supabase", tags=["supabase-proxy"])

_TARGET = settings.supabase_url.rstrip("/")

_HOP_HEADERS = frozenset(
    h.lower() for h in (
        "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
        "te", "trailers", "transfer-encoding", "upgrade", "host",
    )
)


def _forward_headers(src: Request) -> dict:
    return {k: v for k, v in src.headers.items() if k.lower() not in _HOP_HEADERS}


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_supabase(path: str, request: Request):
    url = f"{_TARGET}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    body = await request.body()
    headers = _forward_headers(request)

    client = httpx.AsyncClient(timeout=300.0, follow_redirects=False)

    req = client.build_request(
        request.method,
        url,
        headers=headers,
        content=body if body else None,
    )
    resp = await client.send(req, stream=True)

    async def stream():
        try:
            async for chunk in resp.aiter_raw():
                yield chunk
        finally:
            await resp.aclose()
            await client.aclose()

    response_headers = {
        k: v for k, v in resp.headers.items() if k.lower() not in _HOP_HEADERS
    }
    return StreamingResponse(stream(), status_code=resp.status_code, headers=response_headers)
