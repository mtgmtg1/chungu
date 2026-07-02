#!/usr/bin/env python3
# [Flow: Step 1 (job 로드) -> Step 2 (Storage에서 입력 다운로드) -> Step 3 (PDF: vision|hybrid / 미디어: 파일별 처리) -> Step 4 (Excel/CSV/MD 저장) -> Step 5 (Storage 업로드) -> Step 6 (DB/이메일)]
import json
import logging
import tempfile
import time
import traceback
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from pypdf import PdfReader
from sqlalchemy import text as sql_text

from ..celery_app import celery
from celery.signals import worker_ready
from ..config import settings
from ..core import archive_handler, converter, excel_writer, media_loader, merge, supabase_client
from ..core.ocr_client import has_pdf_text_layer
from ..core.pipeline_docling import run_docling, run_hwp
from ..core.pipeline_hybrid import run_hybrid
from ..core.pipeline_media import run_media
from ..core.pipeline_vision import run_vision
from ..db.models import Job
from ..db.session import SessionLocal
from .. import email_sender, settings_store

logger = logging.getLogger(__name__)

MAX_PAGE_SIDE_MM = 350
MM_PER_PT = 0.3528
MAX_RETRY_COUNT = 3

# [Flow: Step 1 (worker_ready 시그널 수신) -> Step 2 (DB에서 중단된 job 조회) -> Step 3 (retry_count < 3인 job 재시도) -> Step 4 (>= 3인 job error로 변경)]
@worker_ready.connect
def recover_stuck_jobs(sender=None, **kwargs):
    """Worker 시작 시 중단된 job(queued/rendering/ocr/merging)을 자동으로 재시도한다."""
    time.sleep(3)

    db = None
    for attempt in range(2):
        try:
            db = SessionLocal()
            break
        except Exception as e:
            logger.warning(f"[recover] DB 연결 실패 (attempt {attempt + 1}/2): {e}")
            if attempt == 0:
                time.sleep(5)

    if db is None:
        logger.error("[recover] DB 연결 실패, 중단된 job 복구를 건너뜁니다")
        return

    try:
        stuck_statuses = ("queued", "rendering", "ocr", "merging")
        jobs = db.query(Job).filter(Job.status.in_(stuck_statuses)).all()

        if not jobs:
            logger.info("[recover] 중단된 job 없음")
            return

        recovered = 0
        exhausted = 0

        for job in jobs:
            if job.retry_count < MAX_RETRY_COUNT:
                job.retry_count += 1
                job.status = "queued"
                db.commit()
                run_job.delay(job.id)
                recovered += 1
                logger.info(f"[recover] job {job.id} 재시도 ({job.retry_count}/{MAX_RETRY_COUNT})")
            else:
                job.status = "error"
                job.error_log = (job.error_log + f"\n재시도 한계 초과 (server restart, {MAX_RETRY_COUNT}회)").strip()
                job.finished_at = datetime.now(timezone.utc)
                db.commit()
                exhausted += 1
                logger.warning(f"[recover] job {job.id} 재시도 한계 초과, error로 전환")

        logger.info(f"[recover] 복구 완료: {recovered}개 재시도, {exhausted}개 error 전환")
    except Exception as e:
        logger.exception(f"[recover] 중단된 job 복구 중 오류: {e}")
    finally:
        db.close()


def _set_status(db, job: Job, status: str) -> None:
    job.status = status
    db.commit()


def count_oversized_pages(file_path: Path) -> tuple[int, int]:
    """PDF에서 350mm를 초과하는 페이지 수를 반환한다. (oversized_count, total_pages)"""
    try:
        reader = PdfReader(str(file_path))
        total = len(reader.pages)
        oversized = 0
        for page in reader.pages:
            w = float(page.mediabox.width) * MM_PER_PT
            h = float(page.mediabox.height) * MM_PER_PT
            if w > MAX_PAGE_SIDE_MM or h > MAX_PAGE_SIDE_MM:
                oversized += 1
        return oversized, total
    except Exception:
        return 0, 0


