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

from ..auth.supabase_auth import CurrentUser, get_current_user
from ..config import settings
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

# --- sandbox manager 인스턴스 (싱글톤) ---
_sandbox_mgr: SandboxManager | None = None
_collector: ResultCollector | None = None


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
async def create_sandbox(
    req: CreateSandboxRequest,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """새 sandbox 를 생성한다.

    [Flow: Job 확인 -> sandbox 생성 -> DB 저장 -> 결과 반환]
    """
    # Step 1: Job 확인
    job = db.execute(select(Job).where(Job.id == req.job_id)).scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Step 2: sandbox 생성
    mgr = _get_sandbox_mgr()
    result = mgr.create_sandbox(
        job_id=req.job_id,
        user_id=user.user_id,
        resource_limits=req.resource_limits,
        dense_mode=req.dense_mode,
    )

    if result.get("status") == "error":
        raise HTTPException(status_code=500, detail=result.get("error", "sandbox creation failed"))

    # Step 3: DB 저장
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


@router.get("/{sandbox_id}")
async def get_sandbox(
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

    # 컨테이너 상태 갱신
    mgr = _get_sandbox_mgr()
    if sandbox.container_name and sandbox.status == "running":
        status_result = mgr.get_status(sandbox.container_name)
        if status_result.get("status") not in ("running", "starting"):
            sandbox.status = status_result.get("status", "stopped")
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
async def execute_command(
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
async def list_files(
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
async def read_file(
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
async def write_file(
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
async def git_commit(
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
async def git_diff(
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
async def collect_results(
    sandbox_id: str,
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """sandbox 의 결과 파일을 수집하여 Supabase Storage 에 업로드한다.

    [Flow: sandbox 조회 -> workspace 스캔 -> Storage 업로드 -> 결과 반환]
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
    # supabase_client 는 별도 import (순환 참조 방지를 위해 지연 import)
    try:
        from ..core.supabase_client import get_supabase_client
        supabase = get_supabase_client()
    except Exception:
        supabase = None

    result = collector.collect_and_upload(
        workspace_path=workspace_path,
        job_id=sandbox.job_id or "",
        supabase_client=supabase,
    )

    return {
        "sandbox_id": sandbox_id,
        "job_id": sandbox.job_id,
        "uploaded": result["uploaded"],
        "failed": result["failed"],
        "total_scanned": result["total_scanned"],
        "files": result["files"],
    }


@router.delete("/{sandbox_id}")
async def destroy_sandbox(
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
async def list_sandboxes(
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


@router.get("/stats")
async def get_sandbox_stats(
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
