---
sidebar_position: 2
---

# GET /account/pricing

Returns current credit rates (in milli-USD) and charge limits.

## Request

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

## Response

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

## Fields

| Field | Type | Description |
|-------|------|-------------|
| `currency` | string | Always `"USD"` |
| `charge_limits.min_amount` | int | Minimum credit purchase amount in USD ($5) |
| `charge_limits.max_amount` | int | Maximum credit purchase amount in USD ($500) |
| `rates.basic_page_milli_usd` | int | Cost per page for basic model (1 md = $0.001) |
| `rates.premium_page_milli_usd` | int | Cost per page for premium model (5 md = $0.005) |
| `rates.premium_audio_sec_milli_usd` | int | Cost per second of audio (1 md = $0.001) |
| `rates.premium_video_sec_milli_usd` | int | Cost per second of video (5 md = $0.005) |
| `rates.docling_refinement_page_milli_usd` | int | Cost per Docling refinement page (3 md = $0.003) |

:::info
All rates are in **milli-USD** (1,000 md = $1.00 USD). The basic model includes 100 free pages per day.
:::
