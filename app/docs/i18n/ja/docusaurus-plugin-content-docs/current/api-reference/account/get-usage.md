---
sidebar_position: 3
---

# GET /account/usage

過去N日間の日次集計API使用量を返します。

:::note
このエンドポイントはAPIキー以外にウェブアプリログインのJWTセッショントークンもサポートしています。
:::

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
  { "day": "2026-07-13", "requests": 15, "points_spent": 750 },
  { "day": "2026-07-14", "requests": 8, "points_spent": 400 },
  { "day": "2026-07-15", "requests": 0, "points_spent": 0 }
]
```
