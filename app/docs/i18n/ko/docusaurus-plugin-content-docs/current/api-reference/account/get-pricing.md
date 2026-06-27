---
sidebar_position: 2
---

# GET /account/pricing

사용 가능한 포인트 패키지와 단위당 요금을 반환합니다.

## 요청

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

## 응답

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
