#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import base64
from pathlib import Path

video_path = Path("/tmp/test.mp4")
video_b64 = base64.b64encode(video_path.read_bytes()).decode()

payload = {
    "model": "cyankiwi/gemma-4-12B-it-AWQ-INT4",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this video"},
                {"type": "video_url", "video_url": {"url": f"data:video/mp4;base64,{video_b64}"}},
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
        with urllib.request.urlopen(req, timeout=120) as resp:
            d = json.loads(resp.read().decode())
        choice = d["choices"][0]
        print(f"{port}: content={choice['message'].get('content')!r} reason={choice.get('finish_reason')}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"{port}: HTTP ERROR {e.code} {e.reason} body={body[:500]}")
    except Exception as e:
        print(f"{port}: ERROR {e}")
