---
sidebar_position: 1
---

# GET /account

アカウント情報、ポイント残高、本日の使用量、現在のAPIキーメタデータを返します。

## リクエスト

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## レスポンス

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

## フィールド

| フィールド | タイプ | 説明 |
|-------|------|-------------|
| `user_id` | string (uuid) | ユーザー識別子 |
| `email` | string | ユーザーメール |
| `points_balance` | int | 現在のポイント残高 |
| `api_key` | object | 現在のAPIキーメタデータ |
| `api_key.scopes` | string[] | キー権限 |
| `api_key.rate_limit_rpm` | int | 分あたりリクエスト制限 |
| `api_key.daily_quota` | int\|null | 日次ポイント制限（null = 無制限） |
| `api_key.daily_spent_points` | int | 本日消費したポイント |
| `today_usage.points_spent` | int | 本日消費したポイント |
| `today_usage.requests` | int | 本日のAPI呼び出し数 |
