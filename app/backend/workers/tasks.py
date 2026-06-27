#!/usr/bin/env python3
# [Flow: Step 1 (job 로드) -> Step 2 (Storage에서 입력 다운로드) -> Step 3 (PDF: vision|hybrid / 미디어: 파일별 처리) -> Step 4 (Excel/CSV/MD 저장) -> Step 5 (Storage 업로드) -> Step 6 (DB/이메일)]
import json
import tempfile
import traceback
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..celery_app import celery
from ..config import settings
from ..core import archive_handler, converter, excel_writer, media_loader, merge, supabase_client
from ..core.pipeline_docling import run_docling, run_hwp
from ..core.pipeline_hybrid import run_hybrid
from ..core.pipeline_media import run_media
from ..core.pipeline_vision import run_vision
from ..db.models import Job
from ..db.session import SessionLocal
from .. import email_sender, settings_store


def _set_status(db, job: Job, status: str) -> None:
    job.status = status
    db.commit()


@celery.task(name="backend.workers.tasks.run_job")
def run_job(job_id: str) -> dict:
    """업로드된 파일(단일 PDF 또는 멀티미디어)을 변환하는 메인 워커 태스크."""
    db = SessionLocal()
    job = db.get(Job, job_id)
    if job is None:
        db.close()
        return {"error": "job not found"}

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
        use_refinement = docling_enabled and job.use_docling_refinement and (settings_store.get_setting(db, "docling_refinement_enabled") == "1")
        docling_workers = int(settings_store.get_setting(db, "docling_max_workers") or settings.docling_max_workers)

        # Step 2: 단일 PDF/오피스 문서 처리 (Docling 전용 경로)
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
                for fp in extracted:
                    ftype = media_loader.detect_file_type(fp)
                    if ftype in ("image", "audio", "video"):
                        media_files.append((ftype, fp))
                    elif ftype in media_loader.DOCLING_TYPES:
                        # PDF/오피스/HTML은 Docling 전용 경로로 처리
                        docling_errors: list[str] = []
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
                        )
                        for _, table in docling_tables:
                            all_page_contents.append((len(all_page_contents) + 1, table))
                        tabs[fp.name] = excel_writer.build_pdf_rows(fp.name, docling_tables, columns)
                        file_markdowns_by_name[fp.name] = converter.build_layout_markdown_string(docling_tables)
                        errors.extend(docling_errors)

                    elif ftype in media_loader.HWP_TYPES:
                        # HWP/HWPX는 pyhwp 기반 경로로 처리
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
                        )
                        for _, table in hwp_tables:
                            all_page_contents.append((len(all_page_contents) + 1, table))
                        tabs[fp.name] = excel_writer.build_pdf_rows(fp.name, hwp_tables, columns)
                        file_markdowns_by_name[fp.name] = converter.build_layout_markdown_string(hwp_tables)
                        errors.extend(hwp_errors)

                _set_status(db, job, "ocr")

                def on_media_progress(done: int, total: int) -> None:
                    job.done_files = done
                    job.total_files = total
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

        # Step 5: Storage에 결과 업로드
        storage_paths = supabase_client.upload_result(
            job_id, csv_path=csv_path, md_path=md_path
        )

        # Step 6: DB 업데이트
        expire_days = int(settings_store.get_setting(db, "download_expire_days") or "7")
        job.result_csv_path = str(csv_path)
        job.result_md_path = str(md_path)
        job.result_csv_storage_path = storage_paths.get("csv", "")
        job.result_md_storage_path = storage_paths.get("md", "")
        job.download_token = job_id
        job.expires_at = datetime.now(timezone.utc) + timedelta(days=expire_days)
        job.error_log = "\n".join(errors)
        job.finished_at = datetime.now(timezone.utc)
        _set_status(db, job, "done")

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
