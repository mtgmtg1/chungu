#!/usr/bin/env python3
# [Flow: Step 1 (FastAPI 초기화) -> Step 2 (파일 업로드 + ocr_engine 파라미터) -> Step 3 (Docling 변환) -> Step 4 (마크다운 + 이미지 추출) -> Step 5 (JSON 반환)]
import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

import filetype
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.document import ConversionResult
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    EasyOcrOptions,
    PdfPipelineOptions,
    RapidOcrOptions,
    TesseractCliOcrOptions,
)
from docling_core.types.doc import ImageRefMode


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Chungu Docling Preprocessing Service")

DOCLING_NUM_THREADS = int(os.environ.get("DOCLING_NUM_THREADS", "2"))
DOCLING_DEVICE = os.environ.get("DOCLING_DEVICE", "cpu").lower()
DEFAULT_OCR_ENGINE = os.environ.get("OCR_ENGINE", "tesseract").lower()
OCR_LANG = os.environ.get("OCR_LANG", "ko+en+ja")

# 문서당 2스레드만 사용, 80코어에서 최대 40개 문서 동시 처리
try:
    import torch
    torch.set_num_threads(DOCLING_NUM_THREADS)
except ImportError:
    pass

VALID_OCR_ENGINES = ("tesseract", "easyocr", "rapidocr")

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
    ".png": InputFormat.IMAGE,
    ".jpg": InputFormat.IMAGE,
    ".jpeg": InputFormat.IMAGE,
    ".webp": InputFormat.IMAGE,
    ".bmp": InputFormat.IMAGE,
    ".tiff": InputFormat.IMAGE,
    ".tif": InputFormat.IMAGE,
}


def _detect_format(path: Path) -> InputFormat | None:
    """확장자와 MIME으로 InputFormat을 결정한다."""
    ext = path.suffix.lower()
    if ext in EXTENSION_TO_FORMAT:
        return EXTENSION_TO_FORMAT[ext]
    kind = filetype.guess(str(path))
    if not kind:
        return None
    mime = kind.mime
    if mime == "application/pdf":
        return InputFormat.PDF
    if mime.startswith("image/"):
        return InputFormat.IMAGE
    if "wordprocessing" in mime or mime == "application/msword":
        return InputFormat.DOCX
    if "presentation" in mime or mime == "application/vnd.ms-powerpoint":
        return InputFormat.PPTX
    if "spreadsheet" in mime or mime == "application/vnd.ms-excel":
        return InputFormat.XLSX
    if mime == "text/html":
        return InputFormat.HTML
    return None


def _build_ocr_options(ocr_engine: str) -> Any:
    """OCR 엔진 이름에 따라 Docling OCR 옵션 객체를 반환한다."""
    if ocr_engine == "easyocr":
        return EasyOcrOptions(lang=["ko", "en"], use_gpu=False)

    if ocr_engine == "rapidocr":
        # [Flow: RapidOCR v3 한국어 PP-OCRv5 모델 사용 - Docling 기본 Chinese 폴백 우회]
        # Docling은 ko → chinese 폴백하므로, rapidocr_params로 한국어 Enum을 직접 주입
        # PP-OCRv5 korean은 model_type=mobile만 지원 (small 미지원)
        try:
            from rapidocr.utils.typings import LangRec, ModelType, OCRVersion
            return RapidOcrOptions(
                lang=["ko"],
                rapidocr_params={
                    "Det.model_path": None,
                    "Rec.model_path": None,
                    "Rec.rec_keys_path": None,
                    "Rec.lang_type": LangRec.KOREAN,
                    "Rec.ocr_version": OCRVersion.PPOCRV5,
                    "Rec.model_type": ModelType.MOBILE,
                },
            )
        except ImportError:
            return RapidOcrOptions(lang=["ko"])

    # tesseract CLI (tesserocr 패키지 불필요, 시스템 Tesseract 사용)
    # [Flow: kor+eng만 사용 (jpn은 한국어 인식 간섭) -> tessdata 경로 명시 -> PSM 6 (uniform block)로 안정성 향상]
    return TesseractCliOcrOptions(
        lang=["kor", "eng"],
        path="/usr/share/tesseract-ocr/5/tessdata",
        psm=6,
    )


def _build_converter(ocr_engine: str) -> DocumentConverter:
    """OCR 엔진에 따라 DocumentConverter를 생성한다."""
    is_gpu = DOCLING_DEVICE == "cuda"
    pdf_options = PdfPipelineOptions()
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=1 if is_gpu else DOCLING_NUM_THREADS,
        device=AcceleratorDevice.CUDA if is_gpu else AcceleratorDevice.CPU,
    )
    pdf_options.do_ocr = True
    pdf_options.do_table_structure = True
    pdf_options.generate_picture_images = True
    pdf_options.generate_page_images = True
    pdf_options.ocr_options = _build_ocr_options(ocr_engine)

    logger.info(f"[docling] OCR 엔진: {ocr_engine}, device: {DOCLING_DEVICE}")

    return DocumentConverter(
        allowed_formats=list(InputFormat),
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pdf_options,
                backend=PyPdfiumDocumentBackend,
            ),
            InputFormat.IMAGE: PdfFormatOption(
                pipeline_options=pdf_options,
                backend=PyPdfiumDocumentBackend,
            ),
        },
    )


