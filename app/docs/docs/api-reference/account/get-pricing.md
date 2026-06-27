---
sidebar_position: 2
---

# GET /account/pricing

Returns available point packages and per-unit rates.

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

## Response

```json
{
  "packages": [
    {
      "name": "Starter",
      "points": 10000,
      "price_krw": 33000,
      "price_usd": 25
    },
    {
      "name": "Pro",
      "points": 50000,
      "price_krw": 150000,
      "price_usd": 110
    }
  ],
  "rates": {
    "krw_per_page": 3,
    "krw_per_image": 3,
    "krw_per_audio_second": 1,
    "krw_per_video_second": 3,
    "usd_per_point": "0.002"
  }
}
```
