#!/usr/bin/env python3
# [Flow: Step 1 (FastAPI 초기화) -> Step 2 (파일 업로드) -> Step 3 (Docling CPU/VNNI 변환) -> Step 4 (마크다운 + 이미지 추출) -> Step 5 (JSON 반환)]
import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import filetype
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import AcceleratorDevice, AcceleratorOptions, PdfPipelineOptions
from docling_core.types.doc import ImageRefMode


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Chungu Docling Preprocessing Service")

# NUMA-aware VNNI 최적화 환경 변수
DOCLING_NUM_THREADS = int(os.environ.get("DOCLING_NUM_THREADS", "20"))
DOCLING_LAYOUT_BATCH_SIZE = int(os.environ.get("DOCLING_LAYOUT_BATCH_SIZE", "16"))
DOCLING_TABLE_BATCH_SIZE = int(os.environ.get("DOCLING_TABLE_BATCH_SIZE", "4"))
DOCLING_OCR_BATCH_SIZE = int(os.environ.get("DOCLING_OCR_BATCH_SIZE", "4"))


# 확장자 -> InputFormat 매핑
EXTENSION_TO_FORMAT: dict[str, InputFormat] = {
    ".pdf": InputFormat.PDF,
    ".docx": InputFormat.DOCX,
    ".doc": InputFormat.DOCX,
    ".dotx": InputFormat.DOCX,
    ".docm": InputFormat.DOCX,
    ".pptx": InputFormat.PPTX,
    ".ppt": InputFormat.PPTX,
    ".potx": InputFormat.PPTX,
    ".ppsx": InputFormat.PPTX,
    ".pptm": InputFormat.PPTX,
    ".xlsx": InputFormat.XLSX,
    ".xls": InputFormat.XLSX,
    ".xlsm": InputFormat.XLSX,
    ".html": InputFormat.HTML,
    ".htm": InputFormat.HTML,
    ".xhtml": InputFormat.HTML,
}


def _detect_format(path: Path) -> InputFormat | None:
    """확장자와 MIME으로 InputFormat을 결정한다."""
    ext = path.suffix.lower()
    if ext in EXTENSION_TO_FORMAT:
        return EXTENSION_TO_FORMAT[ext]
    kind = filetype.guess(str(path))
    if kind:
        mime = kind.mime
        if mime == "application/pdf":
            return InputFormat.PDF
        if mime in (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/msword",
        ):
            return InputFormat.DOCX
        if mime in (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.ms-powerpoint",
        ):
            return InputFormat.PPTX
        if mime in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel",
        ):
            return InputFormat.XLSX
        if mime == "text/html":
            return InputFormat.HTML
    return None


def _build_converter() -> DocumentConverter:
    """CPU + VNNI/OneDNN 최적화를 활용한 DocumentConverter를 생성한다."""
    pdf_options = PdfPipelineOptions()
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=DOCLING_NUM_THREADS,
        device=AcceleratorDevice.CPU,
    )
    pdf_options.do_ocr = False
    pdf_options.do_table_structure = True
    pdf_options.generate_picture_images = True
    pdf_options.generate_page_images = True
    pdf_options.layout_batch_size = DOCLING_LAYOUT_BATCH_SIZE
    pdf_options.table_batch_size = DOCLING_TABLE_BATCH_SIZE
    pdf_options.ocr_batch_size = DOCLING_OCR_BATCH_SIZE

    converter = DocumentConverter(
        allowed_formats=list(InputFormat),
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        },
    )
    _warmup_and_apply_ipex(converter)
    return converter


_IPEX_LOCK = threading.Lock()
_IPEX_WARMED = False


def _warmup_and_apply_ipex(converter: DocumentConverter) -> None:
    """빈 PDF로 파이프라인을 warm-up하고, 캐시된 모델에 IPEX INT8 최적화를 적용한다."""
    global _IPEX_WARMED
    with _IPEX_LOCK:
        if _IPEX_WARMED:
            return
        try:
            from pypdf import PdfWriter

            with tempfile.TemporaryDirectory() as tmpdir:
                pdf_path = Path(tmpdir) / "warmup.pdf"
                writer = PdfWriter()
                writer.add_blank_page(612, 792)
                with open(pdf_path, "wb") as f:
                    writer.write(f)
                try:
                    converter.convert(pdf_path)
                    logger.info("[docling-warmup] 파이프라인 warm-up 완료")
                except Exception as e:
                    logger.warning(f"[docling-warmup] warm-up 실패: {e}")
        except Exception as e:
            logger.warning(f"[docling-warmup] warm-up PDF 생성 실패: {e}")

        _apply_ipex(converter)
        _IPEX_WARMED = True


