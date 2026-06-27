#!/usr/bin/env python3
"""llama-server 비디오 테스트 (Gemma-4 12B GGUF Q4_K_M)."""
import base64
import json
import subprocess
from pathlib import Path

import requests


def make_video(path: str, duration: int = 5) -> None:
    """ffmpeg로 테스트용 MP4 비디오를 생성한다."""
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
    video_path = Path("/tmp/test_video.mp4")
    make_video(str(video_path))

    b64 = base64.b64encode(video_path.read_bytes()).decode()
    payload = {
        "model": "unsloth/gemma-4-12b-it-GGUF",
        "temperature": 0,
        "max_tokens": 200,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "이 비디오를 시간, 장면/행동 묘사, 발화자, 대사/소리로 구성된 마크다운 표로 대본화해주세요.",
                    },
                    {"type": "input_video", "input_video": {"data": b64}},
                ],
            }
        ],
    }

    resp = requests.post(
        "http://192.168.1.82:18080/v1/chat/completions",
        json=payload,
        timeout=1800,
    )
    print("status", resp.status_code)
    data = resp.json()
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
