#!/usr/bin/env python3
# [Flow: Step 1 (파일명/MAGIC으로 유형 감지) -> Step 2 (PDF/이미지/오디오/비디오/아카이브 분류) -> Step 3 (오디오/비디오 길이, 비디오 프레임 추출)]
import filetype
import subprocess
from pathlib import Path


MEDIA_TYPES = {
    "pdf": (".pdf",),
    "image": (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"),
    "audio": (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"),
    "video": (".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v"),
}


def detect_file_type(path: Path) -> str:
    """확장자와 magic bytes를 조합해 파일 유형을 결정한다."""
    ext = path.suffix.lower()
    for media_type, extensions in MEDIA_TYPES.items():
        if ext in extensions:
            return media_type
    if ext in (".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2"):
        return "archive"
    # magic bytes fallback
    try:
        kind = filetype.guess(str(path))
        if kind:
            mime = kind.mime
            if mime.startswith("image/"):
                return "image"
            if mime.startswith("audio/"):
                return "audio"
            if mime.startswith("video/"):
                return "video"
            if mime == "application/pdf":
                return "pdf"
    except Exception:
        pass
    return "unknown"


def get_media_duration_seconds(path: Path) -> int:
    """ffmpeg로 오디오/비디오 길이(초)를 반환한다."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return int(float(result.stdout.strip() or 0))
    except Exception:
        return 0


def extract_video_frames(path: Path, max_frames: int = 4, work_dir: Path | None = None) -> list[Path]:
    """비디오에서 균일한 간격으로 최대 max_frames 개의 JPEG 프레임을 추출한다."""
    out_dir = work_dir or Path(path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_media_duration_seconds(path)
    if duration <= 0:
        duration = 1
    count = min(max_frames, max(1, duration // 10))
    if count == 1:
        timestamps = [duration / 2]
    else:
        step = duration / (count + 1)
        timestamps = [step * (i + 1) for i in range(count)]

    frames: list[Path] = []
    for i, ts in enumerate(timestamps):
        out_path = out_dir / f"{path.stem}_frame_{i:03d}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss", str(ts),
                "-i", str(path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        if out_path.exists():
            frames.append(out_path)
    return frames
