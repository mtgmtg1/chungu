#!/usr/bin/env python3
# [Flow: Step 1 (샘플 파일 로드) -> Step 2 (EasyOCR 변환 + 시간 측정) ->
#  Step 3 (Tesseract 변환 + 시간 측정) -> Step 4 (결과 비교) -> Step 5 (JSON 보고서 출력)]
"""Docling 내부 OCR 엔진(EasyOCR vs Tesseract)을 A/B 비교하는 벤치마크 도구."""

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    EasyOcrOptions,
    PdfPipelineOptions,
    TesseractOcrOptions,
)


def _build_converter(ocr_engine: str, num_threads: int = 40) -> Any:
    """지정한 OCR 엔진으로 DocumentConverter를 생성한다."""
    from docling.document_converter import DocumentConverter, PdfFormatOption
    from docling.datamodel.base_models import InputFormat

    pdf_options = PdfPipelineOptions()
    pdf_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads,
        device=AcceleratorDevice.CPU,
    )
    pdf_options.do_ocr = True
    pdf_options.do_table_structure = True
    pdf_options.generate_picture_images = True
    pdf_options.generate_page_images = True

    if ocr_engine == "tesseract":
        pdf_options.ocr_options = TesseractOcrOptions()
        pdf_options.ocr_options.lang = ["kor", "eng", "jpn"]
    else:
        pdf_options.ocr_options = EasyOcrOptions()
        pdf_options.ocr_options.lang = ["ko", "en", "ja"]

    return DocumentConverter(
        allowed_formats=list(InputFormat),
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf_options),
        },
    )


def _convert_file(converter: Any, file_path: Path) -> tuple[str, int, float]:
    """단일 파일을 변환하고 (markdown, char_count, elapsed_seconds)를 반환한다."""
    start = time.perf_counter()
    result = converter.convert(file_path)
    elapsed = time.perf_counter() - start

    if result.document is None:
        raise RuntimeError(f"변환 실패: {file_path}")

    from docling_core.types.doc import ImageRefMode
    markdown = result.document.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER)
    return markdown, len(markdown), elapsed


def _benchmark_file(file_path: Path, engines: list[str], num_threads: int) -> dict[str, Any]:
    """하나의 파일에 대해 주어진 OCR 엔진들을 각각 실행하고 결과를 반환한다."""
    print(f"\n[file] {file_path.name}")
    file_result: dict[str, Any] = {
        "file": str(file_path),
        "engines": {},
    }

    for engine in engines:
        print(f"  [{engine}] 변환 시작...")
        converter = _build_converter(engine, num_threads)
        try:
            markdown, char_count, elapsed = _convert_file(converter, file_path)
            file_result["engines"][engine] = {
                "elapsed_seconds": round(elapsed, 3),
                "char_count": char_count,
                "markdown_sample": markdown[:500],
            }
            print(f"  [{engine}] {elapsed:.2f}s, {char_count} chars")
        except Exception as e:
            file_result["engines"][engine] = {"error": str(e)}
            print(f"  [{engine}] ERROR: {e}")

    return file_result


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Docling OCR engines (EasyOCR vs Tesseract)")
    parser.add_argument("input", type=Path, help="Directory or single file to benchmark")
    parser.add_argument(
        "--engines",
        type=str,
        default="easyocr,tesseract",
        help="Comma-separated OCR engines to compare",
    )
    parser.add_argument("--threads", type=int, default=40, help="Docling CPU threads")
    parser.add_argument("--output", type=Path, default=None, help="JSON report output path")
    args = parser.parse_args()

    engines = [e.strip() for e in args.engines.split(",") if e.strip()]
    if not engines:
        raise ValueError("At least one engine is required")

    # Docling 모델 캐시가 공유되지 않도록 분리하여 각 엔진별 초기화 비용 포함
    input_path: Path = args.input
    if input_path.is_file():
        files = [input_path]
    elif input_path.is_dir():
        files = sorted(
            p for p in input_path.iterdir()
            if p.suffix.lower() in (".pdf", ".docx", ".pptx", ".xlsx", ".html", ".htm")
        )
    else:
        raise FileNotFoundError(f"Input not found: {input_path}")

    if not files:
        raise FileNotFoundError(f"No benchmark files found in {input_path}")

    report = {
        "engines": engines,
        "num_threads": args.threads,
        "files": [],
    }

    for file_path in files:
        report["files"].append(_benchmark_file(file_path, engines, args.threads))

    # Aggregate summary
    summary: dict[str, dict[str, Any]] = {}
    for engine in engines:
        times = [
            f["engines"][engine]["elapsed_seconds"]
            for f in report["files"]
            if engine in f["engines"] and "elapsed_seconds" in f["engines"][engine]
        ]
        chars = [
            f["engines"][engine]["char_count"]
            for f in report["files"]
            if engine in f["engines"] and "char_count" in f["engines"][engine]
        ]
        summary[engine] = {
            "total_files": len(times),
            "total_elapsed_seconds": round(sum(times), 3) if times else 0,
            "avg_elapsed_seconds": round(sum(times) / len(times), 3) if times else 0,
            "total_char_count": sum(chars) if chars else 0,
        }
    report["summary"] = summary

    print("\n=== Summary ===")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    if args.output:
        args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
