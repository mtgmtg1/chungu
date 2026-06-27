---
sidebar_position: 3
---

# GET /account/usage

최근 N일간의 일일 집계 API 사용량을 반환합니다.

## 쿼리 매개변수

| 매개변수 | 타입 | 기본값 | 범위 |
|-----------|------|---------|-------|
| `days` | int | 30 | 1–90 |

## 요청

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/usage?days=7"
```

## 응답

```json
[
  { "day": "2026-06-20", "requests": 15, "points_spent": 450 },
  { "day": "2026-06-21", "requests": 8, "points_spent": 240 },
  { "day": "2026-06-22", "requests": 0, "points_spent": 0 }
]
```
