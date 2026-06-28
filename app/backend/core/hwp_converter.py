#!/usr/bin/env python3
# [Flow: Step 1 (HWP/HWPX 파일 검증) -> Step 2 (LibreOffice로 DOCX 변환 시도) -> Step 3 (pyhwp2md로 마크다운 추출 fallback) -> Step 4 (pyhwp Hwp5File로 BinData 이미지 추출) -> Step 5 (페이지 수 추정) -> Step 6 (결과 반환)]
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

from pyhwp2md import convert as hwp_to_markdown


logger = logging.getLogger(__name__)

HWP_EXTENSIONS = {".hwp", ".hwpx"}


def is_hwp_file(path: Path) -> bool:
    """HWP/HWPX 파일 여부."""
    return path.suffix.lower() in HWP_EXTENSIONS


def _libreoffice_env() -> dict[str, str]:
    """LibreOffice headless 변환에 필요한 locale 및 사용자 프로필 경로를 설정한다."""
    return {
        **dict(os.environ),
        "LANG": "ko_KR.UTF-8",
        "LC_ALL": "ko_KR.UTF-8",
        "HOME": "/tmp",
        "XDG_CONFIG_HOME": "/tmp/.config",
        "XDG_CACHE_HOME": "/tmp/.cache",
    }


def convert_to_docx(input_path: Path, output_dir: Path | None = None) -> Path:
    """LibreOffice headless를 이용해 HWP/HWPX 파일을 DOCX로 변환한다."""
    output_dir = output_dir or input_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(output_dir),
        str(input_path),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=120,
        env=_libreoffice_env(),
    )
    stdout_text = result.stdout.decode("utf-8", errors="ignore")
    stderr_text = result.stderr.decode("utf-8", errors="ignore")
    if result.returncode != 0:
        logger.warning(f"[libreoffice-docx] 변환 실패 (returncode={result.returncode}): {stderr_text[:1000]} {stdout_text[:500]}")
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    if stderr_text:
        logger.debug(f"[libreoffice-docx] stderr: {stderr_text[:500]}")

    expected = output_dir / f"{input_path.stem}.docx"
    if not expected.exists():
        raise FileNotFoundError(f"LibreOffice DOCX 변환 산출물을 찾을 수 없습니다: {expected}")
    return expected


def extract_markdown(path: Path) -> str:
    """HWP/HWPX 파일을 마크다운 텍스트로 변환한다."""
    return hwp_to_markdown(str(path))


def extract_images(path: Path, image_dir: Path) -> list[Path]:
    """HWP/HWPX 파일의 BinData 스토리지에서 이미지를 추출한다."""
    image_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    try:
        from hwp5.filestructure import Hwp5File

        hwp = Hwp5File(str(path))
        if "BinData" not in hwp:
            return paths

        bindata = hwp["BinData"]
        for name in bindata:
            try:
                item = bindata[name]
                out_path = image_dir / name
                with open(out_path, "wb") as f:
                    f.write(item.open().read())
                paths.append(out_path)
            except Exception as e:
                logger.warning(f"[hwp-image] {name} 추출 실패: {e}")
    except Exception as e:
        logger.warning(f"[hwp-image] HWP 이미지 추출 실패: {e}")
    return paths


def get_page_count(path: Path) -> int:
    """HWP/HWPX 파일의 페이지 수를 추정한다. 실패하면 1을 반환한다."""
    try:
        from hwp5.filestructure import Hwp5File

        hwp = Hwp5File(str(path))
        summary = hwp.summaryinfo
        if summary and summary.numberOfPages:
            return int(summary.numberOfPages)
    except Exception as e:
        logger.warning(f"[hwp-page-count] {path.name} 실패: {e}")
    return 1


def convert_hwp(
    path: Path,
    image_dir: Path,
) -> dict[str, Any]:
    """HWP/HWPX 파일을 마크다운 + 이미지 + 페이지 수로 변환한다.

    반환 형식은 Docling 서비스 응답과 호환된다:
    {
        "markdown": str,
        "images": [str],  # image_dir 내 상대 경로
        "page_count": int,
        "file_type": "hwp",
        "error": str | None,
    }
    """
    try:
        markdown = extract_markdown(path)
    except Exception as e:
        logger.exception(f"[hwp] {path.name} 마크다운 추출 실패: {e}")
        return {"markdown": "", "images": [], "page_count": 1, "file_type": "hwp", "error": str(e)}

    try:
        image_paths = extract_images(path, image_dir)
        images = [str(p.relative_to(image_dir)) for p in image_paths]
    except Exception as e:
        logger.warning(f"[hwp] {path.name} 이미지 추출 실패: {e}")
        images = []

    page_count = get_page_count(path)
    return {"markdown": markdown, "images": images, "page_count": page_count, "file_type": "hwp", "error": None}
