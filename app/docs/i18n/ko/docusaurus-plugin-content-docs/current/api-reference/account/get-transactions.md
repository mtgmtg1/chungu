---
sidebar_position: 4
---

# GET /account/transactions

포인트 충전 및 사용 내역을 반환합니다.

## 쿼리 매개변수

| 매개변수 | 타입 | 기본값 | 범위 |
|-----------|------|---------|-------|
| `limit` | int | 100 | 1–500 |

## 요청

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/account/transactions?limit=20"
```

## 응답

```json
[
  {
    "id": "tx-001",
    "type": "spend",
    "amount": -30,
    "balance_after": 9970,
    "description": "API 작업: document.pdf",
    "created_at": "2026-06-27T10:30:00"
  },
  {
    "id": "tx-002",
    "type": "charge",
    "amount": 10000,
    "balance_after": 10000,
    "description": "Toss 결제: Starter 패키지",
    "created_at": "2026-06-26T15:00:00"
  }
]
```
