#!/usr/bin/env python3
# [Flow: Step 1 (PDF -> PNG 렌더) -> Step 2 (이미지를 Gemma 4 해상도에 맞게 축소) -> Step 3 (페이지 텍스트 레이어 추출) -> Step 4 (이미지 base64 인코딩) -> Step 5 (OpenAI-호환 호출) -> Step 6 (표/CSV 블록 추출)]
# 기존 ocr_run.py / ocr_hybrid.py 의 공통 로직을 엔드포인트·모델·프롬프트 주입형으로 일반화한 모듈.
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
# Step 1: PDF -> PNG 렌더
# ---------------------------------------------------------------------------
def render_pdf(pdf_path: str, img_dir: str, dpi: int = 300, start: int = 1, end: int = 0) -> list[Path]:
    """PDF 페이지를 PNG 이미지로 변환한다 (poppler pdftoppm)."""
    out = Path(img_dir)
    out.mkdir(parents=True, exist_ok=True)
    # Gemma 4 비전 인코더 VRAM OOM을 방지하면서 높은 해상도를 유지: 300 DPI 상한
    effective_dpi = min(dpi, 300)
    args = ["pdftoppm", "-r", str(effective_dpi), "-png", str(pdf_path), str(out / "page")]
    if end > 0:
        args = ["pdftoppm", "-f", str(start), "-l", str(end), "-r", str(effective_dpi), "-png", str(pdf_path), str(out / "page")]
    subprocess.run(args, check=True)
    return sorted(out.glob("page-*.png"))


def find_page_number(filename: Path) -> int | None:
    """page-001.png -> 1"""
    m = re.search(r"page-(\d+)\.png", filename.name)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Step 2: Gemma 4 비전 인코더가 처리할 수 있는 해상도로 맞춤
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
    """이미지를 Gemma 4 비전 인코더가 처리 가능한 해상도 이하로 축소한다.

    Gemma 4의 이미지 프로세서는 patch_size(16) * pooling_kernel_size(3) = 48 픽셀 단위로
    패치를 생성하고, max_soft_tokens(최대 1120) 개수를 넘지 않도록 내부에서 리사이즈한다.
    OOM을 방지하기 위해 전송 전에 동일한 규칙으로 축소해 전송 payload와 VRAM 사용량을 줄인다.
    """
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
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return resized_path


# ---------------------------------------------------------------------------
# Step 2b: 큰 이미지를 타일로 분할 (화이트보드/플래너 등 고해상도 이미지)
# ---------------------------------------------------------------------------
TILE_OVERLAP_RATIO = 0.15


