---
sidebar_position: 8
---

# POST /jobs/`{job_id}`/xlsx-advanced-action

실패한 XLSX 고급 변환을 재시도하거나 환불합니다. `xlsx_advanced_status`가 `error`이고 `xlsx_advanced_refundable`이 `true`인 경우에만 사용 가능합니다.

## 요청

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/xlsx-advanced-action \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"action": "retry"}'
```

## Body

| Field | Type | Description |
|-------|------|-------------|
| `action` | string | `retry` or `refund` |

## Actions

| Action | 동작 |
|--------|---------|
| `retry` | XLSX 고급 변환 상태를 `processing`으로 초기화하고 추가 비용 없이 재전달 |
| `refund` | XLSX 고급 변환으로 차감된 크레딧 환불 (단위당 3 milli-USD) |

## 응답 (retry)

```json
{
  "job_id": "task-xyz789",
  "status": "processing"
}
```

## 응답 (refund)

```json
{
  "refunded": true,
  "points": 30
}
```

:::info
`points`는 환불된 크레딧 금액 (milli-USD)입니다. `30`은 $0.03 USD를 의미합니다 (10단위 × 3 md/단위).
:::

## 오류

| Status | Meaning |
|--------|---------|
| 400 | XLSX 고급 변환이 환불/재시도 가능한 상태가 아니거나 잘못된 action |
| 404 | 작업을 찾을 수 없거나 소유자가 아님 |
