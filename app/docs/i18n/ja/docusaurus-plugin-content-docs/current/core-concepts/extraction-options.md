---
sidebar_position: 5
---

# 抽出オプション

Chunguがファイルから表を抽出する方法をカスタマイズしてください。

## カラム

モデルの抽出をガイドするためにカラム名を指定します。省略するとデフォルトカラムが使用されます。

### カンマ区切り

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "columns=日付,勘定科目,摘要,入金額,出金額,残高"
```

### JSON配列

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F 'columns=["date","account","description","debit","credit","balance"]'
```

## プロンプト

モデルの抽出動作をカスタマイズする追加指示を入力します。

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "prompt=金額が1,000,000以上の行のみ抽出してください"
```

一般的なプロンプト例:

- `"複数行セルを単一セルにマージ"`
- `"ヘッダー行を無視してデータ行のみ抽出"`
- `"YYYY-MM-DD日付形式を使用"`
- `"行番号カラムを含める"`

## DPI

PDFページのレンダリング解像度を制御します。DPIが高いほど小さなテキストの精度が向上しますが、処理時間が増加します。

| DPI | ユースケース |
|-----|----------|
| 150 | デフォルト、ほとんどの文書に適切 |
| 300 | 高解像度、小さなフォント |
| 600 | 非常に細かい文字、レシート |

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@document.pdf" \
  -F "dpi=300"
```

## 相対パス（アーカイブ用）

アーカイブをアップロードする際、ディレクトリ構造を維持するために相対パスを指定できます:

```bash
curl -X POST https://your-domain.com/api/v1/jobs/upload \
  -H "X-API-Key: chu_live_xxxxxxxx" \
  -F "files=@archive.zip" \
  -F 'relative_paths=["folder/doc1.pdf","folder/doc2.pdf"]'
```
