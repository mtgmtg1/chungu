"""workers/tasks/maintenance.py — 유지보수 Celery 태스크.

cleanup_expired_uploads, cleanup_expired_sandboxes, auto_recharge_retry,
grant_monthly_subscription_credits 태스크를 포함한다.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ...celery_app import celery
from ...config import settings
from ...core import points_service, subscription_service, supabase_client
from ...db.models import Job, User
from ...db.session import SessionLocal
from ... import settings_store
from ._helpers import _handle_job_failure, _release_subscription_usage, _set_status

logger = logging.getLogger(__name__)

RETENTION_DAYS = 30


@celery.task(name="backend.workers.tasks.cleanup_expired_uploads")
def cleanup_expired_uploads() -> dict:
    """created_at 기준 30일이 지난 job의 원본 업로드 파일 삭제를 보류한다. (아카이빙 스토리지 구성 전까지)"""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
        jobs = (
            db.query(Job)
            .filter(Job.created_at < cutoff)
            .filter((Job.pdf_storage_path != "") | (Job.extracted_files.isnot(None)))
            .all()
        )

        pending = 0
        skipped = 0
        for job in jobs:
            has_source = bool(job.pdf_storage_path) or any(
                isinstance(info, dict) and info.get("storage_path")
                for info in job.extracted_files or []
            )
            if not has_source:
                skipped += 1
                continue

            pending += 1
            logger.info(f"[cleanup_expired_uploads] {job.id} 원본 파일 삭제 보류 (아카이빙 스토리지 미구성)")

        return {"pending": pending, "skipped": skipped}
    except Exception as e:
        logger.exception(f"[cleanup_expired_uploads] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()



@celery.task(name="backend.workers.tasks.auto_recharge_retry")
def auto_recharge_retry() -> dict:
    """자동 충전 실패 사용자를 찾아 1일 간격으로 재시도한다.
    auto_recharge_retries > 0 && < 3 && auto_recharge_enabled == True인 사용자 대상."""
    # [Flow: Step 1 (재시도 대상 조회) -> Step 2 (각 사용자에 대해 trigger_auto_recharge 호출) -> Step 3 (결과 집계)]
    from sqlalchemy import select as sa_select
    from ...db.models import User
    from ..api.payments import trigger_auto_recharge

    db = SessionLocal()
    try:
        users = db.execute(
            sa_select(User).where(
                User.auto_recharge_enabled == True,  # noqa: E712
                User.auto_recharge_retries > 0,
                User.auto_recharge_retries < 3,
            )
        ).scalars().all()

        retried = 0
        succeeded = 0
        for user in users:
            try:
                result = trigger_auto_recharge(db, user)
                retried += 1
                if result.get("ok"):
                    succeeded += 1
                    logger.info(f"[auto_recharge_retry] {user.id} 재시도 성공")
                else:
                    logger.warning(f"[auto_recharge_retry] {user.id} 재시도 실패: {result.get('reason')}")
            except Exception as e:
                logger.error(f"[auto_recharge_retry] {user.id} 예외: {e}")

        return {"retried": retried, "succeeded": succeeded}
    except Exception as e:
        logger.exception(f"[auto_recharge_retry] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()



@celery.task(name="backend.workers.tasks.cleanup_expired_sandboxes")
def cleanup_expired_sandboxes() -> dict:
    """[Flow: Step 1 (만료된 sandbox 조회·종료) -> Step 2 (결과 수집) -> Step 3 (오래된 workspace 디스크 정리)]

    만료된 Kata 샌드박스를 자동으로 종료하고 결과 파일을 수집한다.
    또한 이미 종료된 sandbox 의 workspace 디스크를 보존 기간(7일) 경과 후 삭제한다.
    Celery beat 에 의해 주기적으로 실행된다 (기본 10분 간격).
    """
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from sqlalchemy import select as sa_select, update as sa_update
    from ...db.models import Sandbox
    from ...core.sandbox import ResultCollector, SandboxManager, WorkspaceManager

    # [Flow: Step 1 (만료된 sandbox 조회·종료) -> Step 2 (결과 수집) -> Step 3 (workspace 정리)]
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        timeout_seconds = settings.sandbox_default_timeout
        cutoff = now - timedelta(seconds=timeout_seconds)

        manager = SandboxManager()
        collector = ResultCollector()
        workspace_mgr = WorkspaceManager()

        # [Flow: 서비스 롤 클라이언트 획득 -> 만료 sandbox 결과 수집 -> sandbox 종료]
        # 만료 처리에서도 생성 파일을 잃지 않도록 동일한 서비스 클라이언트를 사용한다.
        try:
            from ...core.supabase_client import get_service_client
            supabase = get_service_client()
        except Exception:
            logger.exception("만료 sandbox 결과 파일용 Supabase 서비스 클라이언트 생성 실패")
            supabase = None

        # ========================================
        # Step 1: 만료된 sandbox 종료 + 결과 수집
        # ========================================
        expired = db.execute(
            sa_select(Sandbox).where(
                Sandbox.status.in_(["creating", "running"]),
                Sandbox.created_at < cutoff,
            )
        ).scalars().all()

        destroyed_count = 0
        destroy_errors = 0

        for sandbox in expired:
            try:
                logger.info(f"[cleanup_expired_sandboxes] sandbox {sandbox.id} 만료, 종료 시도")
                workspace_path = Path(sandbox.workspace_path) if sandbox.workspace_path else None

                # 결과 수집 시도 (실패해도 종료는 진행)
                if workspace_path and workspace_path.exists():
                    try:
                        collector.collect_and_upload(
                            workspace_path=workspace_path,
                            job_id=sandbox.job_id or "",
                            supabase_client=supabase,
                        )
                    except Exception as collect_err:
                        logger.warning(f"[cleanup_expired_sandboxes] {sandbox.id} 결과 수집 실패: {collect_err}")

                # sandbox 종료 — destroy_sandbox(container_name, workspace_path)
                manager.destroy_sandbox(sandbox.container_name, workspace_path)

                # DB 상태 업데이트
                db.execute(
                    sa_update(Sandbox)
                    .where(Sandbox.id == sandbox.id)
                    .values(status="expired", updated_at=now)
                )
                destroyed_count += 1
            except Exception as e:
                logger.error(f"[cleanup_expired_sandboxes] sandbox {sandbox.id} 종료 실패: {e}")
                destroy_errors += 1

        # ========================================
        # Step 2: 오래된 workspace 디스크 정리 (보존 기간 7일 경과)
        # ========================================
        # 이미 destroyed/expired 상태이고 workspace_path 가 비어있지 않은 sandbox 조회
        stale = db.execute(
            sa_select(Sandbox).where(
                Sandbox.status.in_(["destroyed", "expired"]),
                Sandbox.workspace_path != "",
            )
        ).scalars().all()

        workspace_cleaned = 0
        workspace_errors = 0

        for sandbox in stale:
            workspace_path = Path(sandbox.workspace_path) if sandbox.workspace_path else None
            if not workspace_path or not workspace_path.exists():
                # 이미 디스크에 없으면 DB 의 workspace_path 만 비우기
                db.execute(
                    sa_update(Sandbox)
                    .where(Sandbox.id == sandbox.id)
                    .values(workspace_path="", updated_at=now)
                )
                continue

            try:
                # cleanup_workspace: mtime 기준 preserve_days(7일) 경과 시 rmtree 실행
                removed = workspace_mgr.cleanup_workspace(workspace_path, preserve_days=7)
                if removed:
                    db.execute(
                        sa_update(Sandbox)
                        .where(Sandbox.id == sandbox.id)
                        .values(workspace_path="", updated_at=now)
                    )
                    workspace_cleaned += 1
                    logger.info(f"[cleanup_expired_sandboxes] workspace 정리 완료: {workspace_path}")
            except Exception as e:
                logger.error(f"[cleanup_expired_sandboxes] workspace 정리 실패 {sandbox.id}: {e}")
                workspace_errors += 1

        db.commit()
        logger.info(
            f"[cleanup_expired_sandboxes] 완료: destroyed={destroyed_count}, destroy_errors={destroy_errors}, "
            f"workspace_cleaned={workspace_cleaned}, workspace_errors={workspace_errors}"
        )
        return {
            "destroyed": destroyed_count,
            "destroy_errors": destroy_errors,
            "workspace_cleaned": workspace_cleaned,
            "workspace_errors": workspace_errors,
        }
    except Exception as e:
        logger.exception(f"[cleanup_expired_sandboxes] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()



@celery.task(name="backend.workers.tasks.grant_monthly_subscription_credits")
def grant_monthly_subscription_credits() -> dict[str, Any]:
    """Celery beat로 매일 실행되어 월간 구독 크레딧을 지급한다.

    연간 요금제의 경우 Paddle 웹훅이 월별로 발생하지 않으므로, 이 태스크가
    구독 기간 시작일 기준으로 매월 크레딧을 지급하는 폴백 역할을 한다.
    """
    db = SessionLocal()
    try:
        plans = list(subscription_service.PLAN_MONTHLY_CREDITS.keys())
        query = db.query(User).where(User.subscription_plan.in_(plans))
        users = query.all()
        granted = 0
        skipped = 0
        for user in users:
            try:
                if subscription_service.grant_monthly_credits(db, user):
                    granted += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(f"[grant_monthly] user={user.id} 크레딧 지급 실패: {e}")
                skipped += 1
        db.commit()
        logger.info(f"[grant_monthly] 완료: granted={granted}, skipped={skipped}")
        return {"granted": granted, "skipped": skipped}
    except Exception as e:
        logger.exception(f"[grant_monthly] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()



