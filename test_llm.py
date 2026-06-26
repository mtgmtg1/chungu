#!/usr/bin/env python3
import base64
from pathlib import Path
from backend.core import ocr_client
from backend.core.prompts import build_media_prompt

png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
data = base64.b64decode(png_b64)
path = Path("/tmp/test.png")
path.write_bytes(data)
print("image size", path.stat().st_size)
encoded = ocr_client.encode_image(path)
print("encoded size", len(encoded))

prompt = build_media_prompt(["항목", "금액"], "")
print("prompt", prompt[:100])

endpoint = "http://192.168.1.69:18080/v1"
model = "cyankiwi/gemma-4-12B-it-qat-AWQ-INT4"
try:
    content, reason = ocr_client.call_media(prompt, endpoint, model, image_paths=[path], max_tokens=10000)
    print("content", content[:500])
    print("finish_reason", reason)
except Exception as e:
    print("ERROR", type(e).__name__, str(e)[:500])
