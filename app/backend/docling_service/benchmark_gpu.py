#!/usr/bin/env python3
"""GPU 벤치마크: Config A (autocast-only) vs Config B (SuryaModel .half())

[Flow: Step 1 (샘플 PDF 로드) -> Step 2 (Config A: autocast-only 변환 + 시간 측정) ->
 Step 3 (Config B: SuryaModel .half() 변환 + 시간 측정) -> Step 4 (VRAM 사용량 비교) ->
 Step 5 (인식 품질 비교) -> Step 6 (결과 표 출력)]
"""
import argparse
import gc
import time
from pathlib import Path
from types import SimpleNamespace

import torch
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import ConversionStatus, InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
)
from docling_core.types.doc import ImageRefMode
from docling_surya import SuryaOcrOptions


def build_converter(half_surya: bool) -> DocumentConverter:
    """GPU DocumentConverter를 생성한다. half_surya=True면 SuryaModel을 .half()로 변환한다."""
    pdf_options = PdfPipelineOptions()
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=1,
        device=AcceleratorDevice.CUDA,
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
    _warmup(converter)
    if half_surya:
        _apply_half_to_surya(converter)
    return converter


def _warmup(converter: DocumentConverter) -> None:
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


def _find_all_nn_modules(obj, _depth=0):
    """객체 내에서 모든 torch.nn.Module을 (parent, attr_name, module) 튜플로 반환한다."""
    if _depth > 5:
        return []
    results = []
    if isinstance(obj, torch.nn.Module):
        results.append((None, None, obj))
        return results
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
    if hasattr(obj, "layout_predictor"):
        lp = obj.layout_predictor
        if hasattr(lp, "_model") and isinstance(lp._model, torch.nn.Module):
            results.append((lp, "_model", lp._model))
    if hasattr(obj, "tf_predictor"):
        tfp = obj.tf_predictor
        if hasattr(tfp, "_model") and isinstance(tfp._model, torch.nn.Module):
            results.append((tfp, "_model", tfp._model))
    for attr in ("model", "_model"):
        child = getattr(obj, attr, None)
        if isinstance(child, torch.nn.Module) and not any(t[2] is child for t in results):
            results.append((obj, attr, child))
    return results


def _apply_half_to_surya(converter: DocumentConverter) -> None:
    """SuryaModel(recognition)만 .half()로 변환하여 VRAM을 절감하고 Tensor Core를 직접 활용한다."""
    for pipeline in converter.initialized_pipelines.values():
        if not hasattr(pipeline, "layout_model") and not hasattr(pipeline, "table_model"):
            continue
        for attr in ("layout_model", "table_model", "ocr_model"):
            model = getattr(pipeline, attr, None)
            if model is None:
                continue
            targets = _find_all_nn_modules(model)
            for parent, attr_name, nn_module in targets:
                model_type = type(nn_module).__name__
                if "SuryaModel" in model_type:
                    try:
                        nn_module.half()
                        nn_module.cuda()
                        print(f"[half] {model_type} .half() 변환 완료")
                    except Exception as e:
                        print(f"[half] {model_type} .half() 실패: {e}")