@celery.task(name="backend.workers.tasks.run_job")
def run_job(job_id: str) -> dict:
    """업로드된 파일(단일 PDF 또는 멀티미디어)을 변환하는 메인 워커 태스크."""
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

    # 중복 실행 방지: status가 queued가 아니면 스킵
    if job.status != "queued":
        db.close()
        return {"job_id": job_id, "skipped": True, "reason": f"status={job.status}"}

    try:
        # Step 1: 런타임 설정 주입
        endpoint = job.endpoint or settings_store.get_setting(db, "llm_endpoint")
        model = job.model or settings_store.get_setting(db, "llm_model")
        api_key = settings_store.get_setting(db, "llm_api_key")
        columns = job.columns or []
        work_dir = Path(settings.data_dir) / "jobs" / job_id
        work_dir.mkdir(parents=True, exist_ok=True)
        out_dir = work_dir / "result"
        out_dir.mkdir(parents=True, exist_ok=True)

        errors: list[str] = []
        tabs: dict[str, list[dict]] = {}
        rows: list[dict] = []
        page_tables: list[tuple[int, str]] = []
        results: list[tuple[str, str, str]] = []
        all_page_contents: list[tuple[int, str]] = []
        extracted_info: list[dict] = []
        fmt = ""

        # media LLM 설정 (PDF vision 및 멀티미디어 공통 사용)
        media_ep = settings_store.get_setting(db, "media_llm_endpoint") or settings.media_llm_endpoint
        media_mdl = settings_store.get_setting(db, "media_llm_model") or settings.media_llm_model
        media_key = settings_store.get_setting(db, "media_llm_api_key") or settings.media_llm_api_key
        llm_workers = int(settings_store.get_setting(db, "llm_max_workers") or settings.llm_max_workers)
        media_workers = int(settings_store.get_setting(db, "media_max_workers") or settings.media_max_workers)

        # Docling 설정
        docling_enabled = settings_store.get_setting(db, "docling_enabled") == "1"
        ocr_model = job.ocr_model or "premium"
        ocr_engine = job.ocr_engine or "easyocr"
        # 기본모델은 refinement 비활성화
        use_refinement = docling_enabled and job.use_docling_refinement and (settings_store.get_setting(db, "docling_refinement_enabled") == "1") and (ocr_model == "premium")
        docling_workers = int(settings_store.get_setting(db, "docling_max_workers") or settings.docling_max_workers)

        # Step 2: 단일 PDF/오피스 문서 처리
        # [Flow: pipeline=vision -> 페이지별 PNG 렌더 후 Gemma4 직접 호출 / pipeline=docling -> Docling OCR + 선택적 LLM refinement]
        if job.file_type in media_loader.DOCLING_TYPES:
            input_ext = Path(job.original_filename).suffix or ".pdf"
            input_path = work_dir / f"input{input_ext}"
            if job.pdf_storage_path:
                input_bytes = supabase_client.download_pdf(job.pdf_storage_path)
                input_path.write_bytes(input_bytes.read())
            else:
                local_candidates = [p for p in work_dir.glob("*") if p.is_file()]
                if not local_candidates:
                    raise FileNotFoundError("입력 파일을 찾을 수 없습니다")
                input_path = local_candidates[0]

            def on_progress(done: int, total: int) -> None:
                job.done_pages = done
                job.total_pages = total
                db.commit()

            def on_error(page: int, msg: str) -> None:
                errors.append(f"p{page}: {msg}")

            # [Flow: Step 1 (페이지 크기 검사) -> Step 2 (전체 초과 시 스킵) -> Step 3 (기본변환: 텍스트 레이어 있음→Docling / 없음→run_vision / 고급변환: 무조건 run_vision) -> Step 4 (비-PDF: Docling)]
            oversized, total_pages = count_oversized_pages(input_path)
            if oversized > 0:
                errors.append(f"{input_path.name}: {oversized}페이지가 350mm를 초과하여 파싱할 수 없습니다")
            if oversized == total_pages and total_pages > 0:
                page_tables = []
                fmt = "markdown"
            elif input_path.suffix.lower() == ".pdf" and ocr_model == "basic" and has_pdf_text_layer(str(input_path)):
                _set_status(db, job, "ocr")
                page_tables = run_docling(
                    input_path,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    use_refinement=use_refinement,
                    max_tokens=10000,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=on_progress,
                    on_error=on_error,
                    ocr_engine=ocr_engine,
                )
                fmt = "markdown"
            elif input_path.suffix.lower() == ".pdf":
                _set_status(db, job, "ocr")
                page_tables = run_vision(
                    str(input_path),
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    dpi=job.dpi,
                    max_tokens=10000,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=on_progress,
                    on_error=on_error,
                )
                fmt = "markdown"
            else:
                _set_status(db, job, "ocr")
                page_tables = run_docling(
                    input_path,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    use_refinement=use_refinement,
                    max_tokens=10000,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    on_progress=on_progress,
                    on_error=on_error,
                    ocr_engine=ocr_engine,
                )
                fmt = "markdown"

            _set_status(db, job, "merging")
            rows = merge.merge_pages(page_tables, columns, fmt=fmt)
            filename = Path(job.original_filename).name or "input.pdf"
            tabs[filename] = excel_writer.build_pdf_rows(filename, page_tables, columns)

            job.total_files = 1
            job.done_files = 1
            job.total_pages = len(page_tables)
            job.done_pages = len(page_tables)
            db.commit()

        elif job.file_type in media_loader.HWP_TYPES:
            # Step 2b: 단일 HWP/HWPX 문서 처리 (pyhwp 기반)
            input_ext = Path(job.original_filename).suffix or ".hwp"
            input_path = work_dir / f"input{input_ext}"
            if job.pdf_storage_path:
                input_bytes = supabase_client.download_pdf(job.pdf_storage_path)
                input_path.write_bytes(input_bytes.read())
            else:
                local_candidates = [p for p in work_dir.glob("*") if p.is_file()]
                if not local_candidates:
                    raise FileNotFoundError("입력 파일을 찾을 수 없습니다")
                input_path = local_candidates[0]

            def on_progress(done: int, total: int) -> None:
                job.done_pages = done
                job.total_pages = total
                db.commit()

            def on_error(page: int, msg: str) -> None:
                errors.append(f"p{page}: {msg}")

            _set_status(db, job, "ocr")
            page_tables = run_hwp(
                input_path,
                str(work_dir),
                columns,
                endpoint,
                model,
                api_key,
                extra_prompt=job.prompt,
                use_refinement=use_refinement,
                max_tokens=10000,
                media_endpoint=media_ep,
                media_model=media_mdl,
                media_api_key=media_key,
                on_progress=on_progress,
                on_error=on_error,
            )
            fmt = "markdown"

            _set_status(db, job, "merging")
            rows = merge.merge_pages(page_tables, columns, fmt=fmt)
            filename = Path(job.original_filename).name or "input.hwp"
            tabs[filename] = excel_writer.build_pdf_rows(filename, page_tables, columns)

            job.total_files = 1
            job.done_files = 1
            job.total_pages = len(page_tables)
            job.done_pages = len(page_tables)
            db.commit()
        else:
            # Step 3: 멀티미디어 처리
            if job.pdf_storage_path:
                input_bytes = supabase_client.download_pdf(job.pdf_storage_path)
                input_data = input_bytes.read()
            else:
                local_candidates = list(work_dir.glob("*"))
                if not local_candidates:
                    raise FileNotFoundError("입력 파일을 찾을 수 없습니다")
                input_data = local_candidates[0].read_bytes()

            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)
                input_file = tmp_path / (job.original_filename or "input.zip")
                input_file.write_bytes(input_data)

                # 확장자가 없는 zip 파일도 인식할 수 있도록 보정
                if not archive_handler.is_archive(input_file.name) and media_loader.detect_file_type(input_file) == "archive":
                    input_file = input_file.with_suffix(".zip")
                    input_file.write_bytes(input_data)

                extracted: list[Path] = []
                if archive_handler.is_archive(input_file.name):
                    archive_dest = tmp_path / "extracted"
                    archive_dest.mkdir(parents=True, exist_ok=True)
                    extracted = archive_handler.extract_all_recursive(input_file.name, input_data, archive_dest)
                else:
                    # 단일 파일이면 다른 파일도 함께 있는지 확인; Storage에는 zip으로 업로드됨
                    if input_file.name.endswith(".zip"):
                        with zipfile.ZipFile(input_file, "r") as zf:
                            zf.extractall(tmp_path)
                        extracted = [p for p in tmp_path.rglob("*") if p.is_file()]
                    else:
                        extracted = [input_file]

                # 파일 유형별 분류
                media_files: list[tuple[str, Path]] = []
                file_markdowns_by_name: dict[str, str] = {}
                docling_files: list[Path] = []
                hwp_files: list[Path] = []
                for fp in extracted:
                    ftype = media_loader.detect_file_type(fp)
                    if ftype in ("image", "audio", "video"):
                        media_files.append((ftype, fp))
                    elif ftype in media_loader.DOCLING_TYPES:
                        docling_files.append(fp)
                    elif ftype in media_loader.HWP_TYPES:
                        hwp_files.append(fp)

                # [Flow: Step 1 (총 파일 수 설정 + 상태 ocr로 변경) -> Step 2 (Docling/HWP 파일 순차 처리하며 done_files 증가) -> Step 3 (미디어 파일 처리하며 done_files 증가)]
                total_to_process = len(docling_files) + len(hwp_files) + len(media_files)
                job.total_files = total_to_process
                job.done_files = 0
                _set_status(db, job, "ocr")
                db.commit()

                for fp in docling_files:
                    docling_errors: list[str] = []
                    # [Flow: Step 1 (페이지 크기 검사) -> Step 2 (전체 초과 시 스킵) -> Step 3 (Docling 처리)]
                    oversized, total_fp_pages = count_oversized_pages(fp)
                    if oversized > 0:
                        errors.append(f"{fp.name}: {oversized}페이지가 350mm를 초과하여 파싱할 수 없습니다")
                    if oversized == total_fp_pages and total_fp_pages > 0:
                        docling_tables = []
                    else:
                        docling_tables = run_docling(
                            fp,
                            str(work_dir),
                            columns,
                            endpoint,
                            model,
                            api_key,
                            extra_prompt=job.prompt,
                            use_refinement=use_refinement,
                            media_endpoint=media_ep,
                            media_model=media_mdl,
                            media_api_key=media_key,
                            on_progress=lambda done, total: None,
                            on_error=lambda page, msg: docling_errors.append(f"p{page}: {msg}"),
                            ocr_engine=ocr_engine,
                        )
                    for _, table in docling_tables:
                        all_page_contents.append((len(all_page_contents) + 1, table))
                    tabs[fp.name] = excel_writer.build_pdf_rows(fp.name, docling_tables, columns)
                    file_markdowns_by_name[fp.name] = converter.build_layout_markdown_string(docling_tables)
                    errors.extend(docling_errors)
                    job.done_files += 1
                    db.commit()

                for fp in hwp_files:
                    hwp_errors: list[str] = []
                    hwp_tables = run_hwp(
                        fp,
                        str(work_dir),
                        columns,
                        endpoint,
                        model,
                        api_key,
                        extra_prompt=job.prompt,
                        use_refinement=use_refinement,
                        media_endpoint=media_ep,
                        media_model=media_mdl,
                        media_api_key=media_key,
                        on_progress=lambda done, total: None,
                        on_error=lambda page, msg: hwp_errors.append(f"p{page}: {msg}"),
                        ocr_engine=ocr_engine,
                    )
                    for _, table in hwp_tables:
                        all_page_contents.append((len(all_page_contents) + 1, table))
                    tabs[fp.name] = excel_writer.build_pdf_rows(fp.name, hwp_tables, columns)
                    file_markdowns_by_name[fp.name] = converter.build_layout_markdown_string(hwp_tables)
                    errors.extend(hwp_errors)
                    job.done_files += 1
                    db.commit()

                def on_media_progress(done: int, total: int) -> None:
                    job.done_files = len(docling_files) + len(hwp_files) + done
                    job.total_files = total_to_process
                    db.commit()

                def on_media_error(filename: str, msg: str) -> None:
                    errors.append(f"{filename}: {msg}")

                results = run_media(
                    media_files,
                    str(work_dir),
                    columns,
                    endpoint,
                    model,
                    api_key,
                    extra_prompt=job.prompt,
                    media_endpoint=media_ep,
                    media_model=media_mdl,
                    media_api_key=media_key,
                    workers=llm_workers + media_workers,
                    on_progress=on_media_progress,
                    on_error=on_media_error,
                    ocr_model=ocr_model,
                    ocr_engine=ocr_engine,
                )

                for filename, position, table in results:
                    ftype = media_loader.detect_file_type(Path(filename))
                    all_page_contents.append((len(all_page_contents) + 1, table or ""))
                    tabs[filename] = excel_writer.build_media_rows(filename, ftype, position, table)
                    file_markdowns_by_name[filename] = converter.build_layout_markdown_string([(1, table or "")])

                # duration 정보 업데이트
                durations = {
                    "audio": 0,
                    "video": 0,
                }
                for ftype, fp in media_files:
                    if ftype in durations:
                        durations[ftype] += media_loader.get_media_duration_seconds(fp)
                job.media_duration_seconds = durations["audio"] + durations["video"]

                # 추출 파일 정보 업데이트 (이미지는 Storage에 개별 업로드)
                extracted_info = []
                for p in extracted:
                    ftype = media_loader.detect_file_type(p)
                    info = {
                        "path": str(p.name),
                        "type": ftype,
                        "size": p.stat().st_size,
                        "duration": media_loader.get_media_duration_seconds(p) if ftype in ("audio", "video") else 0,
                        "result_markdown": file_markdowns_by_name.get(p.name, ""),
                    }
                    if ftype == "image":
                        try:
                            info["storage_path"] = supabase_client.upload_image(job_id, p, p.name)
                        except Exception as e:
                            errors.append(f"{p.name}: 이미지 업로드 실패 {e}")
                    elif ftype in media_loader.DOCLING_TYPES or ftype in media_loader.HWP_TYPES:
                        try:
                            info["storage_path"] = supabase_client.upload_pdf(job_id, p.read_bytes(), p.name)
                        except Exception as e:
                            errors.append(f"{p.name}: 문서 업로드 실패 {e}")
                    extracted_info.append(info)
                job.extracted_files = extracted_info
                job.total_files = len(extracted)
                job.done_files = len(extracted)

        # Step 4: CSV + MD 저장 (xlsx는 별도 LLM 변환으로 제공)
        _set_status(db, job, "merging")
        csv_path = out_dir / "result.csv"
        md_path = out_dir / "result.md"
        if rows:
            converter.write_csv(rows, columns, csv_path)
        else:
            # 미디어 결과를 CSV로도 변환
            merged_rows: list[dict] = []
            for sheet_rows in tabs.values():
                merged_rows.extend(sheet_rows)
            if merged_rows:
                converter.write_csv(merged_rows, columns, csv_path)

        # MD는 원문서 레이아웃을 보존한 마크다운으로 출력 (vision PDF / 미디어)
        if extracted_info:
            converter.write_combined_file_markdowns(
                [info.get("result_markdown", "") for info in extracted_info], md_path
            )
        elif page_tables and fmt == "markdown":
            converter.write_layout_markdown(page_tables, md_path)
        elif rows:
            converter.write_markdown(rows, columns, md_path)
        elif all_page_contents:
            converter.write_layout_markdown(all_page_contents, md_path)
        elif results:
            # 미디어 결과를 페이지별 마크다운으로 변환
            media_page_tables = [(idx + 1, table or "") for idx, (_, _, table) in enumerate(results)]
            converter.write_layout_markdown(media_page_tables, md_path)
        else:
            merged_rows = []
            for sheet_rows in tabs.values():
                merged_rows.extend(sheet_rows)
            if merged_rows:
                converter.write_markdown(merged_rows, columns, md_path)

        # Step 5: 결과 파일 존재 여부 확인 — 결과가 없으면 error 처리
        has_md = md_path.exists() and md_path.stat().st_size > 0
        has_csv = csv_path.exists() and csv_path.stat().st_size > 0
        if not has_md and not has_csv:
            error_detail = "\n".join(errors) or "모든 페이지 처리 실패"
            logger.error(f"[run_job:{job_id}] 결과 파일 없음, error로 전환: {error_detail}")
            job.status = "error"
            job.error_log = error_detail
            job.finished_at = datetime.now(timezone.utc)
            db.commit()
            return {"job_id": job_id, "error": "no result", "errors": len(errors)}

        # Step 6: Storage에 결과 업로드
        logger.info(f"[run_job:{job_id}] Step 6 시작: csv_path={csv_path}, md_path={md_path}, exists={csv_path.exists()}, {md_path.exists()}")
        try:
            storage_paths = supabase_client.upload_result(
                job_id, csv_path=csv_path if has_csv else None, md_path=md_path if has_md else None
            )
            logger.info(f"[run_job:{job_id}] Storage 업로드 결과: {storage_paths}")
        except Exception as upload_err:
            logger.exception(f"[run_job:{job_id}] Storage 업로드 실패: {upload_err}")
            raise

        # Step 7: DB 업데이트
        expire_days = int(settings_store.get_setting(db, "download_expire_days") or "7")
        job.result_csv_path = str(csv_path)
        job.result_md_path = str(md_path)
        job.result_csv_storage_path = storage_paths.get("csv", "")
        job.result_md_storage_path = storage_paths.get("md", "")
        job.download_token = job_id
        job.expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
        job.error_log = "\n".join(errors)
        job.finished_at = datetime.now(timezone.utc)
        logger.info(f"[run_job:{job_id}] DB 업데이트 직전: md_storage={job.result_md_storage_path}, csv_storage={job.result_csv_storage_path}, status={job.status}")
        _set_status(db, job, "done")
        logger.info(f"[run_job:{job_id}] DB 업데이트 완료: status={job.status}")

        # Step 7: 완료 이메일
        try:
            subject, html = email_sender.build_done_email(job_id, job.original_filename, expire_days)
            email_sender.send_email(db, job.email, subject, html)
        except Exception as e:  # noqa: BLE001
            job.error_log = (job.error_log + f"\n[email] {e}").strip()
            db.commit()

        return {"job_id": job_id, "rows": len(rows), "errors": len(errors)}

    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        job.status = "error"
        job.error_log = (job.error_log + f"\n{tb}").strip()
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        try:
            subject, html = email_sender.build_error_email(job_id, job.original_filename, str(e))
            email_sender.send_email(db, job.email, subject, html)
        except Exception:  # noqa: BLE001
            pass
        return {"job_id": job_id, "error": str(e)}
    finally:
        db.close()


