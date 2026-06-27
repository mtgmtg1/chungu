---
sidebar_position: 7
---

# SDKとツール

## 公式SDK（予定）

| 言語 | 状態 | リポジトリ |
|----------|--------|------------|
| Python | 予定 | — |
| JavaScript/TypeScript | 予定 | — |
| Go | 予定 | — |

## コミュニティツール

- **n8nノード** — 予定。Chunguをn8nワークフローに統合できます。
- **Zapierアプリ** — 予定。

## OpenAPI / Swagger

完全なOpenAPI仕様は以下で確認できます:

```
/api/v1/docs
```

`openapi-generator`などのツールを使用して、あらゆる言語のクライアントを生成できます:

```bash
openapi-generator-cli generate \
  -i https://your-domain.com/api/v1/openapi.json \
  -g python \
  -o chungu-python-client
```

## APIキー管理

グラフィカルインターフェースはウェブアプリの[開発者ポータル](../../developer)を使用するか、プログラムで[APIキーエンドポイント](../api-reference/api-keys/create-key)を使用してください。
