---
sidebar_position: 4
---

# Pricing

PROOF uses a prepaid credit system. Credits are measured in **milli-USD** (1,000 milli-USD = $1.00 USD). Credits are deducted based on the input type, volume, and model selected.

## Credit costs

| Input type | Basic model | Premium model |
|------------|-------------|---------------|
| PDF page | $0.001 (1 md) | $0.005 (5 md) |
| Image | $0.001 (1 md) | $0.005 (5 md) |
| Audio (per second) | — | $0.001 (1 md) |
| Video (per second) | — | $0.005 (5 md) |
| Docling refinement (per page) | — | $0.003 (3 md) |

:::info
**Basic model**: 100 free pages per day. After the free quota, $0.001/page is charged.
**Premium model**: No free quota. All pages are charged at $0.005/page.
:::

## XLSX conversion

| Format | Cost |
|--------|------|
| XLSX Basic | $0.001 per unit (page or file), first conversion only |
| XLSX Advanced | $0.003 per unit (page or file), first conversion only |
| DOCX | Free |
| PPTX | Free |

Subsequent downloads of the same format are free.

## Checking current rates

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

**Response:**
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

## Purchasing credits

Visit the [Payment page](pathname:///payment) in the PROOF web app to purchase credits via **Paddle**. You can choose any amount between $5 and $500 USD. Auto-recharge is also available after your first payment.

## Usage tracking

- [Today's usage](./api-reference/account/get-account) — see `today_usage` in the account response
- [Daily usage history](./api-reference/account/get-usage) — aggregated by day
- [Transaction history](./api-reference/account/get-transactions) — credit charge/spend log
- [Payment history](./api-reference/account/get-payments) — payment records
