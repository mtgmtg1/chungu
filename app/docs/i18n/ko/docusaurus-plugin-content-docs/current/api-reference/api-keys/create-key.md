---
sidebar_position: 1
---

# POST /keys

새 API 키를 생성합니다. 전체 키 값은 이 응답에서만 반환됩니다.

## 요청

:::note
이 엔드포인트는 API 키가 아닌 JWT 인증(로그인 토큰)을 사용합니다.
:::

```bash
curl -X POST https://your-domain.com/api/v1/keys \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "production",
    "scopes": ["jobs:read", "jobs:write"],
    "rate_limit_rpm": 60
  }'
```

## 본문

| 필드 | 타입 | 기본값 | 설명 |
|-------|------|---------|-------------|
| `name` | string | `""` | 표시 이름 |
| `scopes` | string[] | `["jobs:read", "jobs:write"]` | 키 권한 |
| `rate_limit_rpm` | int | 60 | 분당 요청 제한 |

## 응답

```json
{
  "id": "key-abc123",
  "name": "production",
  "prefix": "chu_live",
  "key": "chu_live_xxxxxxxxxxxxxxxxxxxxxxxx",
  "scopes": ["jobs:read", "jobs:write"],
  "rate_limit_rpm": 60,
  "daily_quota": null,
  "is_active": true,
  "created_at": "2026-06-27T12:00:00"
}
```

:::warning
`key` 필드는 한 번만 표시됩니다. 안전하게 보관하세요 — 나중에 다시 조회할 수 없습니다.
:::