def run_benchmark(pdf_path: Path, half_surya: bool, label: str) -> dict:
    """단일 PDF에 대해 벤치마크를 실행하고 결과를 반환한다."""
    print(f"\n{'='*60}")
    print(f"[{label}] half_surya={half_surya}, pdf={pdf_path.name}")
    print(f"{'='*60}")

    torch.cuda.reset_peak_memory_settings()
    torch.cuda.empty_cache()

    converter = build_converter(half_surya=half_surya)

    vram_after_load = torch.cuda.max_memory_allocated() / 1024**3

    # warm-up 변환 (1회차)
    t0 = time.perf_counter()
    result_warmup = converter.convert(pdf_path)
    t_warmup = time.perf_counter() - t0

    # 실측 변환 (2회차)
    torch.cuda.reset_peak_memory_settings()
    t0 = time.perf_counter()
    result = converter.convert(pdf_path)
    t_measured = time.perf_counter() - t0

    vram_peak = torch.cuda.max_memory_allocated() / 1024**3

    markdown = ""
    if result and result.document:
        try:
            markdown = result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)
        except Exception:
            markdown = ""

    page_count = 0
    if result and result.document:
        try:
            page_count = len(result.document.pages) if result.document.pages else 1
        except Exception:
            page_count = 1

    print(f"  warm-up: {t_warmup:.2f}s, measured: {t_measured:.2f}s")
    print(f"  VRAM: load={vram_after_load:.2f}GB, peak={vram_peak:.2f}GB")
    print(f"  pages: {page_count}, markdown length: {len(markdown)} chars")

    return {
        "label": label,
        "half_surya": half_surya,
        "warmup_time": t_warmup,
        "measured_time": t_measured,
        "vram_after_load": vram_after_load,
        "vram_peak": vram_peak,
        "page_count": page_count,
        "markdown": markdown,
        "markdown_len": len(markdown),
    }


def cleanup():
    """GPU 메모리를 정리한다."""
    gc.collect()
    torch.cuda.empty_cache()


def main():
    parser = argparse.ArgumentParser(description="GPU 벤치마크: autocast-only vs SuryaModel .half()")
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

    # Config A: autocast-only (모든 모델 FP32, 추론 시 autocast float16)
    result_a = run_benchmark(pdf_path, half_surya=False, label="A: autocast-only")
    cleanup()

    # Config B: SuryaModel .half() + 나머지 autocast
    result_b = run_benchmark(pdf_path, half_surya=True, label="B: SuryaModel .half()")
    cleanup()

    # 결과 비교 표
    print(f"\n{'='*60}")
    print("벤치마크 결과 비교")
    print(f"{'='*60}")
    print(f"{'항목':<25} {'A: autocast-only':>20} {'B: SuryaModel .half()':>20} {'차이':>10}")
    print(f"{'-'*75}")
    print(f"{'warm-up 시간 (s)':<25} {result_a['warmup_time']:>20.2f} {result_b['warmup_time']:>20.2f} {result_b['warmup_time'] - result_a['warmup_time']:>+10.2f}")
    print(f"{'측정 시간 (s)':<25} {result_a['measured_time']:>20.2f} {result_b['measured_time']:>20.2f} {result_b['measured_time'] - result_a['measured_time']:>+10.2f}")
    print(f"{'VRAM after load (GB)':<25} {result_a['vram_after_load']:>20.2f} {result_b['vram_after_load']:>20.2f} {result_b['vram_after_load'] - result_a['vram_after_load']:>+10.2f}")
    print(f"{'VRAM peak (GB)':<25} {result_a['vram_peak']:>20.2f} {result_b['vram_peak']:>20.2f} {result_b['vram_peak'] - result_a['vram_peak']:>+10.2f}")
    print(f"{'페이지 수':<25} {result_a['page_count']:>20} {result_b['page_count']:>20}")
    print(f"{'마크다운 길이':<25} {result_a['markdown_len']:>20} {result_b['markdown_len']:>20} {result_b['markdown_len'] - result_a['markdown_len']:>+10}")

    # 품질 비교: 마크다운이 동일한지
    if result_a["markdown"] == result_b["markdown"]:
        print(f"\n품질: 동일 (마크다운 100% 일치)")
    else:
        a_lines = result_a["markdown"].splitlines()
        b_lines = result_b["markdown"].splitlines()
        print(f"\n품질: 차이 발생 (A: {len(a_lines)}줄, B: {len(b_lines)}줄)")
        diff_count = sum(1 for a, b in zip(a_lines, b_lines) if a != b)
        print(f"  차이 라인 수: {diff_count}")
        for i, (a, b) in enumerate(zip(a_lines, b_lines)):
            if a != b:
                print(f"  line {i+1}:")
                print(f"    A: {a[:100]}")
                print(f"    B: {b[:100]}")
                if diff_count > 5:
                    print(f"  ... (총 {diff_count}줄 차이, 처음 5줄만 표시)")
                    break


if __name__ == "__main__":
    main()
