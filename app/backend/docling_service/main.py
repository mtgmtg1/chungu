#!/usr/bin/env python3
# [Flow: Step 1 (FastAPI 초기화) -> Step 2 (파일 업로드) -> Step 3 (Docling CPU/VNNI 변환) -> Step 4 (마크다운 + 이미지 추출) -> Step 5 (JSON 반환)]
import logging
import os
import tempfile
import threading
import uuid
from pathlib import Path
from types import SimpleNamespace
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

from docling_surya import SuryaOcrOptions


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

app = FastAPI(title="Chungu Docling Preprocessing Service")

# 1요청당 2스레드, 총 40스레드 = 20 동시성 허용
DOCLING_NUM_THREADS = int(os.environ.get("DOCLING_NUM_THREADS", "40"))

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
    pdf_options.do_ocr = True
    pdf_options.allow_external_plugins = True
    pdf_options.ocr_options = SuryaOcrOptions()
    pdf_options.ocr_options.lang = ["ko", "en", "ja"]
    pdf_options.do_table_structure = True
    pdf_options.generate_picture_images = True
    pdf_options.generate_page_images = True

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
    """캐시된 PDF 파이프라인 모델에 IPEX INT8 동적 양자화 + CPU 최적화를 적용한다."""
    try:
        import intel_extension_for_pytorch as ipex
        import torch
    except Exception as e:
        logger.info(f"[ipex] IPEX 초기화 실패, 최적화 생략: {e}")
        return

    # CPU에서 bfloat16 에뮬레이션은 매우 느리므로 autocast를 float32로 패치
    _original_autocast = torch.autocast

    def _patched_autocast(device_type, **kwargs):
        if device_type == "cpu":
            kwargs["dtype"] = torch.float32
        return _original_autocast(device_type, **kwargs)

    torch.autocast = _patched_autocast
    logger.info("[ipex] torch.autocast를 CPU float32로 패치 완료")

    # 1요청당 2스레드: 각 추론은 2코어 사용, 총 40스레드 = 20 동시성 허용
    torch.set_num_threads(2)
    logger.info("[ipex] torch.set_num_threads(2) 적용 (1요청당 2스레드)")

    for pipeline in converter.initialized_pipelines.values():
        if not hasattr(pipeline, "layout_model") and not hasattr(pipeline, "table_model"):
            continue
        for attr in ("layout_model", "table_model", "ocr_model"):
            model = getattr(pipeline, attr, None)
            if model is None:
                continue
            _quantize_model_recursive(model, attr, ipex, torch)


def _quantize_model_recursive(model: Any, label: str, ipex, torch) -> None:
    """모델 래퍼 내의 모든 torch.nn.Module을 찾아 최적화한다.
    - SuryaModel (recognition): torch.quantize_dynamic (Linear INT8) — 글자 인식 문제 없음, 속도 유지
    - RTDetrV2 (layout): FP32 유지 — 레이아웃 인식 품질 복구
    - EfficientViT (detection): FP32 유지 — bbox 검출 품질 복구
    - TableModel04_rs (table structure): FP32 유지 — 표 구조 인식 품질 복구
    """
    targets = _find_all_nn_modules(model)
    if not targets:
        logger.warning(f"[ipex] {label}: torch.nn.Module을 찾지 못함")
        return

    logger.info(f"[ipex] {label}: {len(targets)}개 모델 발견")
    for parent, attr_name, nn_module in targets:
        sub_label = f"{label}.{attr_name}"
        try:
            nn_module.eval()
            model_type = type(nn_module).__name__

            # SuryaModel (recognition): torch.quantize_dynamic (Linear INT8) — 유지
            if "SuryaModel" in model_type:
                try:
                    quantized = torch.quantization.quantize_dynamic(
                        nn_module, {torch.nn.Linear}, dtype=torch.qint8
                    )
                    setattr(parent, attr_name, quantized)
                    logger.info(f"[ipex] {sub_label} ({model_type}) Linear INT8 동적 양자화 적용")
                except Exception as qe:
                    logger.warning(f"[ipex] {sub_label} ({model_type}) 양자화 실패, 원본 유지: {qe}")

            # 나머지 모델: FP32 원본 유지 (레이아웃/표 구조 품질 복구)
            else:
                logger.info(f"[ipex] {sub_label} ({model_type}) FP32 유지 (레이아웃 품질 복구)")
        except Exception as e:
            logger.warning(f"[ipex] {sub_label} 최적화 실패: {e}")


_OV_CACHE_DIR = Path("/data/ov_cache")