def tile_large_image(
    image_path: Path,
    max_soft_tokens: int = GEMMA4_MAX_SOFT_TOKENS,
    patch_size: int = GEMMA4_PATCH_SIZE,
    pooling_kernel_size: int = GEMMA4_POOLING_KERNEL,
    overlap_ratio: float = TILE_OVERLAP_RATIO,
) -> list[Path]:
    # [Flow: Step 1 (이미지 크기 확인) -> Step 2 (분할 필요 시 타일 생성) -> Step 3 (타일 경로 반환)]
    """큰 이미지를 Gemma 4 해상도 한계 내의 겹치는 타일로 분할한다.

    이미지가 max_pixels 이내면 원본을 그대로 반환한다.
    초과하면 overlap_ratio 만큼 겹치는 타일들을 생성해 좌→우, 상→하 순서로 반환한다.
    """
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
# Step 3: PDF 텍스트 레이어 추출 (레이아웃 보존)
# ---------------------------------------------------------------------------
def extract_pdf_page_text(pdf_path: str, page_num: int) -> str:
    """pdftotext -layout으로 특정 페이지의 텍스트 레이어를 추출한다."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", "-f", str(page_num), "-l", str(page_num), str(pdf_path), "-"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Step 4: 이미지 base64 인코딩 (JPEG 변환으로 페이로드 축소)
# ---------------------------------------------------------------------------
def encode_image(image_path: Path, jpeg_quality: int = 95) -> str:
    fitted = fit_image_to_gemma4_resolution(image_path)
    jpeg_path = fitted.with_suffix(".jpg")
    if not jpeg_path.exists():
        subprocess.run(
            ["magick", str(fitted), "-quality", str(jpeg_quality), str(jpeg_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    with open(jpeg_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Step 5: OpenAI-호환 chat/completions 호출
# ---------------------------------------------------------------------------
def _is_gemma4(model: str) -> bool:
    """모델명이 Gemma 4 계열인지 확인한다."""
    return "gemma-4" in (model or "").lower()


def _with_gemma4_kwargs(payload: dict, model: str) -> dict:
    """Gemma 4 모델이라면 thinking 모드를 비활성화한다."""
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
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(2 ** attempt)
    raise RuntimeError(last_err)


def call_vision(image_path: Path, prompt: str, endpoint: str, model: str, api_key: str = "", max_tokens: int = 10000, page_text: str = "") -> tuple[str, str | None]:
    """이미지 + 프롬프트를 vision 모델로 전송 (ocr_run 방식)."""
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
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            }
        ],
    }
    return _post(endpoint, _with_gemma4_kwargs(payload, model), api_key, timeout=1200)


def call_text(prompt: str, endpoint: str, model: str, api_key: str = "", max_tokens: int = 4000) -> tuple[str, str | None]:
    """텍스트 프롬프트만 전송 (ocr_hybrid 방식)."""
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
        ".wav": "audio/wav",
        ".mp3": "audio/mp3",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/m4a",
        ".mp4": "video/mp4",
        ".webm": "video/webm",
        ".mov": "video/quicktime",
        ".avi": "video/x-msvideo",
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
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
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
    """이미지(여러 장) + 오디오(1개) + 비디오(1개)를 멀티모달 LLM에 전송한다.

    provider:
      - "openai": vLLM/표준 OpenAI 호환 (audio_url, video_url, image_url)
      - "llama.cpp": llama.cpp 서버 네이티브 멀티모달 (input_audio, input_video, image_url)
    """
    content: list[dict] = [{"type": "text", "text": prompt}]
    modalities: list[str] = ["text"]
    for img in image_paths or []:
        b64 = encode_image(img)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
        modalities.append("image")

    if audio_path:
        b64 = encode_audio(audio_path)
        if provider == "llama.cpp":
            content.append({"type": "input_audio", "input_audio": {"data": b64}})
        else:
            content.append({"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{b64}"}})
        modalities.append("audio")

    if video_path:
        b64, mime = encode_file(video_path)
        if provider == "llama.cpp":
            content.append({"type": "input_video", "input_video": {"data": b64}})
        else:
            content.append({"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}})
        modalities.append("video")

    logger.info(f"[call-media] provider={provider}, modalities={modalities}, images={len(image_paths or [])}, audio={audio_path is not None}, video={video_path is not None}")

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    return _post(endpoint, _with_gemma4_kwargs(payload, model), api_key, timeout=1800)


# ---------------------------------------------------------------------------
# Step 4: 모델 출력에서 표/CSV 블록만 추출
# ---------------------------------------------------------------------------
def extract_markdown_content(content: str) -> str:
    """모델 출력에서 마크다운 레이아웃 전체를 추출한다."""
    if not content:
        return ""
    content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content).strip()
    return content


# 하위호환 alias
extract_markdown_table = extract_markdown_content


def extract_csv(content: str) -> str:
    """모델 출력에서 CSV 블록을 추출한다 (코드펜스 제거)."""
    if not content:
        return ""
    content = re.sub(r"```[a-zA-Z]*\n?|\n?```", "", content)
    lines = [line.strip() for line in content.strip().splitlines()]
    return "\n".join(line for line in lines if line and ("," in line))


def tesseract_ocr(image_path: Path, text_path: Path, lang: str = "kor+eng") -> Path:
    """Tesseract로 PNG에서 원문 텍스트를 추출한다 (hybrid 1단계)."""
    if text_path.exists():
        return text_path
    result = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", lang],
        capture_output=True,
        text=True,
    )
    text_path.write_text(result.stdout, encoding="utf-8")
    return text_path
