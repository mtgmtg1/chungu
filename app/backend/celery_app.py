#!/usr/bin/env python3
# [Flow: Step 1 (Celery 인스턴스 생성) -> Step 2 (broker/backend 연결) -> Step 3 (tasks 모듈 등록)]
from celery import Celery

from .config import settings

celery = Celery(
    "chungu",
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
)