# OCR 업로드 원본 파일의 Supabase Storage 보관 기간 (시간)
UPLOAD_RETENTION_HOURS = 48


# [Flow: Step 1 (48시간 이전 생성된 job 조회) -> Step 2 (pdfs 버킷 원본 파일 삭제) -> Step 3 (DB 경로 참조 제거)]
@celery.task(name="backend.workers.tasks.cleanup_expired_uploads")
def cleanup_expired_uploads() -> dict:
    """created_at 기준 48시간이 지난 job의 원본 업로드 파일을 Storage에서 삭제한다."""
    db = SessionLocal()
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=UPLOAD_RETENTION_HOURS)
        jobs = (
            db.query(Job)
            .filter(Job.created_at < cutoff)
            .filter((Job.pdf_storage_path != "") | (Job.extracted_files.isnot(None)))
            .all()
        )

        cleaned = 0
        skipped = 0
        for job in jobs:
            has_source = bool(job.pdf_storage_path) or any(
                isinstance(info, dict) and info.get("storage_path")
                for info in job.extracted_files or []
            )
            if not has_source:
                skipped += 1
                continue

            try:
                supabase_client.delete_source_files(job)
                supabase_client.clear_source_paths(job)
                db.commit()
                cleaned += 1
                logger.info(f"[cleanup_expired_uploads] {job.id} 원본 파일 삭제 완료")
            except Exception as e:
                db.rollback()
                logger.warning(f"[cleanup_expired_uploads] {job.id} 삭제 중 오류: {e}")

        return {"cleaned": cleaned, "skipped": skipped}
    except Exception as e:
        logger.exception(f"[cleanup_expired_uploads] 태스크 오류: {e}")
        return {"error": str(e)}
    finally:
        db.close()
