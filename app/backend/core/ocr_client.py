#!/usr/bin/env python3
# [Flow: Step 1 (PDF -> PNG 렌더) -> Step 2 (이미지 해상도 맞춤) -> Step 3 (텍스트 레이어 추출) -> Step 4 (LLM 호출) -> Step 5 (마크다운/CSV 추출)]
# LLM 호출 및 이미지 처리 유틸리티 모듈.
# OCR은 Docling 서비스에서 처리하므로 커스텀 OCR 코드는 제거되었다.
import base64
import json
import logging
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PDF -> PNG 렌더 (PyMuPDF 멀티스레드)
# ---------------------------------------------------------------------------
def _render_single_page(args: tuple[int, str, str, float]) -> Path:
    """단일 페이지를 PNG로 렌더링한다 (ThreadPoolExecutor 워커용)."""
    page_num, pdf_path, out_dir, zoom = args
    import fitz
    doc = fitz.open(pdf_path)
    page = doc[page_num]
    matrix = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=matrix)
    out_path = Path(out_dir) / f"page-{page_num + 1:03d}.png"
    pix.save(str(out_path))
    doc.close()
    return out_path


def render_pdf(pdf_path: str, img_dir: str, dpi: int = 300, start: int = 1, end: int = 0) -> list[Path]:
    """PDF 페이지를 PNG 이미지로 변환한다 (PyMuPDF 멀티스레드).

    [Flow: Step 1 (PDF 열기/페이지 수 확인) -> Step 2 (페이지 범위 계산) -> Step 3 (ThreadPoolExecutor로 병렬 렌더링) -> Step 4 (정렬된 PNG 경로 목록 반환)]
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import fitz

    out = Path(img_dir)
    out.mkdir(parents=True, exist_ok=True)
    effective_dpi = min(dpi, 300)
    zoom = effective_dpi / 72.0

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    doc.close()

    if end > 0:
        page_start = max(start - 1, 0)
        page_end = min(end, total_pages)
    else:
        page_start = 0
        page_end = total_pages

    page_indices = range(page_start, page_end)
    tasks = [(i, pdf_path, str(out), zoom) for i in page_indices]

    results: list[Path] = []
    max_workers = min(len(tasks), 16)
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_render_single_page, t): t[0] for t in tasks}
        for future in as_completed(futures):
            results.append(future.result())

    return sorted(out.glob("page-*.png"))


def find_page_number(filename: Path) -> int | None:
    """page-001.png -> 1"""
    m = re.search(r"page-(\d+)\.png", filename.name)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Gemma 4 비전 인코더 해상도 맞춤
# ---------------------------------------------------------------------------
GEMMA4_MAX_SOFT_TOKENS = 1120
GEMMA4_PATCH_SIZE = 16
GEMMA4_POOLING_KERNEL = 3
GEMMA4_EFFECTIVE_PATCH = GEMMA4_PATCH_SIZE * GEMMA4_POOLING_KERNEL


def fit_image_to_gemma4_resolution(
    image_path: Path,
    max_soft_tokens: int = GEMMA4_MAX_SOFT_TOKENS,
    patch_size: int = GEMMA4_PATCH_SIZE,
    pooling_kernel_size: int = GEMMA4_POOLING_KERNEL,
) -> Path:
    """이미지를 Gemma 4 비전 인코더가 처리 가능한 해상도 이하로 축소한다."""
    effective = patch_size * pooling_kernel_size
    max_pixels = max_soft_tokens * effective * effective

    with Image.open(image_path) as img:
        width, height = img.size
        if width * height <= max_pixels:
            return image_path
        scale = (max_pixels / (width * height)) ** 0.5
        new_w = max((int(width * scale) // effective) * effective, effective)
        new_h = max((int(height * scale) // effective) * effective, effective)

    resized_path = image_path.with_suffix(".resized" + image_path.suffix)
    subprocess.run(
        ["magick", str(image_path), "-resize", f"{new_w}x{new_h}", str(resized_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    return resized_path


# ---------------------------------------------------------------------------
# 큰 이미지 타일 분할 (화이트보드/플래너 등 고해상도)
# ---------------------------------------------------------------------------
TILE_OVERLAP_RATIO = 0.15


def tile_large_image(
    image_path: Path,
    max_soft_tokens: int = GEMMA4_MAX_SOFT_TOKENS,
    patch_size: int = GEMMA4_PATCH_SIZE,
    pooling_kernel_size: int = GEMMA4_POOLING_KERNEL,
    overlap_ratio: float = TILE_OVERLAP_RATIO,
) -> list[Path]:
    """큰 이미지를 Gemma 4 해상도 한계 내의 겹치는 타일로 분할한다."""
    effective = patch_size * pooling_kernel_size
    max_pixels = max_soft_tokens * effective * effective
    max_side = int(max_pixels ** 0.5)

    with Image.open(image_path) as img:
        w, h = img.size
        if w * h <= max_pixels:
            return [image_path]

        tile_w = min(w, max_side)
        tile_h = min(h, max_side)
        overlap_w = int(tile_w * overlap_ratio)
        overlap_h = int(tile_h * overlap_ratio)
        step_w = tile_w - overlap_w
        step_h = tile_h - overlap_h

        cols = max(1, (w - overlap_w + step_w - 1) // step_w)
        rows = max(1, (h - overlap_h + step_h - 1) // step_h)

        tiles: list[Path] = []
        for row in range(rows):
            for col in range(cols):
                left = min(col * step_w, w - tile_w)
                top = min(row * step_h, h - tile_h)
                right = left + tile_w
                bottom = top + tile_h
                tile = img.crop((left, top, right, bottom))
                tile_path = image_path.with_suffix(f".tile_r{row}_c{col}.png")
                tile.save(tile_path, "PNG")
                tiles.append(tile_path)

        logger.info(f"[tile] {image_path.name} ({w}x{h}) -> {len(tiles)} tiles ({rows}x{cols})")
        return tiles


# ---------------------------------------------------------------------------
# PDF 텍스트 레이어 추출
# ---------------------------------------------------------------------------
def extract_pdf_page_text(pdf_path: str, page_num: int) -> str:
    """pdftotext -layout으로 특정 페이지의 텍스트 레이어를 추출한다."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-f", str(page_num), "-l", str(page_num), str(pdf_path), "-"],
            capture_output=True, text=True, check=False, timeout=30,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def has_pdf_text_layer(pdf_path: str, min_chars: int = 50) -> bool:
    """PDF에 텍스트 레이어가 있는지 전체 페이지에서 빠르게 검사한다.

    Args:
        pdf_path: PDF 파일 경로
        min_chars: 텍스트 레이어 존재로 판단할 최소 문자 수
    Returns:
        True if 텍스트 레이어가 충분히 존재함
    """
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", str(pdf_path), "-"],
            capture_output=True, text=True, check=False, timeout=60,
        )
        return len(result.stdout.strip()) >= min_chars
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 이미지 base64 인코딩
# ---------------------------------------------------------------------------
def encode_image(image_path: Path, jpeg_quality: int = 95) -> str:
    """이미지를 JPEG으로 변환 후 base64 인코딩한다."""
    fitted = fit_image_to_gemma4_resolution(image_path)
    jpeg_path = fitted.with_suffix(".jpg")
    if not jpeg_path.exists():
        subprocess.run(
            ["magick", str(fitted), "-quality", str(jpeg_quality), str(jpeg_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    with open(jpeg_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# OpenAI 호환 LLM 호출
# ---------------------------------------------------------------------------
def _is_gemma4(model: str) -> bool:
    return "gemma-4" in (model or "").lower()


def _with_gemma4_kwargs(payload: dict, model: str) -> dict:
    if _is_gemma4(model):
        payload.setdefault("chat_template_kwargs", {})
        payload["chat_template_kwargs"]["enable_thinking"] = False
    return payload


def _post(endpoint: str, payload: dict, api_key: str = "", timeout: int = 1200, retries: int = 3) -> tuple[str, str | None]:
    """엔드포인트로 POST하고 (content, finish_reason)을 반환. 재시도 포함."""
    url = endpoint.rstrip("/") + "/chat/completions"
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read().decode("utf-8"))
            choice = result["choices"][0]
            return choice["message"].get("content") or "", choice.get("finish_reason")
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}"
            time.sleep(2 ** attempt)
        except Exception as e:
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(last_err)


def call_vision(image_path: Path, prompt: str, endpoint: str, model: str, api_key: str = "", max_tokens: int = 10000, page_text: str = "") -> tuple[str, str | None]:
    """이미지 + 프롬프트를 vision 모델로 전송한다."""
    b64 = encode_image(image_path)
    if page_text.strip():
        prompt = (
            f"{prompt}\n\n"
            "참고: 이 PDF 페이지에서 추출한 텍스트 레이어는 아래와 같습니다. "
            "텍스트가 내용의 정확한 기준이므로, 이미지의 레이아웃을 완전히 보존하면서 이 텍스트를 우선적으로 사용해 마크다운으로 변환하세요. "
            "텍스트 레이어에 있는 모든 텍스트를 누락 없이 포함하고, 이미지에서 텍스트 레이어에 없는 추가 시각적 정보도 놓치지 마세요."
            f"\n\n--- PDF 텍스트 레이어 ---\n{page_text.strip()}"
        )
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]}],
    }
    return _post(endpoint, _with_gemma4_kwargs(payload, model), api_key, timeout=1200)


