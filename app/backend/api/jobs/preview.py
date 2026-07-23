from __future__ import annotations

import logging
from io import BytesIO
from pathlib import Path

import fitz
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ...auth.api_key_auth import require_api_key_or_session
from ...auth.supabase_auth import CurrentUser
from ...core import cache, media_loader, pdf_preview_converter, supabase_client
from ...db.models import Job
from ...db.session import get_db
from ._shared import (
    _detect_source_type,
    _estimate_page_image_dpi,
    _get_file_names,
    _get_markdown_content,
    _image_files,
    _job_summary,
    _preview_cache_key,
    _require_job_access,
    _require_job_not_expired,
    _source_files,
    _split_markdown_by_files,
    get_current_user_or_api_key,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api', tags=['jobs'])

@router.get("/jobs/{job_id}/preview")
def preview_job(
    job_id: str,
    start_page: int = Query(1, ge=1, description="시작 페이지 번호"),
    end_page: int | None = Query(None, ge=1, description="종료 페이지 번호(미지정 시 마지막 페이지)"),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """완료된 작업의 마크다운 결과를 페이지 단위로 조회한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if not (
        job.result_md_storage_path
        or job.result_edited_md_storage_path
        or job.result_md_path
        or job.result_edited_md_path
    ):
        detail = f"Result file not ready (status={job.status}, md_path={job.result_md_storage_path or '-'}, edited_path={job.result_edited_md_storage_path or '-'}, error_log={job.error_log or '-'}"
        raise HTTPException(status_code=400, detail=detail)

    cache_key = _preview_cache_key(job_id, start_page, end_page)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate preview: {e}")

    # [Flow: 파일 마커(`<!-- 파일 N -->`) 기준으로 분할 -> start_page/end_page를 파일 번호로 해석]
    # _split_markdown_by_files는 파일 마커가 없으면 전체를 1개 파일로 반환한다.
    files = _split_markdown_by_files(markdown)
    file_nums = [num for num, _ in files]
    last_file = max(file_nums) if file_nums else 1
    effective_end = end_page if end_page is not None else last_file
    if effective_end < start_page:
        effective_end = start_page

    # [Flow: 파일 마커를 영어 페이지 마커 형식으로 변환하여 partial_markdown 구성]
    # SimpleEditor/MarkdownPreview는 `<!-- Page N -->`를 숨김 처리하므로 사용자에게 보이지 않음.
    # 현재 `start_page`/`end_page`는 파일 번호를 의미한다.
    selected = [(num, content) for num, content in files if start_page <= num <= effective_end]
    partial_markdown = "\n\n---\n\n".join(
        f"<!-- Page {num} -->\n\n{content}" for num, content in selected
    )

    source_url = None
    source_type = None
    image_urls: list[str] = []
    if job.pdf_storage_path:
        try:
            source_type = _detect_source_type(job)
            # [Flow: PDF는 원본 서명 URL, docx/hwp/pptx는 _source_files 이후 변환된 PDF preview URL 사용]
            if source_type == "pdf":
                source_url = supabase_client.get_signed_download_url(job.pdf_storage_path, bucket="pdfs", expires_in=3600)
        except Exception:
            pass

    images = _image_files(job)
    if images:
        source_type = "images"
        for page_num, info in images:
            if start_page <= page_num <= effective_end:
                try:
                    url = supabase_client.get_signed_download_url(info["storage_path"], bucket="pdfs", expires_in=3600)
                    image_urls.append(url)
                except Exception:
                    pass

    source_files = _source_files(job)

    # [Flow: docx/hwp/pptx의 source_url은 변환된 PDF preview URL로 설정]
    if source_type in ("docx", "hwp", "pptx"):
        source_url = next(
            (
                f.get("preview_url") or f.get("url")
                for f in source_files
                if f.get("type") == source_type
            ),
            source_url,
        )

    # [Flow: extracted_files의 result_markdown을 source_files에 병합]
    # _source_files는 storage_path가 있는 파일만 반환하므로,
    # 마크다운만 있고 storage_path가 없는 파일의 result_markdown을 별도로 보존한다.
    extracted = job.extracted_files or []
    if extracted and len(extracted) > len(source_files):
        existing_filenames = {f.get("filename") for f in source_files}
        for idx, info in enumerate(extracted):
            if not isinstance(info, dict):
                continue
            md = info.get("result_markdown", "")
            if not md:
                continue
            fname = info.get("filename") or info.get("path") or f"파일 {idx + 1}"
            if fname not in existing_filenames:
                source_files.append({
                    "filename": fname,
                    "type": info.get("type", ""),
                    "result_markdown": md,
                    "source_kind": "original",
                    "source_index": idx,
                    "status": info.get("status", "done"),
                })

    result = {
        "job": _job_summary(job),
        "markdown": partial_markdown,
        "source_url": source_url,
        "source_type": source_type,
        "image_urls": image_urls,
        "source_files": source_files,
        "start_page": start_page,
        "end_page": effective_end,
        "last_page": last_file,
    }
    cache.set(cache_key, result, ttl_seconds=300)
    return result



@router.get("/jobs/{job_id}/preview/pages")
def preview_job_pages(
    job_id: str,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """완료된 작업의 페이지 목록 메타데이터를 반환한다."""
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)
    if not (
        job.result_md_storage_path
        or job.result_edited_md_storage_path
        or job.result_md_path
        or job.result_edited_md_path
    ):
        detail = f"Result file not ready (status={job.status}, md_path={job.result_md_storage_path or '-'}, edited_path={job.result_edited_md_storage_path or '-'}, error_log={job.error_log or '-'}"
        raise HTTPException(status_code=400, detail=detail)

    try:
        markdown = _get_markdown_content(job)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to generate preview: {e}")

    # [Flow: 파일 마커 기준으로 분할 -> 각 파일의 메타데이터(파일명, 미리보기) 반환]
    # `page_num`은 파일 번호(1-based)를 의미한다.
    files = _split_markdown_by_files(markdown)
    file_names = _get_file_names(job)
    out_pages = []
    for num, content in files:
        filename = file_names[num - 1] if num - 1 < len(file_names) else f"파일 {num}"
        entry: dict = {
            "page_num": num,
            "filename": filename,
            "preview": content[:200].replace("\n", " ").strip(),
        }
        out_pages.append(entry)

    return {
        "job": _job_summary(job),
        "total_pages": len(files),
        "pages": out_pages,
    }



@router.get("/jobs/{job_id}/page-image")
def get_job_page_image(
    job_id: str,
    page_no: int = Query(..., description="1-based 페이지 번호", ge=1),
    dpi: int | None = Query(None, description="렌더링 DPI (생략 시 페이지 내 이미지 해상도에서 자동 추정, 150~300)", ge=150, le=300),
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (PDF 확보) -> Step 3 (페이지 이미지 렌더링)
          -> Step 4 (PNG 업로드) -> Step 5 (signed URL 반환)]

    VLLM/vision 모델이 PDF 특정 페이지를 직접 볼 수 있도록 페이지 이미지를 생성한다.
    """
    import fitz

    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    storage_path = job.searchable_pdf_storage_path
    bucket = "pdfs"
    if not storage_path:
        files = job.extracted_files or []
        for info in files:
            sp = info.get("searchable_pdf_storage_path")
            if sp:
                storage_path = sp
                break
    if not storage_path and job.pdf_storage_path:
        storage_path = job.pdf_storage_path
        bucket = "pdfs"

    if not storage_path:
        raise HTTPException(status_code=404, detail="No PDF available for this job")

    try:
        client = supabase_client.get_service_client()
        pdf_bytes = client.storage.from_(bucket).download(storage_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Failed to download PDF: {e}")

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        if page_no < 1 or page_no > doc.page_count:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid page_no {page_no}. PDF has {doc.page_count} pages.",
            )
        page = doc[page_no - 1]
        resolved_dpi = dpi
        if resolved_dpi is None:
            estimated = _estimate_page_image_dpi(page, doc)
            resolved_dpi = 300 if estimated <= 0 else max(150, min(300, estimated))
        pix = page.get_pixmap(dpi=resolved_dpi)
        img_bytes = pix.tobytes("png")
    finally:
        doc.close()

    output_path = f"{job_id}/page-images/page-{page_no}-{resolved_dpi}dpi.png"
    try:
        client.storage.from_("results").upload(
            output_path,
            img_bytes,
            {"content-type": "image/png", "upsert": "true"},
        )
        signed_url = supabase_client.get_signed_download_url(
            output_path, bucket="results", expires_in=3600
        )
        if not signed_url:
            raise HTTPException(status_code=500, detail="Failed to generate signed URL")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload page image: {e}")

    return {
        "page_no": page_no,
        "dpi": resolved_dpi,
        "width": pix.width,
        "height": pix.height,
        "image_url": signed_url,
    }



@router.get("/jobs/{job_id}/ocr-images/{storage_path:path}")
def get_job_ocr_image(
    job_id: str,
    storage_path: str,
    user: CurrentUser = Depends(get_current_user_or_api_key),
    db: Session = Depends(get_db),
):
    """[Flow: Step 1 (job 조회) -> Step 2 (Storage path 검증) -> Step 3 (results 버킷 다운로드)
          -> Step 4 (Content-Type 설정 후 반환)]

    마크다운에 저장된 inline OCR 이미지를 proxy한다.
    """
    job = db.get(Job, job_id)
    _require_job_access(job, user)
    _require_job_not_expired(job)

    if ".." in storage_path or storage_path.split("/")[0] != job_id:
        raise HTTPException(status_code=400, detail="Invalid storage path")

    try:
        client = supabase_client.get_service_client()
        data = client.storage.from_("results").download(storage_path)
    except Exception as e:
        logger.warning(f"[get-job-ocr-image:{job_id}] 이미지 다운로드 실패: {e}")
        raise HTTPException(status_code=404, detail="Image not found")

    content_type, _ = mimetypes.guess_type(storage_path)
    if not content_type:
        content_type = "application/octet-stream"
    return Response(
        content=data,
        media_type=content_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )



