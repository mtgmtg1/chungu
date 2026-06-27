---
sidebar_position: 3
---

# 인증

모든 API 요청에는 API 키가 필요합니다. `X-API-Key` 헤더 또는 `Authorization: Bearer` 헤더로 전달할 수 있습니다.

## X-API-Key 헤더 사용

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## Authorization Bearer 사용

```bash
curl -H "Authorization: Bearer chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## API 키 생성

1. Chungu 웹 앱에 로그인합니다
2. **개발자 포털**(`/developer`)로 이동합니다
3. **키 생성**을 클릭합니다
4. 이름을 입력합니다 (예: "production", "staging")
5. 전체 키 값을 복사합니다 — **한 번만 표시됩니다**

API를 통해서도 키를 생성할 수 있습니다:

```bash
curl -X POST https://your-domain.com/api/v1/keys \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "production", "scopes": ["jobs:read", "jobs:write"]}'
```

:::caution
API 키를 안전하게 보관하세요. 소스 제어에 커밋하거나 클라이언트 사이드 코드에 노출하지 마세요.
:::

## API 키 스코프

| 스코프 | 설명 |
|-------|-------------|
| `jobs:read` | 작업 상태 조회 및 목록 |
| `jobs:write` | 작업 업로드, 확인, 변환 |

## 요청 제한

- **기본**: API 키당 분당 60 요청
- **동시 작업**: 계정당 최대 5개 (관리자 설정 가능)
- **일일 포인트 할당량**: 키별 선택 사항

초과 시 API는 `429 Too Many Requests`와 `Retry-After` 헤더를 반환합니다.

## API 키 관리

- [키 목록](./api-reference/api-keys/list-keys)
- [키 삭제](./api-reference/api-keys/delete-key)
- [키 로테이션](./api-reference/api-keys/rotate-key)
- [키 사용량 조회](./api-reference/api-keys/get-key-usage)