def call_text(prompt: str, endpoint: str, model: str, api_key: str = "", max_tokens: int = 4000) -> tuple[str, str | None]:
    """텍스트 프롬프트만 전송한다."""
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    return _post(endpoint, _with_gemma4_kwargs(payload, model), api_key, timeout=300)


def encode_file(path: Path) -> tuple[str, str]:
    """임의 파일을 base64와 MIME prefix로 변환한다."""
    suffix = path.suffix.lower()
    mime_map = {
        ".wav": "audio/wav", ".mp3": "audio/mp3", ".ogg": "audio/ogg",
        ".flac": "audio/flac", ".m4a": "audio/m4a", ".mp4": "video/mp4",
        ".webm": "video/webm", ".mov": "video/quicktime", ".avi": "video/x-msvideo",
    }
    mime = mime_map.get(suffix, "application/octet-stream")
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return b64, mime


def encode_audio(path: Path) -> str:
    """오디오 파일을 base64 wav로 변환한다 (ffmpeg)."""
    wav_path = path.with_suffix(".wav")
    if not wav_path.exists():
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(path), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
    with open(wav_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def call_media(
    prompt: str,
    endpoint: str,
    model: str,
    api_key: str = "",
    image_paths: list[Path] | None = None,
    audio_path: Path | None = None,
    video_path: Path | None = None,
    max_tokens: int = 10000,
    provider: str = "openai",
) -> tuple[str, str | None]:
    """이미지(여러 장) + 오디오(1개) + 비디오(1개)를 멀티모달 LLM에 전송한다."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in image_paths or []:
        b64 = encode_image(img)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    if audio_path:
        b64 = encode_audio(audio_path)
        if provider == "llama.cpp":
            content.append({"type": "input_audio", "input_audio": {"data": b64}})
        else:
            content.append({"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{b64}"}})

    if video_path:
        b64, mime = encode_file(video_path)
        if provider == "llama.cpp":
            content.append({"type": "input_video", "input_video": {"data": b64}})
        else:
            content.append({"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}})

    logger.info(f"[call-media] provider={provider}, images={len(image_paths or [])}, audio={audio_path is not None}, video={video_path is not None}")

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    return _post(endpoint, _with_gemma4_kwargs(payload, model), api_key, timeout=1800)


# ---------------------------------------------------------------------------
# 모델 출력에서 마크다운/CSV 추출
# ---------------------------------------------------------------------------
def extract_markdown_content(content: str) -> str:
    """모델 출력에서 마크다운 레이아웃 전체를 추출한다."""
    if not content:
        return ""
    return re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()


extract_markdown_table = extract_markdown_content


def extract_csv(content: str) -> str:
    """모델 출력에서 CSV 블록을 추출한다."""
    if not content:
        return ""
    content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content)
    lines = [line.strip() for line in content.strip().splitlines()]
    return "\n".join(line for line in lines if line and "," in line)
