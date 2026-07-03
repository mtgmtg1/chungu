---
sidebar_position: 2
---

# GET /account/pricing

사용 가능한 요금 구조와 단위당 비용을 반환합니다. 모든 금액은 milli-USD 단위입니다.

## 요청

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

## 응답

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

## 필드

| 필드 | 타입 | 설명 |
|-------|------|-------------|
| `currency` | string | 통화 단위 (항상 `USD`) |
| `charge_limits.min_amount` | int | 최소 크레딧 구매 금액 (USD) |
| `charge_limits.max_amount` | int | 최대 크레딧 구매 금액 (USD) |
| `rates.basic_page_milli_usd` | int | 기본 모델 페이지당 비용 (milli-USD) |
| `rates.premium_page_milli_usd` | int | 고급 모델 페이지당 비용 (milli-USD) |
| `rates.premium_audio_sec_milli_usd` | int | 오디오 초당 비용 (milli-USD) |
| `rates.premium_video_sec_milli_usd` | int | 비디오 초당 비용 (milli-USD) |
| `rates.docling_refinement_page_milli_usd` | int | Docling 정제 페이지당 비용 (milli-USD) |
