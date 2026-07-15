#!/usr/bin/env python3
"""PDF 무손실 압축 최적화 유틸리티.

PyMuPDF(deflate=True, garbage=4)를 사용하여 PDF 내부 스트림을 재압축한다.
이미지 품질이나 DPI를 변경하지 않으므로 OCR 정확도에 영향이 없다.
일반적으로 스캐너/오피스 소프트웨어가 생성한 PDF는 비효율적 인코딩을 사용하므로
50~70% 크기 감소 효과가 있다 (테스트: 12.5MB → 3.4MB).

[Flow: Step 1 (원본 PDF 크기 확인) -> Step 2 (임계값 이하면 스킵) -> Step 3 (PyMuPDF로 deflate+garbage 재저장) -> Step 4 (최적화된 PDF 경로 반환)]
"""
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# 이 크기(MB) 이하의 PDF는 최적화를 생략한다 (오버헤드가 감소 효과보다 큼)
MIN_OPTIMIZE_SIZE_MB = 1.0


def optimize_pdf(pdf_path: Path | str, output_dir: Path | str | None = None) -> Path:
    """PDF를 무손실 압축하여 최적화한다.

    [Flow: Step 1 (원본 PDF 크기 확인) -> Step 2 (임계값 이하면 원본 그대로 반환)
          -> Step 3 (PyMuPDF로 deflate=True, garbage=4 재저장) -> Step 4 (최적화된 PDF 경로 반환)]

    이미지 품질이나 DPI를 변경하지 않고 PDF 내부 스트림만 재압축한다.
    원본 PDF가 최적화 대상(1MB 초과)인 경우에만 최적화를 수행하고,
    그렇지 않으면 원본 경로를 그대로 반환한다.

    Args:
        pdf_path: 최적화할 PDF 파일 경로
        output_dir: 최적화된 PDF를 저장할 디렉토리 (기본: 원본과 동일 디렉토리)

    Returns:
        최적화된 PDF 파일 경로 (원본이 최적화 대상이 아닌 경우 원본 경로)
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    original_size_mb = pdf_path.stat().st_size / 1024 / 1024

    # 임계값 이하면 최적화 생략
    if original_size_mb <= MIN_OPTIMIZE_SIZE_MB:
        logger.debug(f"[pdf-optimize] {pdf_path.name} ({original_size_mb:.2f}MB) — 임계값 이하, 최적화 생략")
        return pdf_path

    # 이미 최적화된 파일은 재최적화하지 않는다
    if pdf_path.stem.endswith("_optimized"):
        logger.debug(f"[pdf-optimize] {pdf_path.name} — 이미 최적화됨, 생략")
        return pdf_path

    import fitz

    # 출력 경로 설정
    if output_dir is None:
        out_dir = pdf_path.parent
    else:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{pdf_path.stem}_optimized.pdf"

    # PyMuPDF로 무손실 재압축
    doc = fitz.open(str(pdf_path))
    try:
        doc.save(str(out_path), deflate=True, garbage=4)
    finally:
        doc.close()

    optimized_size_mb = out_path.stat().st_size / 1024 / 1024
    reduction_pct = (1 - optimized_size_mb / original_size_mb) * 100

    logger.info(
        f"[pdf-optimize] {pdf_path.name} 최적화 완료: "
        f"{original_size_mb:.2f}MB → {optimized_size_mb:.2f}MB ({reduction_pct:.0f}% 감소)"
    )

    return out_path


def optimize_pdf_in_place(pdf_path: Path | str) -> Path:
    """PDF를 무손실 압축하여 원본을 대체한다.

    [Flow: Step 1 (optimize_pdf로 임시 파일 생성) -> Step 2 (원본을 최적화된 파일로 대체) -> Step 3 (최종 경로 반환)]

    Args:
        pdf_path: 최적화할 PDF 파일 경로

    Returns:
        최적화된 PDF 파일 경로 (원본과 동일 경로)
    """
    pdf_path = Path(pdf_path)
    original_size_mb = pdf_path.stat().st_size / 1024 / 1024

    if original_size_mb <= MIN_OPTIMIZE_SIZE_MB:
        return pdf_path

    # 임시 디렉토리에 최적화 후 원본 대체
    with tempfile.TemporaryDirectory() as tmpdir:
        optimized = optimize_pdf(pdf_path, output_dir=tmpdir)
        if optimized == pdf_path:
            return pdf_path

        # 원본을 최적화된 파일로 대체
        import shutil
        shutil.move(str(optimized), str(pdf_path))

        final_size_mb = pdf_path.stat().st_size / 1024 / 1024
        logger.info(f"[pdf-optimize] in-place 완료: {pdf_path.name} ({final_size_mb:.2f}MB)")

    return pdf_path


def optimize_pdf_bytes(pdf_bytes: bytes) -> bytes:
    """PDF bytes를 무손실 압축하여 최적화된 bytes를 반환한다.

    [Flow: Step 1 (원본 크기 확인) -> Step 2 (임계값 이하면 원본 그대로 반환)
          -> Step 3 (PyMuPDF로 deflate=True, garbage=4 재저장) -> Step 4 (최적화된 bytes 반환)]

    Storage에서 다운로드한 PDF bytes를 메모리에서 직접 최적화한다.
    이미지 품질이나 DPI를 변경하지 않고 PDF 내부 스트림만 재압축한다.

    Args:
        pdf_bytes: 최적화할 PDF 바이트 데이터

    Returns:
        최적화된 PDF 바이트 데이터 (원본이 최적화 대상이 아닌 경우 원본 bytes)
    """
    original_size_mb = len(pdf_bytes) / 1024 / 1024

    # 임계값 이하면 최적화 생략
    if original_size_mb <= MIN_OPTIMIZE_SIZE_MB:
        return pdf_bytes

    import fitz
    import io

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        buf = io.BytesIO()
        doc.save(buf, deflate=True, garbage=4)
        optimized_bytes = buf.getvalue()
    finally:
        doc.close()

    optimized_size_mb = len(optimized_bytes) / 1024 / 1024
    reduction_pct = (1 - optimized_size_mb / original_size_mb) * 100

    logger.info(
        f"[pdf-optimize] bytes 최적화 완료: "
        f"{original_size_mb:.2f}MB → {optimized_size_mb:.2f}MB ({reduction_pct:.0f}% 감소)"
    )

    return optimized_bytes
