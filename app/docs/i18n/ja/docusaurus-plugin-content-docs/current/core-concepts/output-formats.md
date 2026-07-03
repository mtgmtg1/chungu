---
sidebar_position: 3
---

# 出力形式

PROOFは複数の形式で結果を提供できます。主な出力は常にMarkdownで、必要に応じて他の形式に変換されます。

## 利用可能な形式

| 形式 | エンドポイントパラメータ | 備考 |
|--------|-------------------|-------|
| Markdown | `type=md` | デフォルト出力、元の構造化表 |
| CSV Basic | `type=csv_basic` | カンマ区切り値 |
| XLSX Basic | `type=xlsx_basic` | Excelスプレッドシート（最初の変換に追加クレジット消費） |
| XLSX Advanced | `type=xlsx_advanced` | フォーマット付き高度Excel（最初の変換に追加クレジット消費） |
| DOCX | `type=docx` | Word文書（`/convert`エンドポイント使用） |
| PPTX | `type=pptx` | PowerPoint（`/convert`エンドポイント使用） |

## ダウンロード vs 変換

- **ダウンロード** (`GET /jobs/{id}/download?type=`) — 既に生成された結果の署名付きURL返却
- **変換** (`POST /jobs/{id}/convert`) — Markdown結果から新しい形式を生成

### どちらを使うべきか

- `md`と`csv_basic`には**ダウンロード**を使用（ジョブ完了後に常に利用可能）
- `xlsx_basic`には**ダウンロード**を使用（初回リクエスト時に自動変換、その後キャッシュ）
- `xlsx_advanced`には**ダウンロード**を使用（初回リクエスト時に自動変換、その後キャッシュ）
- `docx`と`pptx`には**変換**を使用（ダウンロードエンドポイントでは利用不可）

## 例: XLSX Basicダウンロード

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  "https://your-domain.com/api/v1/jobs/job-abc123/download?type=xlsx_basic"
```

## 例: DOCXに変換

```bash
curl -X POST https://your-domain.com/api/v1/jobs/job-abc123/convert \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -H "Content-Type: application/json" \
  -d '{"format": "docx"}'
```

## 署名付きURLの有効期限

ダウンロードURLは**1時間**有効です。期限切れの場合は新しいURLをリクエストしてください。
