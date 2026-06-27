---
sidebar_position: 1
---

# 작업 수명 주기

모든 Chungu 작업은 업로드부터 다운로드까지 명확한 수명 주기를 따릅니다.

## 상태

| 상태 | 설명 |
|--------|-------------|
| `pending` | 파일이 업로드되었으나 확인 대기 중 |
| `queued` | 확인됨, 워커가 처리를 대기 중 |
| `processing` | 워커가 파일을 활발히 처리 중 |
| `done` | 처리 완료, 결과 다운로드 가능 |
| `error` | 처리 실패, `error_log` 확인 |
| `cancelled` | 완료 전에 취소됨 |

## 흐름

```
업로드 → pending → 확인 → queued → processing → done
                                              ↘ error
```

1. **업로드** (`POST /jobs/upload`) — `pending` 상태로 작업 생성, 비용 미리보기 반환
2. **확인** (`POST /jobs/{id}/confirm`) — 포인트 차감, `queued`로 전환, Celery 워커에 전달
3. **처리** — 워커가 페이지/파일 처리, 실시간으로 `done_pages` / `done_files` 업데이트
4. **완료** — 결과가 Supabase Storage에 저장, 다운로드 준비 완료
5. **다운로드** (`GET /jobs/{id}/download`) — 1시간 유효한 서명된 URL 반환

## 폴링 전략

`GET /jobs/{id}`를 3~5초 간격으로 폴링합니다. 응답에 `done_pages`와 `total_pages`가 포함되어 있어 진행률을 표시할 수 있습니다.

```python
import time

while True:
    job = get_job(job_id)
    if job["status"] in ("done", "error"):
        break
    print(f"진행률: {job['done_pages']}/{job['total_pages']}")
    time.sleep(3)
```

## 오류 처리

`status`가 `error`인 경우 `error_log` 필드에 상세 내용이 포함됩니다. 일반적인 원인:

- 지원되지 않는 파일 형식
- 손상된 PDF 또는 미디어 파일
- LLM 추론 시간 초과
- 포인트 부족 (확인 단계에서 감지)
