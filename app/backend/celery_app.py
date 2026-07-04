#!/usr/bin/env python3
# [Flow: Step 1 (Celery 인스턴스 생성) -> Step 2 (broker/backend 연결) -> Step 3 (tasks 모듈 등록)]
from celery import Celery

from .config import settings

celery = Celery(
    "proof",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["backend.workers.tasks"],
)

celery.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 대용량 파일 변환(최대 ~24시간) 시 Redis visibility timeout으로 인한 재시도 방지
    broker_transport_options={"visibility_timeout": 86400},
    visibility_timeout=86400,
    beat_schedule={
        # "cleanup-expired-uploads": {
        #     "task": "backend.workers.tasks.cleanup_expired_uploads",
        #     "schedule": 3600.0,
        # },
        # 실제 Storage 삭제는 별도 아카이빙 스토리지 구성 전까지 수행하지 않는다.
        "auto-recharge-retry": {
            "task": "backend.workers.tasks.auto_recharge_retry",
            "schedule": 86400.0,  # 1일 간격
        },
    },
)
