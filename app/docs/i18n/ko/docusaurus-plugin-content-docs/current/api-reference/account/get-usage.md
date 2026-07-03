---
sidebar_position: 3
---

# GET /account/usage

최근 N일간의 일일 집계 API 사용량을 반환합니다.

:::note
이 엔드포인트는 API 키 외에도 웹 앱 로그인의 JWT 세션 토큰을 지원합니다.
:::

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
  { "day": "2026-07-13", "requests": 15, "points_spent": 750 },
  { "day": "2026-07-14", "requests": 8, "points_spent": 400 },
  { "day": "2026-07-15", "requests": 0, "points_spent": 0 }
]
```
