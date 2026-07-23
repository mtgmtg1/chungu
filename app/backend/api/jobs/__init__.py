"""api/jobs 패키지 — 기능별로 분할된 Job 라우터 모듈들을 하나의 router로 조립.

main.py의 `app.include_router(jobs.router)`는 이 패키지의 __init__.py에서
노출하는 `router`를 사용한다. 모든 엔드포인트 경로는 기존과 동일하다.
"""
from fastapi import APIRouter

from . import admin, annotations, download, lifecycle, preview, result, uploads

router = APIRouter(prefix="/api", tags=["jobs"])

router.include_router(uploads.router)
router.include_router(lifecycle.router)
router.include_router(download.router)
router.include_router(result.router)
router.include_router(preview.router)
router.include_router(annotations.router)
router.include_router(admin.router)

# 테스트 호환성 re-export
from .annotations import get_job_result_json, save_user_annotations, search_job_text
from ._shared import (
    _build_source_file_item,
    _detect_source_type,
    _expand_match_to_line,
    _get_markdown_content,
    _load_all_annotations,
    _require_job_access,
    _require_job_not_expired,
    _resolve_annotations_json_path,
    _source_files,
    _split_markdown_by_files,
    _split_markdown_by_pages,
)

# 테스트가 monkeypatch/patch로 접근하는 모듈 속성 re-export
from ...core import cache, pdf_preview_converter, supabase_client

__all__ = [
    "router",
    "save_user_annotations",
    "_split_markdown_by_files",
    "_source_files",
    "_split_markdown_by_pages",
    "get_job_result_json",
    "search_job_text",
    "_load_all_annotations",
    "_resolve_annotations_json_path",
    "_get_markdown_content",
    "_build_source_file_item",
    "_detect_source_type",
    "_expand_match_to_line",
]
