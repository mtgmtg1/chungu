---
sidebar_position: 1
---

# GET /account

계정 정보, 포인트 잔액, 오늘 사용량, 현재 API 키 메타데이터를 반환합니다.

## 요청

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## 응답

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "points_balance": 10000,
  "api_key": {
    "id": "key-id",
    "name": "production",
    "prefix": "chu_live",
    "scopes": ["jobs:read", "jobs:write"],
    "rate_limit_rpm": 60,
    "daily_quota": null,
    "daily_spent_points": 150
  },
  "today_usage": {
    "points_spent": 150,
    "requests": 12
  }
}
```

## 필드

| 필드 | 타입 | 설명 |
|-------|------|-------------|
| `user_id` | string (uuid) | 사용자 식별자 |
| `email` | string | 사용자 이메일 |
| `points_balance` | int | 현재 포인트 잔액 |
| `api_key` | object | 현재 API 키 메타데이터 |
| `api_key.scopes` | string[] | 키 권한 |
| `api_key.rate_limit_rpm` | int | 분당 요청 제한 |
| `api_key.daily_quota` | int\|null | 일일 포인트 한도 (null = 무제한) |
| `api_key.daily_spent_points` | int | 오늘 사용한 포인트 |
| `today_usage.points_spent` | int | 오늘 사용한 포인트 |
| `today_usage.requests` | int | 오늘 API 호출 수 |
