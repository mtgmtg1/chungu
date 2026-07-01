#!/usr/bin/env python3
# [Flow: Step 1 (GPU 환경 출력) -> Step 2 (Docling GPU converter 생성) ->
#  Step 3 (PDF 변환 + 시간/VRAM 측정) -> Step 4 (결과 출력)]
"""GPU 벤치마크: Docling 기본 모델의 CUDA autocast FP16 성능 측정.

b2 GPU 서버 보수 후 재개를 위해 남겨둔 도구입니다.
"""

import argparse
import gc
import time
from pathlib import Path

import torch
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    EasyOcrOptions,
    PdfPipelineOptions,
)
from docling_core.types.doc import ImageRefMode


def build_converter():
    """GPU DocumentConverter를 생성한다."""
    from docling.document_converter import DocumentConverter, PdfFormatOption

    _original_autocast = torch.autocast

    def _patched_autocast(device_type, **kwargs):
        if device_type == "cuda":
            kwargs.setdefault("dtype", torch.float16)
        return _original_autocast(device_type, **kwargs)

    torch.autocast = _patched_autocast
    print("[autocast] torch.autocast를 CUDA float16으로 패치 완료")

    pdf_options = PdfPipelineOptions()
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=1,
        device=AcceleratorDevice.CUDA,
    )
    pdf_options.do_ocr = True
    pdf_options.do_table_structure = True
    pdf_options.generate_picture_images = True
    pdf_options.generate_page_images = True
    pdf_options.ocr_options = EasyOcrOptions()
    pdf_options.ocr_options.lang = ["ko", "en", "ja"]

    converter = DocumentConverter(
        allowed_formats=list(InputFormat),
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        },
    )
    _warmup(converter)
    return converter


def _warmup(converter):
    """빈 PDF로 파이프라인을 warm-up한다."""
    import tempfile

    from pypdf import PdfWriter

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "warmup.pdf"
        writer = PdfWriter()
        writer.add_blank_page(612, 792)
        with open(pdf_path, "wb") as f:
            writer.write(f)
        try:
            converter.convert(pdf_path)
            print("[warmup] 파이프라인 warm-up 완료")
        except Exception as e:
            print(f"[warmup] warm-up 실패: {e}")


def run_benchmark(pdf_path: Path) -> dict:
    """단일 PDF에 대해 GPU 벤치마크를 실행한다."""
    print(f"\n[benchmark] pdf={pdf_path.name}")

    torch.cuda.reset_peak_memory_stats()
    torch.cuda.empty_cache()

    converter = build_converter()
    vram_after_load = torch.cuda.max_memory_allocated() / 1024**3

    t0 = time.perf_counter()
    result = converter.convert(pdf_path)
    t_measured = time.perf_counter() - t0

    vram_peak = torch.cuda.max_memory_allocated() / 1024**3

    markdown = ""
    page_count = 0
    if result and result.document:
        try:
            markdown = result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)
            page_count = len(result.document.pages) if result.document.pages else 1
        except Exception:
            pass

    print(f"  measured: {t_measured:.2f}s")
    print(f"  VRAM: load={vram_after_load:.2f}GB, peak={vram_peak:.2f}GB")
    print(f"  pages: {page_count}, markdown length: {len(markdown)} chars")

    return {
        "measured_time": t_measured,
        "vram_after_load": vram_after_load,
        "vram_peak": vram_peak,
        "page_count": page_count,
        "markdown_len": len(markdown),
    }


def cleanup():
    """GPU 메모리를 정리한다."""
    gc.collect()
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description="GPU 벤치마크: Docling 기본 모델 CUDA FP16")
    parser.add_argument("--pdf", type=str, required=True, help="테스트할 PDF 파일 경로")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        print(f"파일을 찾을 수 없음: {pdf_path}")
        return

    print(f"GPU: {torch.cuda.get_device_name(0)}")
    print(f"VRAM total: {torch.cuda.get_device_properties(0).total_memory / 1024**3:.1f}GB")
    print(f"CUDA: {torch.version.cuda}")
    print(f"PyTorch: {torch.__version__}")

    result = run_benchmark(pdf_path)
    cleanup()

    print(f"\n[result] {result}")


if __name__ == "__main__":
    main()
