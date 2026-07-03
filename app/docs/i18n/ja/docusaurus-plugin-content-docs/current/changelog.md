---
sidebar_position: 100
---

# 変更履歴

## 2026-07

- 決済システムをKRWポイントから**USDクレジット（milli-USD）**に移行
- Toss決済連携を削除 — **Paddle**が唯一の決済プロバイダー
- 自由金額クレジット購入（$5〜$500 USD）および自動チャージ対応を追加
- アップロードエンドポイントに`ocr_model`パラメータ（`basic` / `premium`）を追加
- アップロードエンドポイントに`ocr_engine`パラメータ（`tesseract` / `easyocr` / `rapidocr`）を追加
- XLSX出力を`xlsx_basic`と`xlsx_advanced`形式に分離
- ドキュメント解析リトライ/返金のための`POST /jobs/{id}/action`エンドポイントを追加
- XLSX高度変換リトライ/返金のための`POST /jobs/{id}/xlsx-advanced-action`エンドポイントを追加
- 基本モデル: 1日100ページまで無料
- ファイルあたり最大ページ数を10,000に増加
- アカウントエンドポイントがAPIキー以外にセッショントークンもサポート

## 2026-06-27

- PROOF API v1ドキュメントサイト公開
- 音声および動画ファイル処理サポートを追加
- XLSX、DOCX、PPTX変換エンドポイントを追加
- APIキーローテーションエンドポイントを追加

## 2026-01-15

- API v1初期リリース
- エンドポイント: account、keys、jobs（upload、confirm、status、download）
- ポイントベース課金システム
- Visionおよびハイブリッドパイプライン
