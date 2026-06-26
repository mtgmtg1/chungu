#!/usr/bin/env python3
# [Flow: Step 1 (v1 라우터 생성) -> Step 2 (하위 라우터 등록) -> Step 3 (main app에 포함)]
from fastapi import APIRouter

from . import account, jobs, keys

router = APIRouter(prefix="/api/v1", tags=["v1"])
router.include_router(account.router)
router.include_router(keys.router)
router.include_router(jobs.router)
