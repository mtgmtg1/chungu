---
sidebar_position: 3
---

# 認証

すべてのAPIリクエストにはAPIキーが必要です。`X-API-Key`ヘッダーまたは`Authorization: Bearer`ヘッダーで渡すことができます。

## X-API-Keyヘッダーの使用

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## Authorization Bearerの使用

```bash
curl -H "Authorization: Bearer chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account
```

## APIキーの作成

1. Chunguウェブアプリにログインします
2. **開発者ポータル**（`/developer`）に移動します
3. **キー作成**をクリックします
4. 名前を入力します（例: "production"、"staging"）
5. 完全なキー値をコピーします — **一度のみ表示されます**

API経由でもキーを作成できます:

```bash
curl -X POST https://your-domain.com/api/v1/keys \
  -H "Authorization: Bearer <your-jwt-token>" \
  -H "Content-Type: application/json" \
  -d '{"name": "production", "scopes": ["jobs:read", "jobs:write"]}'
```

:::caution
APIキーを安全に保管してください。ソース管理にコミットしたり、クライアントサイドコードに公開しないでください。
:::

## APIキースコープ

| スコープ | 説明 |
|-------|-------------|
| `jobs:read` | ジョブステータスの読み取りと一覧 |
| `jobs:write` | ジョブのアップロード、確認、変換 |

## レート制限

- **デフォルト**: APIキーあたり分間60リクエスト
- **同時ジョブ**: アカウントあたり最大5件（管理者設定可能）
- **日次ポイント割り当て**: キーごとにオプション

超過した場合、APIは`429 Too Many Requests`と`Retry-After`ヘッダーを返します。

## APIキー管理

- [キー一覧](./api-reference/api-keys/list-keys)
- [キー削除](./api-reference/api-keys/delete-key)
- [キーローテーション](./api-reference/api-keys/rotate-key)
- [キー使用量確認](./api-reference/api-keys/get-key-usage)
