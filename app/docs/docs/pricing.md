---
sidebar_position: 4
---

# Pricing

Chungu uses a prepaid point system. Points are deducted based on the input type and volume.

## Point costs

| Input type | Cost |
|------------|------|
| PDF page | 3 points |
| Image | 3 points |
| Audio (per second) | 1 point |
| Video (per second) | 3 points |

## XLSX conversion

Converting a completed job to XLSX costs an additional **3 points per unit** (page or file), but only on the first conversion. Subsequent downloads of the same format are free.

## Checking current rates

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

**Response:**
```json
{
  "packages": [
    { "name": "Starter", "points": 10000, "price_krw": 33000, "price_usd": 25 }
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

## Purchasing points

Visit the [Payment page](../../payment) in the Chungu web app to purchase point packages via Toss (Korea) or Paddle (international).

## Usage tracking

- [Today's usage](./api-reference/account/get-account) — see `today_usage` in the account response
- [Daily usage history](./api-reference/account/get-usage) — aggregated by day
- [Transaction history](./api-reference/account/get-transactions) — point charge/spend log
- [Payment history](./api-reference/account/get-payments) — payment records
