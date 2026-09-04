#!/usr/bin/env python3
"""[Flow: Step 1 (api/ 하위 라우트 핸들러 수집) -> Step 2 (async 핸들러 중 동기 DB 사용 탐지)
      -> Step 3 (허용 목록과 일치하는지 검증)]

이벤트 루프 블로킹 회귀 방지 테스트.

FastAPI 는 `def` 핸들러를 스레드풀에서 실행하지만 `async def` 핸들러는 이벤트 루프에서
그대로 실행한다. 동기 SQLAlchemy 세션(또는 subprocess) 을 쓰는 핸들러를 `async def` 로
두면, 그 요청이 끝날 때까지 프로세스 전체가 다른 요청을 하나도 처리하지 못한다.
uvicorn 워커가 1개이므로 도망갈 곳이 없다.

이 테스트는 "동기 DB 를 쓰면서 async 인 핸들러" 집합을 고정한다. 허용 목록에 있는
6개는 `await` 가 반드시 필요해(파일 업로드, Turnstile 검증 등) async 를 유지한다.
"""
import ast
import os
import pathlib
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

API_DIR = pathlib.Path(__file__).resolve().parent.parent / "api"

ROUTE_DECORATORS = ("get", "post", "put", "patch", "delete", "head", "options", "api_route")

SYNC_DB_CALLS = (
    "db.query", "db.execute", "db.commit", "db.add", "db.get",
    "db.delete", "db.scalar", "db.refresh", "db.flush",
)

# await 가 실제로 필요해 async 를 유지하는 핸들러.
# 여기에 추가하기 전에, 정말 await 가 필요한지 / 블로킹 부분을 asyncio.to_thread 로
# 감쌀 수 없는지 먼저 확인할 것.
ALLOWED_ASYNC_WITH_SYNC_DB = {
    ("api/admin.py", "login"),                      # await verify_turnstile_token
    ("api/jobs/download.py", "save_edited_xlsx"),   # await file.read()
    ("api/jobs/uploads.py", "upload_job"),          # await file.read()
    ("api/jobs/uploads.py", "create_job"),          # await _count_pages_with_docling
    ("api/jobs/uploads.py", "confirm_add_files"),   # await _analyze_extracted_files
    ("api/v1/jobs.py", "upload_job"),               # await file.read()
}


def _is_route_handler(node: ast.AsyncFunctionDef) -> bool:
    for deco in node.decorator_list:
        target = deco.func if isinstance(deco, ast.Call) else deco
        if isinstance(target, ast.Attribute) and target.attr in ROUTE_DECORATORS:
            return True
    return False


def _async_handlers_touching_sync_db() -> set[tuple[str, str]]:
    found = set()
    for path in sorted(API_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef) or not _is_route_handler(node):
                continue
            body = ast.unparse(node)
            if any(call in body for call in SYNC_DB_CALLS):
                rel = path.relative_to(API_DIR.parent).as_posix()
                found.add((rel, node.name))
    return found


def test_no_new_blocking_async_endpoints():
    actual = _async_handlers_touching_sync_db()

    unexpected = actual - ALLOWED_ASYNC_WITH_SYNC_DB
    assert not unexpected, (
        "동기 DB 를 쓰는 async 핸들러가 새로 생겼다. 이벤트 루프가 막힌다:\n"
        + "\n".join(f"  {f}::{n}" for f, n in sorted(unexpected))
        + "\n\n`async def` 를 `def` 로 바꿔라 — FastAPI 가 스레드풀에서 실행한다.\n"
        "await 가 꼭 필요하면 블로킹 부분을 asyncio.to_thread 로 감싸거나,\n"
        "정당한 사유와 함께 ALLOWED_ASYNC_WITH_SYNC_DB 에 추가하라."
    )

    stale = ALLOWED_ASYNC_WITH_SYNC_DB - actual
    assert not stale, (
        "허용 목록에 실제로 존재하지 않는 항목이 남아 있다(이름 변경/삭제됨):\n"
        + "\n".join(f"  {f}::{n}" for f, n in sorted(stale))
    )


def test_sandbox_handlers_are_sync():
    """SandboxManager 는 subprocess.run(timeout=60) 을 쓴다 — 절대 루프에서 돌리면 안 된다."""
    import inspect

    from backend.api import sandboxes

    blocking = [
        "create_sandbox", "get_sandbox_stats", "get_sandbox", "execute_command",
        "list_files", "read_file", "write_file", "git_commit", "git_diff",
        "collect_results", "destroy_sandbox", "list_sandboxes",
    ]
    still_async = [
        name for name in blocking
        if inspect.iscoroutinefunction(getattr(sandboxes, name))
    ]
    assert not still_async, (
        f"샌드박스 핸들러가 async 로 되돌아갔다: {still_async}. "
        "nerdctl subprocess 호출(최대 60초)이 백엔드 전체를 동결시킨다."
    )
