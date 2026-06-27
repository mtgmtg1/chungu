---
sidebar_position: 7
---

# SDK 및 도구

## 공식 SDK (예정)

| 언어 | 상태 | 저장소 |
|----------|--------|------------|
| Python | 예정 | — |
| JavaScript/TypeScript | 예정 | — |
| Go | 예정 | — |

## 커뮤니티 도구

- **n8n 노드** — 예정. Chungu를 n8n 워크플로우에 통합할 수 있습니다.
- **Zapier 앱** — 예정.

## OpenAPI / Swagger

전체 OpenAPI 사양은 다음에서 확인할 수 있습니다:

```
/api/v1/docs
```

`openapi-generator` 등의 도구를 사용하여 모든 언어의 클라이언트를 생성할 수 있습니다:

```bash
openapi-generator-cli generate \
  -i https://your-domain.com/api/v1/openapi.json \
  -g python \
  -o chungu-python-client
```

## API 키 관리

그래픽 인터페이스는 웹 앱의 [개발자 포털](../../developer)을 사용하거나, 프로그래밍 방식으로 [API 키 엔드포인트](../api-reference/api-keys/create-key)를 사용하세요.
