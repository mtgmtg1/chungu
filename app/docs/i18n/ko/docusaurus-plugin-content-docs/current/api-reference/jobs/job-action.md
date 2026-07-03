---
sidebar_position: 7
---

# POST /jobs/`{job_id}`/action

실패한 문서 파싱 작업을 재시도하거나 환불합니다. 작업 상태가 `error`이고 `refundable`이 `true`인 경우에만 사용 가능합니다.

## 요청

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/action \
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
| `retry` | 작업 상태를 `queued`로 초기화하고 추가 비용 없이 워커에 재전달 |
| `refund` | 이 작업으로 차감된 모든 크레딧을 잔액에 환불 |

## 응답 (retry)

```json
{
  "job_id": "job-abc123",
  "status": "queued"
}
```

## 응답 (refund)

```json
{
  "refunded": true,
  "points": 50
}
```

:::info
`points`는 환불된 크레딧 금액 (milli-USD)입니다. `50`은 $0.05 USD를 의미합니다.
:::

## 오류

| Status | Meaning |
|--------|---------|
| 400 | 환불/재시도 가능한 상태가 아니거나 잘못된 action |
| 404 | 작업을 찾을 수 없거나 소유자가 아님 |
