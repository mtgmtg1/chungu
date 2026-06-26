#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
from pathlib import Path

image_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBEQCEAwEPwAB//9k="

payload = {
    "model": "cyankiwi/gemma-4-26B-A4B-it-AWQ-4bit",
    "messages": [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "describe this image"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
            ],
        }
    ],
    "max_tokens": 100,
}

Path("/tmp/vllm_debug.txt").write_text("script started\n")
print("starting vllm test")
for port in (18080,):
    url = f"http://127.0.0.1:{port}/v1/chat/completions"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            d = json.loads(resp.read().decode())
        choice = d["choices"][0]
        print(f"{port}: content={choice['message'].get('content')!r} reason={choice.get('finish_reason')}")
    except Exception as e:
        print(f"{port}: ERROR {e}")