def _apply_ipex(converter: DocumentConverter) -> None:
    """캐시된 PDF 파이프라인 모델에 IPEX CPU 최적화를 시도한다."""
    try:
        import intel_extension_for_pytorch as ipex
        import torch
    except Exception as e:
        logger.info(f"[ipex] IPEX 초기화 실패, 최적화 생략: {e}")
        return

    for pipeline in converter.initialized_pipelines.values():
        if not hasattr(pipeline, "layout_model") and not hasattr(pipeline, "table_structure_model"):
            continue
        for attr in ("layout_model", "table_structure_model", "ocr_model"):
            model = getattr(pipeline, attr, None)
            if model is None:
                continue
            try:
                target = _unwrap_torch_module(model)
                if isinstance(target, torch.nn.Module):
                    optimized = ipex.optimize(target, dtype=torch.int8)
                    _assign_torch_module(model, optimized)
                    logger.info(f"[ipex] {attr} INT8 최적화 적용")
            except Exception as e:
                logger.warning(f"[ipex] {attr} 최적화 실패: {e}")


def _unwrap_torch_module(model: Any) -> Any:
    """Docling 모델 래퍼에서 실제 torch.nn.Module을 꺼낸다."""
    if hasattr(model, "model"):
        return model.model
    if hasattr(model, "predictor"):
        return model.predictor
    if hasattr(model, "_model"):
        return model._model
    return model


def _assign_torch_module(model: Any, target: Any) -> None:
    """최적화된 모듈을 원래 래퍼에 다시 할당한다."""
    if hasattr(model, "model"):
        model.model = target
    elif hasattr(model, "predictor"):
        model.predictor = target
    elif hasattr(model, "_model"):
        model._model = target


# 전역 싱글톤 (Docling 모델 로딩 비용이 크므로)
_converter: DocumentConverter | None = None


def get_converter() -> DocumentConverter:
    global _converter
    if _converter is None:
        _converter = _build_converter()
    return _converter


def _extract_images(result: ConversionResult, image_dir: Path) -> list[Path]:
    """DoclingDocument에서 이미지를 추출해 image_dir에 저장하고 저장된 경로 목록을 반환한다."""
    if not result or not result.document:
        return []

    doc = result.document
    image_dir.mkdir(parents=True, exist_ok=True)
    image_paths: list[Path] = []

    for idx, picture in enumerate(doc.pictures):
        try:
            img = picture.get_image(doc)
            if img is None:
                continue
            out_path = image_dir / f"image_{idx:04d}.png"
            img.save(out_path, "PNG")
            image_paths.append(out_path)
        except Exception as e:
            logger.warning(f"[docling-image] {idx} 추출 실패: {e}")
            continue

    return image_paths


def _count_pages(result: ConversionResult) -> int:
    """문서 유형별 페이지/슬라이드/시트 수를 추정한다."""
    if not result or not result.document:
        return 0
    doc = result.document
    try:
        if doc.pages:
            return len(doc.pages)
    except Exception:
        pass
    try:
        if hasattr(doc, "tables"):
            return len(doc.tables)
    except Exception:
        pass
    return 1


class ConvertResponse(BaseModel):
    markdown: str
    images: list[str]
    page_count: int
    file_type: str
    error: str | None = None


DATA_DIR = Path("/data")
IMAGE_BASE_DIR = DATA_DIR / "docling_images"


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/convert/file", response_model=ConvertResponse)
async def convert_file(file: UploadFile = File(...)) -> ConvertResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / (file.filename or "input.bin")
        input_path.write_bytes(await file.read())

        input_format = _detect_format(input_path)
        if input_format is None:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {file.filename}")

        converter = get_converter()
        try:
            result = converter.convert(input_path)
        except Exception as e:
            logger.exception(f"[docling-convert] {file.filename} 변환 실패: {e}")
            raise HTTPException(status_code=500, detail=f"Docling 변환 실패: {e}")

        if result.status in (ConversionStatus.FAILURE, ConversionStatus.PARTIAL_SUCCESS) and not result.document:
            raise HTTPException(status_code=500, detail="Docling 변환 결과가 없습니다")

        request_id = uuid.uuid4().hex
        image_dir = IMAGE_BASE_DIR / request_id
        image_paths = _extract_images(result, image_dir)
        relative_images = [str(p.relative_to(DATA_DIR)) for p in image_paths]

        try:
            markdown = result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)
        except Exception as e:
            logger.exception(f"[docling-markdown] {file.filename} 마크다운 추출 실패: {e}")
            raise HTTPException(status_code=500, detail=f"마크다운 추출 실패: {e}")

        return ConvertResponse(
            markdown=markdown,
            images=relative_images,
            page_count=_count_pages(result),
            file_type=input_format.value,
        )


@app.get("/images/{image_path:path}")
async def get_image(image_path: str) -> FileResponse:
    """추출된 이미지를 /data/docling_images 하위에서 반환한다."""
    base = DATA_DIR.resolve()
    target = (base / image_path).resolve()
    if not str(target).startswith(str(base)):
        raise HTTPException(status_code=400, detail="잘못된 이미지 경로")
    if not target.exists():
        raise HTTPException(status_code=404, detail="이미지를 찾을 수 없습니다")
    return FileResponse(str(target))


@app.exception_handler(Exception)
async def generic_exception_handler(_: Any, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception")
    return JSONResponse(status_code=500, content={"detail": f"내부 오류: {exc}"})
