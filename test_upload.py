#!/usr/bin/env python3
import base64
import http.client
import io
import json
import time
import urllib.parse
import uuid

BASE_URL = "192.168.1.50:28181"
SUPABASE_URL = "192.168.1.50:28000"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJyb2xlIjoiYW5vbiIsImlzcyI6InN1cGFiYXNlLWNodW5ndSIsImlhdCI6MTc4MjM3NzA0MiwiZXhwIjoyMDk3NzM3MDQyfQ._WSiSZmzrmnmgfKHfEN9FrSnZ_a5PiMiJvyS4hmHmEc"


def _request(method: str, host: str, path: str, headers: dict = None, body: bytes = None, json_data=None):
    if json_data is not None:
        body = json.dumps(json_data).encode()
        headers = {**(headers or {}), "Content-Type": "application/json"}
    headers = headers or {}
    conn = http.client.HTTPConnection(host)
    conn.request(method, path, body=body, headers=headers)
    resp = conn.getresponse()
    data = resp.read()
    conn.close()
    text = data.decode("utf-8", errors="replace")
    if resp.status >= 400:
        raise RuntimeError(f"HTTP {resp.status}: {text[:500]}")
    return resp.status, text


def login(email: str, password: str) -> str:
    path = f"/auth/v1/token?grant_type=password"
    _, text = _request(
        "POST",
        SUPABASE_URL,
        path,
        headers={"apikey": ANON_KEY},
        json_data={"email": email, "password": password},
    )
    return json.loads(text)["access_token"]


def test_upload_image(token: str):
    png_b64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    data = base64.b64decode(png_b64)

    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for name, value in {"pipeline": "vision", "columns": "", "prompt": "", "dpi": "150"}.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        body.write(f"{value}\r\n".encode())
    body.write(f"--{boundary}\r\n".encode())
    body.write(b'Content-Disposition: form-data; name="files"; filename="test.png"\r\n')
    body.write(b"Content-Type: image/png\r\n\r\n")
    body.write(data)
    body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    payload = body.getvalue()

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    status, text = _request("POST", BASE_URL, "/api/jobs/upload", headers=headers, body=payload)
    print("upload status:", status)
    print("upload body:", text[:500])
    return json.loads(text)


def confirm_job(token: str, job_id: str):
    headers = {"Authorization": f"Bearer {token}"}
    status, text = _request("POST", BASE_URL, f"/api/jobs/{job_id}/confirm", headers=headers)
    print("confirm status:", status)
    print("confirm body:", text[:500])
    return json.loads(text)


def poll_job(token: str, job_id: str, max_seconds: int = 60):
    headers = {"Authorization": f"Bearer {token}"}
    for i in range(max_seconds):
        _, text = _request("GET", BASE_URL, f"/api/jobs/{job_id}", headers=headers)
        j = json.loads(text)
        print(f"[{i}s] status={j.get('status')} done_files={j.get('done_files')}/{j.get('total_files')}")
        if j.get("status") in ("completed", "done", "failed"):
            return j
        time.sleep(1)
    return None


if __name__ == "__main__":
    token = login("test@chungu.local", "Test1234!")
    print("token acquired")
    job = test_upload_image(token)
    job_id = job["job_id"]
    print("job_id:", job_id)
    confirm_job(token, job_id)
    result = poll_job(token, job_id)
    print("result:", json.dumps(result, default=str, indent=2)[:1000])
