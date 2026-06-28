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
    """hwp5odt로 HWP -> ODT 변환 후 LibreOffice로 ODT -> DOCX 변환한다.

    LibreOffice는 직접 HWP/HWPX를 읽지 못하는 환경이 많으므로, pyhwp의
    hwp5odt를 먼저 사용해 ODT를 생성한 뒤 DOCX로 변환한다.
    """
    output_dir = output_dir or input_path.parent
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ext = input_path.suffix.lower()
    if ext != ".hwp":
        # .hwpx 등 hwp5odt가 지원하지 않는 형식은 직접 LibreOffice 시도
        return _hwp_to_docx_with_libreoffice(input_path, output_dir)

    # 1) HWP -> ODT
    odt_path = output_dir / f"{input_path.stem}.odt"
    odt_cmd = [
        "hwp5odt",
        "--output",
        str(odt_path),
        str(input_path),
    ]
    try:
        odt_result = subprocess.run(
            odt_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            env=_libreoffice_env(),
        )
    except FileNotFoundError as e:
        logger.warning(f"[hwp5odt] 명령을 찾을 수 없습니다: {e}")
        return _hwp_to_docx_with_libreoffice(input_path, output_dir)

    odt_stderr = odt_result.stderr.decode("utf-8", errors="ignore")
    if odt_result.returncode != 0:
        logger.warning(f"[hwp5odt] 변환 실패 (returncode={odt_result.returncode}): {odt_stderr[:1000]}")
        return _hwp_to_docx_with_libreoffice(input_path, output_dir)
    if not odt_path.exists():
        logger.warning(f"[hwp5odt] ODT 산출물이 생성되지 않았습니다: {odt_path}")
        return _hwp_to_docx_with_libreoffice(input_path, output_dir)
    if odt_stderr:
        logger.debug(f"[hwp5odt] stderr: {odt_stderr[:500]}")

    # 2) ODT -> DOCX
    return _odt_to_docx_with_libreoffice(odt_path, output_dir)


def _odt_to_docx_with_libreoffice(odt_path: Path, output_dir: Path) -> Path:
    """LibreOffice headless를 이용해 ODT 파일을 DOCX로 변환한다."""
    cmd = [
        "libreoffice",
        "--headless",
        "--convert-to",
        "docx",
        "--outdir",
        str(output_dir),
        str(odt_path),
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

    expected = output_dir / f"{odt_path.stem}.docx"
    if not expected.exists():
        raise FileNotFoundError(f"LibreOffice DOCX 변환 산출물을 찾을 수 없습니다: {expected}")
    return expected


def _hwp_to_docx_with_libreoffice(input_path: Path, output_dir: Path) -> Path:
    """LibreOffice headless를 이용해 HWP/HWPX 파일을 직접 DOCX로 변환한다."""
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
        logger.warning(f"[libreoffice-docx-direct] 변환 실패 (returncode={result.returncode}): {stderr_text[:1000]} {stdout_text[:500]}")
        raise subprocess.CalledProcessError(result.returncode, cmd, output=result.stdout, stderr=result.stderr)
    if stderr_text:
        logger.debug(f"[libreoffice-docx-direct] stderr: {stderr_text[:500]}")

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
