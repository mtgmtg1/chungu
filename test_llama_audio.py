#!/usr/bin/env python3
"""llama-server 오디오 테스트 (Gemma-4 12B GGUF Q4_K_M)."""
import base64
import json
import wave
from pathlib import Path

import requests


def make_wav(path: str, duration: int = 3) -> None:
    """테스트용 WAV 파일을 생성한다."""
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        frames = duration * 16000
        w.writeframes(b"\x00\x00" * frames)


def main() -> None:
    wav_path = Path("/tmp/test_audio.wav")
    make_wav(str(wav_path))

    b64 = base64.b64encode(wav_path.read_bytes()).decode()
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
                        "text": "이 오디오를 시간, 발화자, 대사로 구성된 마크다운 표로 대본화해주세요.",
                    },
                    {"type": "input_audio", "input_audio": {"data": b64}},
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
