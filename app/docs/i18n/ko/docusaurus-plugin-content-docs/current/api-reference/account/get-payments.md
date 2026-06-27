---
sidebar_position: 5
---

# GET /account/payments

결제 내역을 반환합니다.

## 쿼리 매개변수

| 매개변수 | 타입 | 기본값 | 범위 |
|-----------|------|---------|-------|
| `limit` | int | 100 | 1–500 |

## 요청

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/payments"
```

## 응답

```json
[
  {
    "id": "pay-001",
    "provider": "toss",
    "currency": "KRW",
    "amount": "33000",
    "points_added": 10000,
    "status": "done",
    "external_id": "toss_payment_abc123",
    "paid_at": "2026-06-26T15:00:00",
    "created_at": "2026-06-26T14:59:00"
  }
]
```
