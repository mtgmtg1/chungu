---
sidebar_position: 4
---

# 요금

Chungu는 선불 포인트 시스템을 사용합니다. 포인트는 입력 유형과 볼륨에 따라 차감됩니다.

## 포인트 비용

| 입력 유형 | 비용 |
|------------|------|
| PDF 페이지 | 3 포인트 |
| 이미지 | 3 포인트 |
| 오디오 (초당) | 1 포인트 |
| 비디오 (초당) | 3 포인트 |

## XLSX 변환

완료된 작업을 XLSX로 변환하는 데는 **단위당 3 포인트**가 추가로 소요됩니다 (페이지 또는 파일). 첫 변환에만 적용되며, 동일한 형식의 후속 다운로드는 무료입니다.

## 현재 요금 확인

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

**응답:**
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

## 포인트 구매

Chungu 웹 앱의 [결제 페이지](../../payment)에서 Toss(한국) 또는 Paddle(해외)을 통해 포인트 패키지를 구매할 수 있습니다.

## 사용량 추적

- [오늘 사용량](./api-reference/account/get-account) — 계정 응답의 `today_usage` 확인
- [일일 사용량 기록](./api-reference/account/get-usage) — 일별 집계
- [거래 내역](./api-reference/account/get-transactions) — 포인트 충전/사용 로그
- [결제 내역](./api-reference/account/get-payments) — 결제 기록
