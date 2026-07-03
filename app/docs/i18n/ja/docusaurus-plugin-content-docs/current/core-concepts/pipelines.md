---
sidebar_position: 4
---

# モデルとパイプライン

PROOFは入力タイプ、精度要件、予算に応じて2つの処理モデルを提供します。

## 基本モデル (`ocr_model=basic`)

基本モデルはテキストレイヤーのあるPDFにDoclingを使用し、スキャン文書や画像にTesseract OCRを使用します。コスト効率が高く高速です。

- **適した用途**: テキストを含むクリーンなデジタルPDF
- **速度**: 高速 — LLM呼び出しなしのテキスト抽出
- **コスト**: ページあたり$0.001（1 milli-USD）、**1日100ページまで無料**
- **制限**: 音声/動画非対応、複雑なレイアウトで精度が低い

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=basic"
```

## プレミアムモデル (`ocr_model=premium`)

プレミアムモデルはすべてのページにGemma 4 AI（26B）ビジョンモデルを使用し、複雑な文書、スキャン画像、手書き、回転されたページ、表で優れた精度を提供します。

- **適した用途**: スキャン文書、手書き、複雑な表、画像、音声/動画
- **速度**: 中程度 — ページあたり1回のLLM呼び出し
- **コスト**: ページあたり$0.005（5 milli-USD）、無料枠なし
- **機能**: 音声（$0.001/秒）、動画（$0.005/秒）、Docling洗練オプション

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium"
```

## OCRエンジン選択

プレミアムモデルの場合、テキスト抽出に使用するOCRエンジンを指定できます:

| エンジン | フラグ | 備考 |
|--------|------|-------|
| `easyocr` | デフォルト | 速度と精度のバランス |
| `tesseract` | `ocr_engine=tesseract` | 高速で広くサポート |
| `rapidocr` | `ocr_engine=rapidocr` | CJKテキストに最適化 |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "ocr_model=premium" \
  -F "ocr_engine=rapidocr"
```

## モデル選択

| シナリオ | 推奨モデル |
|----------|-------------------|
| テキストレイヤーのあるクリーンなデジタルPDF | `basic` |
| スキャン文書 | `premium` |
| 手書き | `premium` |
| 表を含む画像 | `premium` |
| 音声/動画 | `premium`（必須） |
| 予算重視、大容量 | `basic`（1日100ページまで無料） |
