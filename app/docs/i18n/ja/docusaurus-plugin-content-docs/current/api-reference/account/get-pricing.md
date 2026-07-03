---
sidebar_position: 2
---

# GET /account/pricing

利用可能な料金構造と単位あたりのコストを返します。すべての金額はmilli-USD単位です。

## リクエスト

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

## レスポンス

```json
{
  "currency": "USD",
  "charge_limits": {
    "min_amount": 5,
    "max_amount": 500
  },
  "rates": {
    "basic_page_milli_usd": 1,
    "premium_page_milli_usd": 5,
    "premium_audio_sec_milli_usd": 1,
    "premium_video_sec_milli_usd": 5,
    "docling_refinement_page_milli_usd": 3
  }
}
```

## フィールド

| フィールド | タイプ | 説明 |
|-------|------|-------------|
| `currency` | string | 通貨単位（常に`USD`） |
| `charge_limits.min_amount` | int | 最小クレジット購入金額（USD） |
| `charge_limits.max_amount` | int | 最大クレジット購入金額（USD） |
| `rates.basic_page_milli_usd` | int | 基本モデルページあたりコスト（milli-USD） |
| `rates.premium_page_milli_usd` | int | プレミアムモデルページあたりコスト（milli-USD） |
| `rates.premium_audio_sec_milli_usd` | int | 音声秒あたりコスト（milli-USD） |
| `rates.premium_video_sec_milli_usd` | int | 動画秒あたりコスト（milli-USD） |
| `rates.docling_refinement_page_milli_usd` | int | Docling洗練ページあたりコスト（milli-USD） |
