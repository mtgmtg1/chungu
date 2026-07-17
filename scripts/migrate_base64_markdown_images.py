#!/usr/bin/env python3
# [Flow: Step 1 (DB에서 후보 Job 목록 조회) -> Step 2 (각 Job의 result_markdown/base64 이미지 검출)
#       -> Step 3 (rewrite_inline_images_to_storage로 base64 -> Storage proxy URL 치환)
#       -> Step 4 (새 markdown Storage 업로드 및 DB 갱신) -> Step 5 (처리 통계 출력)]
"""기존 Job의 result_markdown에 포함된 base64 인라인 이미지를 Supabase Storage로 외부화한다.

Usage:
    python scripts/migrate_base64_markdown_images.py
    python scripts/migrate_base64_markdown_images.py --apply --limit 100

기본적으로 dry-run 모드로 실행되며, --apply 플래그가 있어야만 DB/Storage를 실제로 갱신한다.
"""
import argparse
import logging
import os
import sys
import tempfile
from pathlib import Path

# app/ 경로를 import path에 추가 (backend 패키지로 상대 import 가능하도록)
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(script_dir, "..", "app"))

from backend.core.markdown_image_rewriter import rewrite_inline_images_to_storage
from backend.core.markdown_sanitizer import sanitize_markdown_for_llm
from backend.core import supabase_client
from backend.db.models import Job
from backend.db.session import SessionLocal
from sqlalchemy.orm.attributes import flag_modified

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


def _contains_base64_image(text: str) -> bool:
    """문자열에 data:image base64 URI가 포함되어 있는지 확인한다."""
    return 'data:image' in (text or '')


def _rewrite_extracted_files(extracted_files: list[dict], job_id: str) -> tuple[list[dict], int]:
    """extracted_files의 result_markdown에서 base64 이미지를 제거/외부화한다."""
    changed = 0
    updated = []
    for info in extracted_files:
        md = info.get("result_markdown", "") or ""
        if _contains_base64_image(md):
            info["result_markdown"] = rewrite_inline_images_to_storage(md, job_id)
            changed += 1
        updated.append(info)
    return updated, changed


def _rewrite_storage_markdown(job: Job) -> tuple[str, int, int]:
    """Job의 result_md / result_edited_md Storage 파일을 다운로드하여 base64 이미지를 외부화한다.

    Returns:
        (source_key, rewritten_markdown, image_count) 또는 변경이 없으면 ("", "", 0)
    """
    client = supabase_client.get_service_client()
    sources = [
        ("edited_md", job.result_edited_md_storage_path),
        ("md", job.result_md_storage_path),
    ]
    for key, storage_path in sources:
        if not storage_path:
            continue
        try:
            data = client.storage.from_("results").download(storage_path)
        except Exception as e:
            logger.warning(f"[migrate:{job.id}] {storage_path} 다운로드 실패: {e}")
            continue
        markdown = data.decode("utf-8", errors="replace")
        if not _contains_base64_image(markdown):
            continue
        cleaned = rewrite_inline_images_to_storage(markdown, job.id)
        return key, cleaned, 1
    return "", "", 0


def _migrate_job(job: Job, dry_run: bool) -> dict:
    """단일 Job의 마크다운을 마이그레이션하고 변경 통계를 반환한다."""
    stats = {"storage_updated": False, "extracted_files_changed": 0, "images_found": False}

    storage_key, cleaned_markdown, _ = _rewrite_storage_markdown(job)
    if storage_key:
        stats["images_found"] = True
        stats["storage_updated"] = True
        if not dry_run:
            with tempfile.TemporaryDirectory() as tmpdir:
                md_path = Path(tmpdir) / f"{storage_key}.md"
                md_path.write_text(cleaned_markdown, encoding="utf-8")
                paths = supabase_client.upload_result(
                    job.id,
                    md_path=md_path if storage_key == "md" else None,
                    edited_md_path=md_path if storage_key == "edited_md" else None,
                )
                if storage_key == "md":
                    job.result_md_storage_path = paths.get("md", job.result_md_storage_path)
                else:
                    job.result_edited_md_storage_path = paths.get("edited_md", job.result_edited_md_storage_path)

    extracted = job.extracted_files or []
    updated_extracted, changed = _rewrite_extracted_files(extracted, job.id)
    if changed:
        stats["images_found"] = True
        stats["extracted_files_changed"] = changed
        if not dry_run:
            job.extracted_files = updated_extracted
            flag_modified(job, "extracted_files")

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description="기존 result_markdown의 base64 이미지를 Storage로 외부화")
    parser.add_argument("--apply", action="store_true", help="dry-run을 끄고 실제 DB/Storage 갱신")
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 Job 수")
    parser.add_argument("--batch", type=int, default=50, help="커밋 단위(batch) Job 수")
    args = parser.parse_args()

    dry_run = not args.apply
    if dry_run:
        logger.info("[migrate] dry-run 모드입니다. --apply를 추가하면 실제로 갱신됩니다.")

    session = SessionLocal()
    try:
        query = session.query(Job).order_by(Job.id)
        if args.limit:
            query = query.limit(args.limit)

        jobs = list(query)
        logger.info(f"[migrate] 총 {len(jobs)}개 Job 검사")

        total_changed = 0
        batch_changed = 0
        for idx, job in enumerate(jobs, 1):
            try:
                stats = _migrate_job(job, dry_run)
                if stats["images_found"]:
                    total_changed += 1
                    batch_changed += 1
                    logger.info(
                        f"[migrate:{job.id}] storage_updated={stats['storage_updated']}, "
                        f"extracted_files_changed={stats['extracted_files_changed']}"
                    )
            except Exception as e:
                logger.exception(f"[migrate:{job.id}] 처리 실패: {e}")
                if not dry_run:
                    session.rollback()
                continue

            if not dry_run and batch_changed >= args.batch:
                session.commit()
                logger.info(f"[migrate] {idx}개 Job까지 커밋 완료 ({batch_changed}개 변경)")
                batch_changed = 0

        if not dry_run:
            session.commit()
            logger.info(f"[migrate] 최종 커밋 완료. 총 {total_changed}개 Job 변경")
        else:
            logger.info(f"[migrate] dry-run 완료. 총 {total_changed}개 Job에서 base64 이미지 발견")
    finally:
        session.close()


if __name__ == "__main__":
    main()
