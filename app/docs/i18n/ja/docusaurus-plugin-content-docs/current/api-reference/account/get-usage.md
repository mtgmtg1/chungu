---
sidebar_position: 3
---

# GET /account/usage

過去N日間の日次集計API使用量を返します。

## クエリパラメータ

| パラメータ | タイプ | デフォルト | 範囲 |
|-----------|------|---------|-------|
| `days` | int | 30 | 1–90 |

## リクエスト

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/usage?days=7"
```

## レスポンス

```json
[
  { "day": "2026-06-20", "requests": 15, "points_spent": 450 },
  { "day": "2026-06-21", "requests": 8, "points_spent": 240 },
  { "day": "2026-06-22", "requests": 0, "points_spent": 0 }
]
```