_converters: dict[str, DocumentConverter] = {}
_converters_lock = threading.Lock()


def get_converter(ocr_engine: str = DEFAULT_OCR_ENGINE) -> DocumentConverter:
    """OCR 엔진별 싱글톤 DocumentConverter를 반환한다."""
    if ocr_engine not in VALID_OCR_ENGINES:
        ocr_engine = DEFAULT_OCR_ENGINE
    with _converters_lock:
        if ocr_engine not in _converters:
            _converters[ocr_engine] = _build_converter(ocr_engine)
        return _converters[ocr_engine]


def _extract_images(result: ConversionResult, image_dir: Path) -> list[Path]:
    """DoclingDocument에서 이미지를 추출해 image_dir에 저장한다."""
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
    return image_paths


def _count_pages(result: ConversionResult) -> int:
    """문서 페이지/슬라이드/시트 수를 반환한다."""
    if not result or not result.document:
        return 0
    doc = result.document
    try:
        if doc.pages:
            return len(doc.pages)
    except Exception:
        pass
    return 1


class ConvertResponse(BaseModel):
    markdown: str
    images: list[str]
    page_count: int
    file_type: str
    error: str | None = None


class AsyncConvertResponse(BaseModel):
    task_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str
    result: ConvertResponse | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


DATA_DIR = Path("/data")
IMAGE_BASE_DIR = DATA_DIR / "docling_images"

_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _do_convert(task_id: str, input_path: Path, filename: str, ocr_engine: str) -> None:
    """백그라운드 스레드에서 Docling 변환을 수행한다."""
    import time

    try:
        converter = get_converter(ocr_engine)
        result = converter.convert(input_path)

        if result.status in (ConversionStatus.FAILURE, ConversionStatus.PARTIAL_SUCCESS) and not result.document:
            with _tasks_lock:
                _tasks[task_id]["status"] = "error"
                _tasks[task_id]["error"] = "Docling 변환 결과가 없습니다"
                _tasks[task_id]["finished_at"] = time.time()
            return

        request_id = uuid.uuid4().hex
        image_dir = IMAGE_BASE_DIR / request_id
        image_paths = _extract_images(result, image_dir)
        relative_images = [str(p.relative_to(DATA_DIR)) for p in image_paths]

        markdown = result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)

        convert_result = ConvertResponse(
            markdown=markdown,
            images=relative_images,
            page_count=_count_pages(result),
            file_type=fmt.value if (fmt := _detect_format(input_path)) else "unknown",
        )

        with _tasks_lock:
            _tasks[task_id]["status"] = "done"
            _tasks[task_id]["result"] = convert_result
            _tasks[task_id]["finished_at"] = time.time()

    except Exception as e:
        logger.exception(f"[docling-async] {filename} 변환 실패: {e}")
        with _tasks_lock:
            _tasks[task_id]["status"] = "error"
            _tasks[task_id]["error"] = str(e)
            _tasks[task_id]["finished_at"] = time.time()


@app.post("/convert/async", response_model=AsyncConvertResponse)
async def convert_async(
    file: UploadFile = File(...),
    ocr_engine: str = Form(DEFAULT_OCR_ENGINE),
) -> AsyncConvertResponse:
    """파일을 비동기로 변환 시작, task_id를 즉시 반환한다."""
    import time

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

    if ocr_engine not in VALID_OCR_ENGINES:
        ocr_engine = DEFAULT_OCR_ENGINE

    task_id = uuid.uuid4().hex
    tmpdir = tempfile.mkdtemp()
    tmp_path = Path(tmpdir)
    input_path = tmp_path / (file.filename or "input.bin")
    input_path.write_bytes(await file.read())

    input_format = _detect_format(input_path)
    if input_format is None:
        raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {file.filename}")

    with _tasks_lock:
        _tasks[task_id] = {
            "status": "processing",
            "result": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
            "tmpdir": tmpdir,
        }

    thread = threading.Thread(
        target=_do_convert,
        args=(task_id, input_path, file.filename, ocr_engine),
        daemon=True,
    )
    thread.start()

    return AsyncConvertResponse(task_id=task_id, status="processing")


@app.get("/convert/status/{task_id}", response_model=TaskStatusResponse)
async def get_convert_status(task_id: str) -> TaskStatusResponse:
    """비동기 변환 task의 진행 상태를 반환한다."""
    with _tasks_lock:
        task = _tasks.get(task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task를 찾을 수 없습니다")
    return TaskStatusResponse(
        task_id=task_id,
        status=task["status"],
        result=task.get("result"),
        error=task.get("error"),
        started_at=task.get("started_at"),
        finished_at=task.get("finished_at"),
    )


@app.post("/convert/file", response_model=ConvertResponse)
async def convert_file(
    file: UploadFile = File(...),
    ocr_engine: str = Form(DEFAULT_OCR_ENGINE),
) -> ConvertResponse:
    """파일을 동기로 변환한다."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

    if ocr_engine not in VALID_OCR_ENGINES:
        ocr_engine = DEFAULT_OCR_ENGINE

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        input_path = tmp_path / (file.filename or "input.bin")
        input_path.write_bytes(await file.read())

        input_format = _detect_format(input_path)
        if input_format is None:
            raise HTTPException(status_code=400, detail=f"지원하지 않는 파일 형식입니다: {file.filename}")

        converter = get_converter(ocr_engine)
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
