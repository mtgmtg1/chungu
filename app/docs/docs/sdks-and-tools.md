---
sidebar_position: 7
---

# SDKs and Tools

## Official SDKs (planned)

| Language | Status | Repository |
|----------|--------|------------|
| Python | Planned | — |
| JavaScript/TypeScript | Planned | — |
| Go | Planned | — |

## Community tools

- **n8n node** — Planned. Will allow integrating Chungu into n8n workflows.
- **Zapier app** — Planned.

## OpenAPI / Swagger

The full OpenAPI specification is available at:

```
/api/v1/docs
```

You can use this to generate clients in any language using tools like `openapi-generator`:

```bash
openapi-generator-cli generate \
  -i https://your-domain.com/api/v1/openapi.json \
  -g python \
  -o chungu-python-client
```

## API key management

Use the [Developer Portal](../../developer) in the web app for a graphical interface, or the [API Keys endpoints](../api-reference/api-keys/create-key) for programmatic access.
