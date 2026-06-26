#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import base64
import struct
import math
import io
import wave


def make_wav_b64() -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        samples = [int(0.1 * 32767 * math.sin(2 * math.pi * 440 * t / 16000)) for t in range(16000)]
        w.writeframes(struct.pack("<" + "h" * len(samples), *samples))
    return base64.b64encode(buf.getvalue()).decode()


audio_b64 = make_wav_b64()

payload = {
    "model": "cyankiwi/gemma-4-12B-it-AWQ-INT4",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this audio"},
                {"type": "audio_url", "audio_url": {"url": f"data:audio/wav;base64,{audio_b64}"}},
            ],
        }
    ],
    "max_tokens": 100,
}

for port in (18080,):
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.loads(resp.read().decode())
        choice = d["choices"][0]
        print(f"{port}: content={choice['message'].get('content')!r} reason={choice.get('finish_reason')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"{port}: HTTP ERROR {e.code} {e.reason} body={body[:500]}")
    except Exception as e:
        print(f"{port}: ERROR {e}")