def _convert_to_openvino(
    nn_module: Any,
    model_type: str,
    output_kind: str,
    parent_wrapper: Any,
) -> Any:
    """PyTorch 모델을 OpenVINO INT8로 변환하여 래퍼를 반환한다.

    [Flow: Step 1 (입력 크기 추출) -> Step 2 (Export wrapper 생성) -> Step 3 (캐시 확인) ->
     Step 4 (OpenVINO 변환 + NNCF 양자화 or 캐시 로드) -> Step 5 (CPU 컴파일) -> Step 6 (래퍼 반환)]
    """
    import openvino as ov
    import torch

    # Step 1: 입력 크기 추출
    if output_kind == "detection":
        predictor = getattr(parent_wrapper, "detection_predictor", None)
        if predictor is None or not hasattr(predictor, "processor"):
            return None
        size = predictor.processor.size
        h, w = size["height"], size["width"]
    else:
        predictor = getattr(parent_wrapper, "layout_predictor", None)
        if predictor is None or not hasattr(predictor, "_image_processor"):
            return None
        size = predictor._image_processor.size
        h, w = size["height"], size["width"]

    # Step 2: Export wrapper 생성 (출력을 tensor tuple로 단순화)
    if output_kind == "detection":
        class _DetWrapper(torch.nn.Module):
            def __init__(self, m):
                super().__init__()
                self.m = m
            def forward(self, pixel_values):
                return self.m(pixel_values=pixel_values).logits
        export_wrapper = _DetWrapper(nn_module)
        example_input = torch.randn(1, 3, h, w)
        ov_input = {"pixel_values": (1, 3, h, w)}
    else:
        class _LayoutWrapper(torch.nn.Module):
            def __init__(self, m):
                super().__init__()
                self.m = m
            def forward(self, pixel_values, pixel_mask):
                out = self.m(pixel_values=pixel_values, pixel_mask=pixel_mask)
                return out.logits, out.pred_boxes
        export_wrapper = _LayoutWrapper(nn_module)
        example_input = (torch.randn(1, 3, h, w), torch.ones(1, h, w, dtype=torch.long))
        ov_input = {"pixel_values": (1, 3, h, w), "pixel_mask": (1, h, w)}

    # Step 3: 캐시 확인
    _OV_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_key = f"{model_type}_{h}x{w}"
    xml_path = _OV_CACHE_DIR / f"{cache_key}.xml"
    bin_path = _OV_CACHE_DIR / f"{cache_key}.bin"

    if xml_path.exists() and bin_path.exists():
        # Step 4a: 캐시 로드
        core = ov.Core()
        ov_model = core.read_model(str(xml_path), str(bin_path))
        logger.info(f"[ov] {model_type} 캐시에서 로드: {xml_path}")
    else:
        # Step 4b: OpenVINO 변환 + NNCF INT8 양자화
        logger.info(f"[ov] {model_type} 변환 시작 (input={ov_input})...")
        with torch.inference_mode():
            if output_kind == "detection":
                ov_model = ov.convert_model(export_wrapper, input=ov_input)
            else:
                traced = torch.jit.trace(export_wrapper, example_input, strict=False)
                ov_model = ov.convert_model(traced, example_input=example_input)
        # NNCF INT8 양자화 (Fast Bias Correction)
        import nncf
        calib_data = []
        for _ in range(8):
            if output_kind == "detection":
                calib_data.append({"pixel_values": torch.randn(1, 3, h, w)})
            else:
                calib_data.append({
                    "pixel_values": torch.randn(1, 3, h, w),
                    "pixel_mask": torch.ones(1, h, w, dtype=torch.long),
                })
        quantized_dataset = nncf.Dataset(calib_data)
        ov_model = nncf.quantize(ov_model, quantized_dataset)
        ov.save_model(ov_model, str(xml_path))
        logger.info(f"[ov] {model_type} OpenVINO NNCF INT8 양자화 완료, 캐시 저장: {xml_path}")

    # Step 5: CPU 컴파일 (1요청당 2스레드, 총 40스레드 = 20 동시성 허용)
    core = ov.Core()
    compiled = core.compile_model(
        ov_model, "CPU",
        {"INFERENCE_NUM_THREADS": "2"},
    )

    # Step 6: 래퍼 반환
    return _OpenVINOModelWrapper(nn_module, compiled, output_kind)


