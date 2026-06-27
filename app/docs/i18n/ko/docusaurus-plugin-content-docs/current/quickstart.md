---
sidebar_position: 2
---

# 퀵 스타트

5분 만에 첫 API 호출을 만들어보세요.

## 사전 준비

- Chungu 계정 (웹 앱에서 가입)
- API 키 ([개발자 포털](../../developer)에서 생성)
- `curl` 또는 HTTP 클라이언트

## 1단계: API 키 받기

1. Chungu 웹 앱에 로그인합니다
2. **개발자 포털**(`/developer`)로 이동합니다
3. **키 생성**을 클릭합니다
4. 전체 키를 복사합니다 — 한 번만 표시됩니다

## 2단계: 계정 확인

키가 작동하는지 확인하고 포인트 잔액을 확인합니다:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

**응답:**
```json
{
  "user_id": "uuid",
  "email": "user@example.com",
  "points_balance": 10000,
  "today_usage": { "points_spent": 0, "requests": 0 }
}
```

## 3단계: 파일 업로드

PDF를 업로드하고 비용 미리보기를 받습니다 (아직 포인트가 차감되지 않습니다):

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision"
```

**응답:**
```json
{
  "job_id": "job-abc123",
  "status": "pending",
  "file_type": "pdf",
  "total_pages": 10,
  "cost": { "pages": 10, "points": 30, "krw": 30, "usd": "0.02" },
  "balance": 10000
}
```

## 4단계: 작업 확인

확인하면 포인트가 차감되고 처리가 시작됩니다:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/confirm \
  -H "X-API-Key: chu_live_xxxxxxxx"
```

**응답:**
```json
{
  "job_id": "job-abc123",
  "status": "queued",
  "remaining_points": 9970
}
```

## 5단계: 완료 폴링

상태가 `done`이 될 때까지 확인합니다:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/jobs/job-abc123
```

**응답 (완료 시):**
```json
{
  "job_id": "job-abc123",
  "status": "done",
  "total_pages": 10,
  "done_pages": 10,
  "cost_points": 30,
  "downloadable": true
}
```

## 6단계: 결과 다운로드

결과 파일을 다운로드할 수 있는 서명된 URL을 받습니다:

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx"
```

**응답:**
```json
{
  "download_url": "https://supabase-storage.example.com/results/job-abc123/result.xlsx?token=..."
}
```

## Python 예제

```python
import requests

API_KEY = "chu_live_xxxxxxxx"
BASE = "https://your-domain.com/api/v1"
HEADERS = {"X-API-Key": API_KEY}

# 업로드
with open("document.pdf", "rb") as f:
    resp = requests.post(f"{BASE}/jobs/upload", headers=HEADERS,
                         files={"files": f}, data={"pipeline": "vision"})
job_id = resp.json()["job_id"]

# 확인
requests.post(f"{BASE}/jobs/{job_id}/confirm", headers=HEADERS)

# 폴링
import time
while True:
    status = requests.get(f"{BASE}/jobs/{job_id}", headers=HEADERS).json()
    if status["status"] in ("done", "error"):
        break
    time.sleep(5)

# 다운로드
url = requests.get(f"{BASE}/jobs/{job_id}/download?type=csv",
                   headers=HEADERS).json()["download_url"]
print(f"다운로드: {url}")
```

## 다음 단계

- [인증](./authentication) — API 키 관리 세부 정보
- [핵심 개념](./core-concepts/job-lifecycle) — 작업 수명 주기 이해
- [AI 프롬프트](./ai-prompts/full-pipeline-prompt) — AI가 API를 자동으로 호출하게 하기
