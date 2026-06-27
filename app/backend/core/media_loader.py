#!/usr/bin/env python3
# [Flow: Step 1 (파일명/MAGIC으로 유형 감지) -> Step 2 (PDF/이미지/오디오/비디오/아카이브 분류) -> Step 3 (오디오/비디오 길이, 세그먼트별 프레임/오디오 추출)]
import filetype
import subprocess
from pathlib import Path


MEDIA_TYPES = {
    "pdf": (".pdf",),
    "image": (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".tif"),
    "audio": (".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma"),
    "video": (".mp4", ".avi", ".mov", ".mkv", ".flv", ".wmv", ".webm", ".m4v"),
    "docx": (".docx", ".doc", ".dotx", ".docm"),
    "pptx": (".pptx", ".ppt", ".potx", ".ppsx", ".pptm", ".potm", ".ppsm"),
    "xlsx": (".xlsx", ".xls", ".xlsm"),
    "html": (".html", ".htm", ".xhtml"),
    "hwp": (".hwp", ".hwpx"),
}

# Docling 전처리 서비스가 처리할 수 있는 파일 타입 (PDF + 오피스 + HTML)
DOCLING_TYPES = {"pdf", "docx", "pptx", "xlsx", "html"}

# pyhwp 기반 처리 파일 타입
HWP_TYPES = {"hwp"}


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
            if mime in (
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                "application/msword",
            ):
                return "docx"
            if mime in (
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
                "application/vnd.ms-powerpoint",
            ):
                return "pptx"
            if mime in (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/vnd.ms-excel",
            ):
                return "xlsx"
            if mime == "text/html":
                return "html"
            if mime in ("application/x-hwp", "application/vnd.hancom.hwp"):
                return "hwp"
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


def _format_segment_prefix(start: float, end: float) -> str:
    """세그먼트 구간을 파일명에 사용할 고유 짧은 접두어로 변환한다."""
    return f"seg_{int(start):04d}_{int(end):04d}_"


def extract_video_frames(
    path: Path,
    max_frames: int = 4,
    work_dir: Path | None = None,
    start: float = 0,
    end: float | None = None,
    fps: float = 1,
) -> list[tuple[float, Path]]:
    """비디오에서 JPEG 프레임을 추출한다.

    - end가 None이고 start가 0이면: 전체 영상에서 max_frames 개 균등 추출 (레거시 모드)
    - 그 외: [start, end] 구간에서 fps 기준으로 추출, max_frames 개로 제한

    반환: [(timestamp_seconds, frame_path), ...]
    """
    out_dir = work_dir or Path(path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_media_duration_seconds(path)
    if duration <= 0:
        duration = 1

    segment_mode = end is not None or start > 0
    if not segment_mode:
        return _extract_evenly_spaced_frames(path, max_frames, out_dir, duration)

    if end is None:
        end = duration
    start = max(0.0, start)
    end = min(end, duration)
    segment_duration = max(1.0, end - start)

    prefix = _format_segment_prefix(start, end)
    out_pattern = out_dir / f"{prefix}frame_%03d.jpg"
    count = min(max_frames, int(segment_duration * fps))

    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss", str(start),
            "-i", str(path),
            "-to", str(end),
            "-vf", f"fps={fps}",
            "-q:v", "2",
            str(out_pattern),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )

    frames: list[tuple[float, Path]] = []
    for i in range(count):
        frame_path = out_dir / f"{prefix}frame_{i + 1:03d}.jpg"
        if not frame_path.exists():
            break
        ts = start + i / fps
        frames.append((ts, frame_path))
    return frames


def _extract_evenly_spaced_frames(
    path: Path,
    max_frames: int,
    out_dir: Path,
    duration: int,
) -> list[tuple[float, Path]]:
    """전체 영상에서 균일한 간격으로 max_frames 개 프레임을 추출한다."""
    count = min(max_frames, max(1, int(duration // 3)))
    if count == 1:
        timestamps = [duration / 2]
    else:
        step = duration / (count + 1)
        timestamps = [step * (i + 1) for i in range(count)]

    frames: list[tuple[float, Path]] = []
    for i, ts in enumerate(timestamps):
        # 원본 파일명이 길 경우(특히 한글 NFD) 파일명 길이 제한을 초과할 수 있으므로 짧은 고정 이름 사용
        out_path = out_dir / f"frame_{i:03d}.jpg"
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
            frames.append((ts, out_path))
    return frames


def _extract_audio_segment_to_wav(
    path: Path,
    start: float,
    end: float,
    out_dir: Path,
    extra_args: list[str] | None = None,
) -> Path | None:
    """오디오/비디오의 특정 구간을 16kHz mono WAV로 추출하는 내부 헬퍼."""
    prefix = _format_segment_prefix(start, end)
    out_path = out_dir / f"{prefix}audio.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-ss", str(start),
        "-i", str(path),
        "-to", str(end),
        *(extra_args or []),
        "-ar", "16000",
        "-ac", "1",
        "-c:a", "pcm_s16le",
        str(out_path),
    ]
    subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=120,
    )

    if out_path.exists() and out_path.stat().st_size > 0:
        return out_path
    return None


def extract_video_audio(
    path: Path,
    start: float = 0,
    end: float | None = None,
    work_dir: Path | None = None,
) -> Path | None:
    """비디오의 특정 구간 오디오를 16kHz mono WAV로 추출한다.

    반환: 추출된 WAV 파일 경로, 실패 시 None
    """
    out_dir = work_dir or Path(path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_media_duration_seconds(path)
    if duration <= 0:
        return None

    if end is None:
        end = duration
    start = max(0.0, start)
    end = min(end, duration)
    if end <= start:
        return None

    return _extract_audio_segment_to_wav(path, start, end, out_dir, extra_args=["-vn"])


def extract_audio_segment(
    path: Path,
    start: float = 0,
    end: float | None = None,
    work_dir: Path | None = None,
) -> Path | None:
    """오디오 파일의 특정 구간을 16kHz mono WAV로 추출한다.

    반환: 추출된 WAV 파일 경로, 실패 시 None
    """
    out_dir = work_dir or Path(path).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_media_duration_seconds(path)
    if duration <= 0:
        return None

    if end is None:
        end = duration
    start = max(0.0, start)
    end = min(end, duration)
    if end <= start:
        return None

    return _extract_audio_segment_to_wav(path, start, end, out_dir)
