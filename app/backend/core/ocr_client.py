#!/usr/bin/env python3
# [Flow: Step 1 (PDF -> PNG 렌더) -> Step 2 (이미지 base64 인코딩) -> Step 3 (OpenAI-호환 호출) -> Step 4 (표/CSV 블록 추출)]
# 기존 ocr_run.py / ocr_hybrid.py 의 공통 로직을 엔드포인트·모델·프롬프트 주입형으로 일반화한 모듈.
import base64
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path


# ---------------------------------------------------------------------------
# Step 1: PDF -> PNG 렌더
# ---------------------------------------------------------------------------
def render_pdf(pdf_path: str, img_dir: str, dpi: int = 150, start: int = 1, end: int = 0) -> list[Path]:
    """PDF 페이지를 PNG 이미지로 변환한다 (poppler pdftoppm)."""
    out = Path(img_dir)
    out.mkdir(parents=True, exist_ok=True)
    args = ["pdftoppm", "-r", str(dpi), "-png", str(pdf_path), str(out / "page")]
    if end > 0:
        args = ["pdftoppm", "-f", str(start), "-l", str(end), "-r", str(dpi), "-png", str(pdf_path), str(out / "page")]
    subprocess.run(args, check=True)
    return sorted(out.glob("page-*.png"))


def find_page_number(filename: Path) -> int | None:
    """page-001.png -> 1"""
    m = re.search(r"page-(\d+)\.png", filename.name)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Step 2: 이미지 base64 인코딩 (JPEG 변환으로 페이로드 축소)
# ---------------------------------------------------------------------------
def encode_image(image_path: Path, jpeg_quality: int = 95) -> str:
    jpeg_path = image_path.with_suffix(".jpg")
    if not jpeg_path.exists():
        subprocess.run(
            ["magick", str(image_path), "-quality", str(jpeg_quality), str(jpeg_path)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    with open(jpeg_path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


# ---------------------------------------------------------------------------
# Step 3: OpenAI-호환 chat/completions 호출
# ---------------------------------------------------------------------------
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


def call_vision(image_path: Path, prompt: str, endpoint: str, model: str, api_key: str = "", max_tokens: int = 10000) -> tuple[str, str | None]:
    """이미지 + 프롬프트를 vision 모델로 전송 (ocr_run 방식)."""
    b64 = encode_image(image_path)
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
    return _post(endpoint, payload, api_key, timeout=1200)


def call_text(prompt: str, endpoint: str, model: str, api_key: str = "", max_tokens: int = 4000) -> tuple[str, str | None]:
    """텍스트 프롬프트만 전송 (ocr_hybrid 방식)."""
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    return _post(endpoint, payload, api_key, timeout=300)


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
    max_tokens: int = 10000,
) -> tuple[str, str | None]:
    """이미지(여러 장) + 오디오(1개)를 멀티모달 LLM에 전송한다."""
    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in image_paths or []:
        b64 = encode_image(img)
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})
    if audio_path:
        b64 = encode_audio(audio_path)
        content.append({"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{b64}"}})
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": content}],
    }
    return _post(endpoint, payload, api_key, timeout=1800)


# ---------------------------------------------------------------------------
# Step 4: 모델 출력에서 표/CSV 블록만 추출
# ---------------------------------------------------------------------------
def extract_markdown_table(content: str) -> str:
    """모델 출력에서 첫 마크다운 표만 추출한다."""
    if not content:
        return ""
    lines = content.strip().splitlines()
    table_lines: list[str] = []
    in_table = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            table_lines.append(stripped)
            in_table = True
        elif in_table and not stripped:
            continue
        elif in_table:
            break
    return "\n".join(table_lines) if table_lines else content.strip()


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
