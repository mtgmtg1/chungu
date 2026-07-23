"""workers/tasks 패키지 — 태스크별로 분할된 Celery 태스크 모듈.

[Flow: Step 1 (각 서브모듈에서 태스크 import) -> Step 2 (단일 네임스페이스 re-export)
      -> Step 3 (Celery name= 문자열 유지로 브로커 호환성 보장)]

모든 태스크는 기존 name= 문자열(backend.workers.tasks.xxx)을 유지한다.
다른 모듈에서 `from ..workers.tasks import run_job` 등으로 import하는 코드는
이 패키지의 __init__.py에서 re-export하므로 그대로 작동한다.
"""
# 태스크 re-export
from .annotation_tasks import annotate_edit_job, annotate_pdf_job
from .conversion import convert_xlsx_advanced
from .ediscovery_tasks import run_ediscovery
from .job_tasks import recover_stuck_jobs, run_job, run_job_added_files
from .maintenance import (
    auto_recharge_retry,
    cleanup_expired_sandboxes,
    cleanup_expired_uploads,
    grant_monthly_subscription_credits,
)

# 헬퍼 re-export (테스트 호환성)
from ._helpers import (
    _build_and_upload_searchable_pdf,
    _handle_job_failure,
    _image_to_searchable_pdf,
    _register_searchable_pdf_if_text_layer,
    _release_subscription_usage,
    _set_status,
    count_oversized_pages,
)

# 테스트가 tasks.xxx로 접근하는 모듈 속성 re-export
from ...core import pdf_text_layer, supabase_client
from ...core.job_helpers import upload_ocr_layout

__all__ = [
    "run_job",
    "run_job_added_files",
    "recover_stuck_jobs",
    "cleanup_expired_uploads",
    "cleanup_expired_sandboxes",
    "auto_recharge_retry",
    "grant_monthly_subscription_credits",
    "convert_xlsx_advanced",
    "annotate_pdf_job",
    "annotate_edit_job",
    "run_ediscovery",
    # helpers
    "_build_and_upload_searchable_pdf",
    "_set_status",
    "_release_subscription_usage",
    "_handle_job_failure",
    "count_oversized_pages",
    "_register_searchable_pdf_if_text_layer",
    "_image_to_searchable_pdf",
]
