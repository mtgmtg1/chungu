#!/usr/bin/env python3
"""백엔드 media 파이프라인 테스트 (Gemma-4 12B GGUF Q4_K_M 연동)."""
import base64
import subprocess
import wave
from pathlib import Path

from backend.core.pipeline_media import run_media


def make_wav(path: str, duration: int = 3) -> None:
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * (duration * 16000))


def make_video(path: str, duration: int = 5) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi", "-i",
            f"testsrc=duration={duration}:size=320x240:rate=1",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=5",
            "-pix_fmt", "yuv420p", path,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=True,
    )


def main() -> None:
    work = Path("/tmp/test_media_pipeline")
    work.mkdir(parents=True, exist_ok=True)
    audio_path = work / "test_audio.wav"
    video_path = work / "test_video.mp4"
    make_wav(str(audio_path))
    make_video(str(video_path))

    files = [("audio", audio_path), ("video", video_path)]
    results = run_media(
        files,
        str(work / "work"),
        columns=["내용"],
        endpoint="http://192.168.1.69:18080/v1",
        model="cyankiwi/gemma-4-12B-it-qat-AWQ-INT4",
        media_endpoint="http://192.168.1.82:18080/v1",
        media_model="unsloth/gemma-4-12b-it-GGUF",
        max_tokens=200,
    )
    for filename, position, table in results:
        print(f"=== {filename} (position={position}) ===")
        print(table)
        print()


if __name__ == "__main__":
    main()
