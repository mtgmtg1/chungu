---
sidebar_position: 6
---

# 오류 처리

Chungu API는 표준 HTTP 상태 코드를 사용합니다. 오류 응답에는 사람이 읽을 수 있는 메시지가 포함된 `detail` 필드가 있습니다.

## 오류 코드

| 상태 | 의미 | 조치 |
|--------|---------|--------|
| 400 | 잘못된 요청 — 잘못된 파일 형식, 누락된 필드 | 요청 형식 확인 |
| 401 | 잘못되거나 누락된 API 키 | API 키 확인 |
| 402 | 포인트 부족 | `/payment`에서 포인트 추가 구매 |
| 403 | 금지됨 — 스코프 누락 또는 개발자가 아님 | 키 스코프 확인 |
| 404 | 작업 또는 리소스를 찾을 수 없음 | 작업 ID 확인 |
| 413 | 파일이 너무 크거나 페이지가 너무 많음 | 파일 크기 줄이기 또는 PDF 분할 |
| 429 | 요청 제한 초과 | `Retry-After` 헤더 후 대기 후 재시도 |
| 502 | 다운스트림 처리 오류 | 지수 백오프로 재시도 |

## 오류 응답 형식

```json
{
  "detail": "포인트가 부족합니다"
}
```

:::note
오류 메시지는 한국어일 수 있습니다. 프로그래밍 방식 처리에는 HTTP 상태 코드를 사용하세요.
:::

## 재시도 전략

`429` 및 `502` 오류의 경우 지수 백오프를 사용하세요:

```python
import time
import requests

def retry_request(url, max_retries=3):
    for attempt in range(max_retries):
        resp = requests.get(url, headers=HEADERS)
        if resp.status_code == 429:
            wait = int(resp.headers.get("Retry-After", 5))
            time.sleep(wait)
            continue
        if resp.status_code == 502 and attempt < max_retries - 1:
            time.sleep(2 ** attempt)
            continue
        return resp
    return resp
```

## 작업 오류

작업이 실패하면 `GET /jobs/{id}`는 다음을 반환합니다:

```json
{
  "job_id": "job-abc123",
  "status": "error",
  "error_log": "LLM inference timeout after 120s"
}
```

일반적인 작업 오류:
- **LLM 추론 시간 초과** — 모델이 너무 오래 걸림, 재시도 또는 페이지 수 감소
- **지원되지 않는 파일 형식** — [지원 형식](../file-formats) 확인
- **Storage 업로드 실패** — 일시적 인프라 오류, 재시도
