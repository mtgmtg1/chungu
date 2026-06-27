---
sidebar_position: 4
---

# パイプライン

Chunguは入力タイプと精度要件に応じて2つの処理パイプラインを提供します。

## Visionパイプライン（デフォルト）

`vision`パイプラインは各PDFページを画像にレンダリングし、ビジョン言語モデル（VLM）に送信して直接表を抽出します。

- **適した用途**: クリーンなPDF、スキャン文書、画像
- **速度**: 高速 — ページあたり1回のモデル呼び出し
- **精度**: 構造化された表に高い

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=vision"
```

## ハイブリッドパイプライン

`hybrid`パイプラインはOCRテキスト抽出とビジョンモデル分析を組み合わせます。まずTesseract OCRでテキストを抽出し、画像とOCRテキストの両方をモデルに送信します。

- **適した用途**: テキストと表が混在する文書、低品質スキャン
- **速度**: 遅い — ページあたりOCR + モデル呼び出し
- **精度**: 複雑なレイアウトのテキスト中心文書に高い

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "pipeline=hybrid"
```

## パイプラインの選択

| シナリオ | 推奨パイプライン |
|----------|---------------------|
| クリーンなデジタルPDF | `vision` |
| スキャン文書 | `vision` |
| テキストありの低品質スキャン | `hybrid` |
| 表を含む画像 | `vision` |
| 音声/動画 | どちらでも（メディアにはパイプラインは無視されます） |