class _OpenVINOModelWrapper:
    """OpenVINO 컴파일된 모델을 PyTorch 모델 인터페이스로 래핑한다.

    - 원본 모델의 속성(config, dtype, device 등)을 그대로 노출
    - __call__ 시 OpenVINO 추론 후 torch tensor로 변환하여 반환
    """

    def __init__(self, original_model: Any, compiled_model: Any, output_kind: str):
        self._original = original_model
        self._compiled = compiled_model
        self._output_kind = output_kind

    @property
    def config(self):
        return self._original.config

    @property
    def dtype(self):
        import torch
        return torch.float32

    @property
    def device(self):
        import torch
        return torch.device("cpu")

    def eval(self):
        pass

    def __call__(self, pixel_values=None, **kwargs):
        import numpy as np
        import torch

        # 입력 준비: torch tensor → numpy
        inputs = {}
        if pixel_values is not None:
            if isinstance(pixel_values, torch.Tensor):
                inputs["pixel_values"] = pixel_values.detach().cpu().numpy()
            else:
                inputs["pixel_values"] = np.asarray(pixel_values, dtype=np.float32)

        if "pixel_mask" in kwargs and kwargs["pixel_mask"] is not None:
            pm = kwargs["pixel_mask"]
            if isinstance(pm, torch.Tensor):
                inputs["pixel_mask"] = pm.detach().cpu().numpy()
            else:
                inputs["pixel_mask"] = np.asarray(pm, dtype=np.int64)

        # OpenVINO 입력 이름 매핑
        input_names = [inp.get_any_name() for inp in self._compiled.inputs]
        if len(input_names) == len(inputs):
            # 이름이 다를 수 있으므로 순서대로 매핑
            sorted_keys = list(inputs.keys())
            ov_inputs = {input_names[i]: inputs[sorted_keys[i]] for i in range(len(input_names))}
        else:
            ov_inputs = inputs

        # OpenVINO 추론
        results = self._compiled(ov_inputs)
        output_values = list(results.values())

        # 출력을 torch tensor로 변환
        if self._output_kind == "detection":
            logits = torch.from_numpy(np.array(output_values[0]))
            return SimpleNamespace(loss=None, logits=logits, hidden_states=None)
        else:
            logits = torch.from_numpy(np.array(output_values[0]))
            pred_boxes = torch.from_numpy(np.array(output_values[1]))
            return SimpleNamespace(
                loss=None, logits=logits, pred_boxes=pred_boxes,
                hidden_states=None, attentions=None,
            )


def _find_all_nn_modules(obj: Any, _depth: int = 0) -> list[tuple[Any, str, Any]]:
    """객체 내에서 모든 torch.nn.Module을 (parent, attr_name, module) 튜플로 반환한다."""
    import torch
    if _depth > 5:
        return []

    results = []
    # 직접 nn.Module인 경우
    if isinstance(obj, torch.nn.Module):
        results.append((None, None, obj))
        return results

    # SuryaOcrModel: recognition_predictor.foundation_predictor.model + detection_predictor.model
    if hasattr(obj, "recognition_predictor"):
        rp = obj.recognition_predictor
        if hasattr(rp, "foundation_predictor"):
            fp = rp.foundation_predictor
            if hasattr(fp, "model") and isinstance(fp.model, torch.nn.Module):
                results.append((fp, "model", fp.model))
    if hasattr(obj, "detection_predictor"):
        dp = obj.detection_predictor
        if hasattr(dp, "model") and isinstance(dp.model, torch.nn.Module):
            results.append((dp, "model", dp.model))

    # LayoutModel: layout_predictor._model
    if hasattr(obj, "layout_predictor"):
        lp = obj.layout_predictor
        if hasattr(lp, "_model") and isinstance(lp._model, torch.nn.Module):
            results.append((lp, "_model", lp._model))

    # TableStructureModel: tf_predictor._model (TableModel04_rs)
    if hasattr(obj, "tf_predictor"):
        tfp = obj.tf_predictor
        if hasattr(tfp, "_model") and isinstance(tfp._model, torch.nn.Module):
            results.append((tfp, "_model", tfp._model))

    # 일반 래퍼: .model, ._model
    for attr in ("model", "_model"):
        child = getattr(obj, attr, None)
        if isinstance(child, torch.nn.Module) and not any(t[2] is child for t in results):
            results.append((obj, attr, child))

    return results




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


class AsyncConvertResponse(BaseModel):
    task_id: str
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str  # processing | done | error
    result: ConvertResponse | None = None
    error: str | None = None
    started_at: float | None = None
    finished_at: float | None = None


DATA_DIR = Path("/data")
IMAGE_BASE_DIR = DATA_DIR / "docling_images"

# 비동기 변환 task store (메모리 내)
_tasks: dict[str, dict] = {}
_tasks_lock = threading.Lock()


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


def _do_convert(task_id: str, input_path: Path, filename: str) -> None:
    """백그라운드 스레드에서 Docling 변환을 수행한다."""
    import time

    try:
        converter = get_converter()
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
async def convert_async(file: UploadFile = File(...)) -> AsyncConvertResponse:
    """파일을 비동기로 변환 시작, task_id를 즉시 반환한다."""
    import time

    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 없습니다")

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

    thread = threading.Thread(target=_do_convert, args=(task_id, input_path, file.filename), daemon=True)
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
