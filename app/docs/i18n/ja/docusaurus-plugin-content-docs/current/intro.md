---
sidebar_position: 1
slug: /
---

# はじめに

Chunguは、PDFやメディアファイルを構造化された表に変換するサービスです。PDF、画像、音声、動画をアップロードすると、CSV、Markdown、XLSX形式の構造化された表が返されます。

## Chungu APIでできること

- PDF文書、スキャン画像、スクリーンショットから**表抽出**
- 音声録音と動画ファイルの**文字起こし・構造化**
- 結果をCSV、Markdown、XLSX、DOCX、PPTXに**変換**
- AIベースのパイプラインで文書処理を**自動化**

## 仕組み

```mermaid
flowchart LR
    A[ファイルアップロード] --> B[コストプレビュー]
    B --> C[ジョブ確認]
    C --> D[処理中]
    D --> E[ステータスポーリング]
    E --> F[結果ダウンロード]
```

1. **アップロード** — `POST /api/v1/jobs/upload`でファイルをアップロードし、コストプレビューを取得します（ポイント消費なし）
2. **確認** — `POST /api/v1/jobs/{job_id}/confirm`でジョブを確認します。ポイントが差し引かれ、処理が開始されます
3. **ポーリング** — `GET /api/v1/jobs/{job_id}`で`status`が`done`または`error`になるまで確認します
4. **ダウンロード** — `GET /api/v1/jobs/{job_id}/download?type=csv|md|xlsx`で結果をダウンロードします

## 開始方法

- Chungu初めてですか？[クイックスタート](./quickstart)ガイドをお読みください
- APIキーが必要ですか？[開発者ポータル](../../developer)にアクセスしてください
- AIにAPIを自動呼び出させたいですか？[AIプロンプト](./ai-prompts/full-pipeline-prompt)を確認してください
