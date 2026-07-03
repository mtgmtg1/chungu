---
sidebar_position: 4
---

# 요금

PROOF는 선불 크레딧 시스템을 사용합니다. 크레딧은 **milli-USD** 단위로 측정됩니다 (1,000 milli-USD = $1.00 USD). 입력 유형, 볼륨, 선택한 모델에 따라 크레딧이 차감됩니다.

## 크레딧 비용

| 입력 유형 | 기본 모델 | 고급 모델 |
|------------|-------------|---------------|
| PDF 페이지 | $0.001 (1 md) | $0.005 (5 md) |
| 이미지 | $0.001 (1 md) | $0.005 (5 md) |
| 오디오 (초당) | — | $0.001 (1 md) |
| 비디오 (초당) | — | $0.005 (5 md) |
| Docling 정제 (페이지당) | — | $0.003 (3 md) |

:::info
**기본 모델**: 하루 100페이지 무료. 무료 한도 초과 후 $0.001/페이지 과금.
**고급 모델**: 무료 한도 없음. 모든 페이지 $0.005/페이지 과금.
:::

## XLSX 변환

| 형식 | 비용 |
|--------|------|
| XLSX Basic | 단위당 $0.001 (페이지 또는 파일), 첫 변환에만 적용 |
| XLSX Advanced | 단위당 $0.003 (페이지 또는 파일), 첫 변환에만 적용 |
| DOCX | 무료 |
| PPTX | 무료 |

동일한 형식의 후속 다운로드는 무료입니다.

## 현재 요금 확인

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

**응답:**
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

## 크레딧 구매

PROOF 웹 앱의 [결제 페이지](pathname:///payment)에서 **Paddle**을 통해 크레딧을 구매할 수 있습니다. $5~$500 USD 사이의 원하는 금액을 선택할 수 있으며, 첫 결제 후 자동 충전 설정도 가능합니다.

## 사용량 추적

- [오늘 사용량](./api-reference/account/get-account) — 계정 응답의 `today_usage` 확인
- [일일 사용량 기록](./api-reference/account/get-usage) — 일별 집계
- [거래 내역](./api-reference/account/get-transactions) — 크레딧 충전/사용 로그
- [결제 내역](./api-reference/account/get-payments) — 결제 기록
