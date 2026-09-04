#!/usr/bin/env python3
"""PROOF Sandbox API — Kata Containers 샌드박스 관리 엔드포인트

[Flow: Step 1 (POST /api/sandboxes — sandbox 생성) -> Step 2 (POST /api/sandboxes/{id}/execute — 명령 실행)
  -> Step 3 (GET /api/sandboxes/{id} — 상태 조회) -> Step 4 (GET /api/sandboxes/{id}/files — 파일 목록)
  -> Step 5 (POST /api/sandboxes/{id}/commit — git commit) -> Step 6 (DELETE /api/sandboxes/{id} — 종료)]

이 라우터는 Kata Containers 기반 에이전트 샌드박스의 생명주기를 REST API 로 노출한다.
AI 백엔드(Node.js)가 이 API 를 호출하여 sandbox 내부에서 코드를 실행한다.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from sqlalchemy.orm.attributes import flag_modified

from ..auth.supabase_auth import CurrentUser, get_current_user
from ..config import settings
from ..core import cache
from ..core.sandbox import (
    ResultCollector,
    SandboxManager,
    WorkspaceManager,
    check_command,
    log_blocked_command,
)
from ..db.models import Job, Sandbox
from ..db.session import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/sandboxes", tags=["sandboxes"])

# [Flow: Step 1 (요청 수신) -> Step 2 (FastAPI 스레드풀에서 동기 실행) -> Step 3 (이벤트 루프 비점유)]
#
# 이 라우터의 핸들러는 의도적으로 `async def` 가 아니라 `def` 다.
# FastAPI 는 `def` 핸들러를 스레드풀(anyio, 기본 40스레드)에서 돌리지만,
# `async def` 핸들러는 이벤트 루프에서 그대로 실행한다.
#
# 여기서는 특히 치명적이다. SandboxManager 의 모든 메서드는 `subprocess.run` 으로
# nerdctl 을 호출하며 타임아웃이 최대 60초다(core/sandbox/manager.py). `async def` 였을 때는
# 샌드박스 명령 하나가 백엔드 전체를 최대 60초 동결시켰다 — 다른 모든 요청, 헬스체크,
# /api/ai 스트리밍 프록시까지 전부. execute_command 는 사용자가 준 명령을 그대로 돌린다.
#
# ⚠️ 이 파일의 핸들러를 `async def` 로 되돌리지 말 것. 동기 DB 세션과 subprocess 호출이
# 그대로 이벤트 루프로 돌아온다. `await` 가 필요하면 블로킹 부분을 `asyncio.to_thread` 로 감쌀 것.


# --- sandbox manager 인스턴스 (싱글톤) ---
_sandbox_mgr: SandboxManager | None = None
_collector: ResultCollector | None = None

# 파일 확장자 → source_files 타입 매핑 (_build_source_file_item 호환)
_EXTENSION_TYPE_MAP = {
    ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".svg": "image",
    ".mp3": "audio", ".wav": "audio",
    ".mp4": "video", ".webm": "video",
    ".csv": "file", ".md": "file", ".xlsx": "file", ".json": "file",
    ".txt": "file", ".html": "file", ".zip": "file", ".tar": "file", ".gz": "file",
    # 미리보기 PDF 변환을 지원하는 문서 타입
    ".pptx": "pptx", ".ppt": "pptx", ".ppsx": "pptx", ".pps": "pptx",
    ".hwp": "hwp", ".hwpx": "hwp",
    ".docx": "docx", ".doc": "docx",
}


def _ext_to_file_type(extension: str) -> str:
    """파일 확장자를 source_files 타입으로 변환한다.

    매개변수:
        extension: 파일 확장자 (예: ".csv")

    반환값:
        타입 문자열 ("pdf"|"image"|"audio"|"video"|"file")
    """
    return _EXTENSION_TYPE_MAP.get(extension.lower(), "file")


def _get_sandbox_mgr() -> SandboxManager:
    """SandboxManager 싱글톤 인스턴스를 반환한다."""
    global _sandbox_mgr
    if _sandbox_mgr is None:
        _sandbox_mgr = SandboxManager()
    return _sandbox_mgr


def _get_collector() -> ResultCollector:
    """ResultCollector 싱글톤 인스턴스를 반환한다."""
    global _collector
    if _collector is None:
        _collector = ResultCollector()
    return _collector


# ========================================
# 요청/응답 모델
# ========================================

class CreateSandboxRequest(BaseModel):
    """sandbox 생성 요청."""
    job_id: str = Field(..., description="연결된 Job ID")
    resource_limits: dict[str, Any] | None = Field(
        None, description='{"cpu": 1, "memory_mb": 2048}'
    )
    dense_mode: bool = Field(False, description="고밀도 모드 (300+ VM)")


class ExecuteCommandRequest(BaseModel):
    """sandbox 내 명령 실행 요청."""
    command: str = Field(..., description="실행할 셸 명령어")
    timeout: int | None = Field(None, description="명령 타임아웃 (초, 기본 300)")


class WriteFileRequest(BaseModel):
    """sandbox 내 파일 쓰기 요청."""
    path: str = Field(..., description="파일 경로 (/workspace 하위)")
    content: str = Field(..., description="파일 내용")


class GitCommitRequest(BaseModel):
    """git commit 요청."""
    message: str = Field("Agent changes", description="commit 메시지")


# ========================================
# 엔드포인트
# ========================================

@router.post("")
def create_sandbox(
    req: CreateSandboxRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """새 sandbox 를 생성한다.

    [Flow: Job 확인 -> job_data 구성 -> sandbox 생성(파일 매핑 포함)
      -> Storage 에서 결과 파일 다운로드 -> DB 저장 -> 결과 반환]
    """
    # Step 1: Job 확인
    job = db.execute(select(Job).where(Job.id == req.job_id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Step 2: job_data 딕셔너리 구성 — 파일명 매핑에 필요한 필드만 추출
    # original_filename: 단일 파일 Job에서 input.{ext} → 원본 파일명 매핑용
    # extracted_files: 멀티미디어/아카이브 Job의 개별 파일 매핑용
    # pdf_storage_path: Storage에서 원본 파일 다운로드용
    # annotated_pdf_files: 주석 JSON 다운로드용
    job_data = {
        "original_filename": job.original_filename or "",
        "pdf_storage_path": job.pdf_storage_path or "",
        "extracted_files": job.extracted_files or [],
        "annotated_pdf_files": job.annotated_pdf_files or [],
        "file_type": job.file_type or "",
    }

    # Step 3: sandbox 생성 — job_data 전달로 파일명 매핑 수행
    mgr = _get_sandbox_mgr()
    result = mgr.create_sandbox(
        job_id=req.job_id,
        user_id=user.user_id,
        resource_limits=req.resource_limits,
        dense_mode=req.dense_mode,
        job_data=job_data,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "sandbox creation failed"))

    # Step 4: Storage 에서 결과 파일 다운로드 (추출 결과 마크다운, 주석 JSON 등)
    # 기존 처리 파일(input.pdf)은 _map_input_files_to_original_names 로 복사되었고,
    # 여기서는 Storage 에만 있는 파일(추출 결과, 주석)을 추가로 다운로드.
    try:
        from ..core import supabase_client as sbc
        workspace_path = Path(result.get("workspace", ""))
        if workspace_path.exists():
            _get_collector()  # collector 싱글톤 초기화 (필요시)
            mgr.workspace_mgr.download_job_files(workspace_path, job_data, sbc.get_service_client())
    except Exception as e:
        logger.warning("Storage 파일 다운로드 실패 (무시): %s", e)

    # Step 5: DB 저장
    sandbox = Sandbox(
        id=result["sandbox_id"],
        job_id=req.job_id,
        user_id=user.user_id,
        container_name=result.get("container_name", ""),
        container_id=result.get("container_id", ""),
        runtime=result.get("runtime", "io.containerd.kata-clh.v2"),
        status=result.get("status", "running"),
        workspace_path=result.get("workspace", ""),
        resource_limits=result.get("resource_limits", {"cpu": 1, "memory_mb": 2048}),
        dense_mode=req.dense_mode,
    )
    db.add(sandbox)
    db.commit()

    return result


@router.get("/stats")
def get_sandbox_stats(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """[Flow: Step 1 (sandbox 통계 조회) -> Step 2 (상태별 카운트 + 디스크 사용량) -> Step 3 (결과 반환)]

    관리자용 sandbox 통계 엔드포인트. 활성 sandbox 수, 누적 생성 수,
    상태별 분포, 디스크 사용량을 반환한다.
    """
    # [Flow: Step 1 (sandbox 통계 조회) -> Step 2 (상태별 카운트 + 디스크 사용량) -> Step 3 (결과 반환)]
    from sqlalchemy import func, case

    # 상태별 카운트
    status_counts = db.execute(
        select(
            Sandbox.status,
            func.count(Sandbox.id).label("count"),
        ).group_by(Sandbox.status)
    ).all()

    status_map = {row.status: row.count for row in status_counts}
    total_created = sum(status_map.values())
    active_count = status_map.get("running", 0) + status_map.get("creating", 0)

    # 사용자별 활성 sandbox 수 (관리자만 조회 가능)
    user_stats = []
    if user.is_admin:
        user_active = db.execute(
            select(
                Sandbox.user_id,
                func.count(Sandbox.id).label("count"),
            )
            .where(Sandbox.status.in_(["running", "creating"]))
            .group_by(Sandbox.user_id)
        ).all()
        user_stats = [{"user_id": str(row.user_id), "active_count": row.count} for row in user_active]

    # 디스크 사용량 (sandbox_data_dir 의 전체 크기)
    disk_usage = None
    try:
        import shutil
        data_dir = settings.sandbox_data_dir
        if Path(data_dir).exists():
            total, used, free = shutil.disk_usage(data_dir)
            disk_usage = {
                "total_gb": round(total / (1024 ** 3), 1),
                "used_gb": round(used / (1024 ** 3), 1),
                "free_gb": round(free / (1024 ** 3), 1),
            }
    except Exception as e:
        logger.warning(f"디스크 사용량 조회 실패: {e}")

    return {
        "active_count": active_count,
        "total_created": total_created,
        "status_breakdown": status_map,
        "max_concurrent": settings.sandbox_max_concurrent,
        "max_concurrent_dense": settings.sandbox_max_concurrent_dense,
        "disk_usage": disk_usage,
        "user_stats": user_stats if user.is_admin else None,
    }


@router.get("/{sandbox_id}")
def get_sandbox(
    sandbox_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """sandbox 상태를 조회한다.

    [Flow: DB 조회 -> 컨테이너 상태 갱신 -> 결과 반환]
    """
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    # 권한 확인
    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    # 컨테이너 실제 상태 조회 및 DB 동기화
    # starting 상태에서도 컨테이너가 running 이면 DB 를 갱신해야 함.
    mgr = _get_sandbox_mgr()
    if sandbox.container_name and sandbox.status in ("running", "starting", "creating"):
        status_result = mgr.get_status(sandbox.container_name)
        actual_status = status_result.get("status", "unknown")
        if actual_status == "running" and sandbox.status != "running":
            sandbox.status = "running"
            db.commit()
        elif actual_status not in ("running", "starting", "unknown"):
            sandbox.status = actual_status
            db.commit()

    return {
        "sandbox_id": sandbox.id,
        "job_id": sandbox.job_id,
        "status": sandbox.status,
        "container_name": sandbox.container_name,
        "workspace_path": sandbox.workspace_path,
        "resource_limits": sandbox.resource_limits,
        "dense_mode": sandbox.dense_mode,
        "created_at": sandbox.created_at.isoformat() if sandbox.created_at else None,
        "error": sandbox.error,
    }


@router.post("/{sandbox_id}/execute")
def execute_command(
    sandbox_id: str,
    req: ExecuteCommandRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """sandbox 내부에서 셸 명령을 실행한다.

    [Flow: sandbox 조회 -> 권한 확인 -> 보안 검사 -> 명령 실행 -> 결과 반환]
    """
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    # starting 상태일 때 컨테이너 실제 상태를 확인하여 DB 동기화
    if sandbox.status in ("starting", "creating"):
        mgr = _get_sandbox_mgr()
        status_result = mgr.get_status(sandbox.container_name)
        if status_result.get("status") == "running":
            sandbox.status = "running"
            db.commit()
        else:
            raise HTTPException(
                status_code=409,
                detail=f"Sandbox is not running yet (status={sandbox.status})",
            )

    if sandbox.status != "running":
        raise HTTPException(status_code=409, detail=f"Sandbox is not running (status={sandbox.status})")

    # 보안 검사 (사전 필터링)
    allowed, reason = check_command(req.command)
    if not allowed:
        log_blocked_command(req.command, reason)
        raise HTTPException(status_code=403, detail=f"Command blocked by security policy: {reason}")

    mgr = _get_sandbox_mgr()
    result = mgr.execute_command(
        sandbox_id=sandbox.id,
        container_name=sandbox.container_name,
        command=req.command,
        timeout=req.timeout,
    )

    if "error" in result:
        return {"sandbox_id": sandbox_id, "error": result["error"]}

    return {
        "sandbox_id": sandbox_id,
        "exit_code": result.get("exit_code", -1),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
    }


@router.get("/{sandbox_id}/files")
def list_files(
    sandbox_id: str,
    path: str = Query("/workspace", description="조회할 경로"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """workspace 내 파일 목록을 조회한다."""
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    mgr = _get_sandbox_mgr()
    return mgr.list_files(sandbox.container_name, path)


@router.get("/{sandbox_id}/files/read")
def read_file(
    sandbox_id: str,
    path: str = Query(..., description="읽을 파일 경로"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """workspace 내 파일을 읽는다."""
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    mgr = _get_sandbox_mgr()
    return mgr.read_file(sandbox.container_name, path)


@router.post("/{sandbox_id}/files/write")
def write_file(
    sandbox_id: str,
    req: WriteFileRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """workspace 에 파일을 쓴다."""
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    mgr = _get_sandbox_mgr()
    return mgr.write_file(sandbox.container_name, req.path, req.content)


@router.post("/{sandbox_id}/commit")
def git_commit(
    sandbox_id: str,
    req: GitCommitRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """workspace 의 변경사항을 git commit 한다."""
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    mgr = _get_sandbox_mgr()
    return mgr.git_commit(sandbox.container_name, req.message)


@router.get("/{sandbox_id}/diff")
def git_diff(
    sandbox_id: str,
    cached: bool = Query(False, description="staged 변경사항만"),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """git diff 를 조회한다."""
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    mgr = _get_sandbox_mgr()
    return mgr.git_diff(sandbox.container_name, cached)


@router.post("/{sandbox_id}/collect")
def collect_results(
    sandbox_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """sandbox 의 결과 파일을 수집하여 Supabase Storage 에 업로드한다.

    [Flow: sandbox 조회 -> workspace 스캔 -> Storage 업로드 -> job.extracted_files 업데이트 -> 캐시 무효화]
    """
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    workspace_path = Path(sandbox.workspace_path)
    if not workspace_path.exists():
        raise HTTPException(status_code=404, detail="Workspace not found")

    collector = _get_collector()
    # [Flow: 서비스 롤 클라이언트 획득 -> 업로드 실행 -> 실패 시 명시적 오류 반환]
    # 결과 파일은 백엔드가 Storage에 기록해야 하므로 anon 클라이언트가 아닌 서비스 클라이언트를 사용한다.
    # 클라이언트 생성 실패를 None으로 바꾸면 업로드가 0개인 성공 응답처럼 보이므로 즉시 오류를 반환한다.
    try:
        from ..core.supabase_client import get_service_client
        supabase = get_service_client()
    except Exception as e:
        logger.exception("sandbox 결과 파일용 Supabase 서비스 클라이언트 생성 실패")
        raise HTTPException(
            status_code=503,
            detail="Sandbox result storage is temporarily unavailable",
        ) from e

    result = collector.collect_and_upload(
        workspace_path=workspace_path,
        job_id=sandbox.job_id or "",
        supabase_client=supabase,
        since_timestamp=sandbox.created_at.timestamp() if sandbox.created_at else None,
    )

    # [Flow: 업로드된 파일을 job.extracted_files 에 추가하여 파일 탭에 표시]
    uploaded_files = result.get("files", [])
    if uploaded_files and sandbox.job_id:
        job = db.execute(
            select(Job).where(Job.id == sandbox.job_id)
        ).scalar_one_or_none()
        if job:
            existing = list(job.extracted_files or [])
            existing_paths = {
                f.get("storage_path") for f in existing if isinstance(f, dict)
            }
            for f in uploaded_files:
                storage_path = f.get("storage_path", "")
                if not storage_path or storage_path in existing_paths:
                    continue
                ext = Path(f.get("path", "")).suffix.lower()
                existing.append({
                    "path": f.get("path", storage_path),
                    "storage_path": storage_path,
                    "type": _ext_to_file_type(ext),
                    "size": f.get("size", 0),
                    "bucket": "jobs",
                    "source_kind": "agent_output",
                })
                existing_paths.add(storage_path)
            job.extracted_files = existing
            flag_modified(job, "extracted_files")
            db.commit()
            # preview 캐시 무효화 — 다음 preview_job 호출 시 새 파일이 source_files 에 포함됨
            cache.invalidate_pattern(f"preview:{job.id}:*")

    return {
        "sandbox_id": sandbox_id,
        "job_id": sandbox.job_id,
        "uploaded": result["uploaded"],
        "failed": result["failed"],
        "total_scanned": result["total_scanned"],
        "files": result["files"],
    }


@router.delete("/{sandbox_id}")
def destroy_sandbox(
    sandbox_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """sandbox 를 종료하고 정리한다.

    [Flow: sandbox 조회 -> 권한 확인 -> 결과 수집 (옵션) -> 컨테이너 종료 -> DB 업데이트]
    """
    sandbox = db.execute(
        select(Sandbox).where(Sandbox.id == sandbox_id)
    ).scalar_one_or_none()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="Sandbox not found")

    if str(sandbox.user_id) != user.user_id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Access denied")

    mgr = _get_sandbox_mgr()
    workspace_path = Path(sandbox.workspace_path) if sandbox.workspace_path else None
    result = mgr.destroy_sandbox(sandbox.container_name, workspace_path)

    # DB 업데이트
    sandbox.status = "destroyed"
    sandbox.destroyed_at = datetime.now()
    db.commit()

    return {
        "sandbox_id": sandbox_id,
        "status": "destroyed",
        "container": sandbox.container_name,
    }


@router.get("")
def list_sandboxes(
    status: str | None = Query(None, description="상태 필터 (running/stopped/...)"),
    job_id: str | None = Query(None, description="Job ID 필터"),
    limit: int = Query(50, ge=1, le=200),
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """sandbox 목록을 조회한다."""
    query = select(Sandbox)
    if not user.is_admin:
        query = query.where(Sandbox.user_id == user.user_id)
    if status:
        query = query.where(Sandbox.status == status)
    if job_id:
        query = query.where(Sandbox.job_id == job_id)
    query = query.order_by(Sandbox.created_at.desc()).limit(limit)

    sandboxes = db.execute(query).scalars().all()

    return {
        "sandboxes": [
            {
                "sandbox_id": s.id,
                "job_id": s.job_id,
                "status": s.status,
                "container_name": s.container_name,
                "dense_mode": s.dense_mode,
                "created_at": s.created_at.isoformat() if s.created_at else None,
            }
            for s in sandboxes
        ],
        "count": len(sandboxes),
    }
