---
sidebar_position: 4
---

# 料金

PROOFはプリペイドクレジットシステムを使用します。クレジットはmilli-USD単位（1 USD = 1000 milli-USD）で、入力タイプとモデルに基づいて差し引かれます。

## モデル別コスト

### 基本モデル (`ocr_model=basic`)

| 入力タイプ | コスト |
|------------|------|
| PDFページ | $0.001 (1 milli-USD) |
| 画像 | $0.001 (1 milli-USD) |

- **無料枠**: 1日100ページまで無料
- 音声/動画は非対応

### プレミアムモデル (`ocr_model=premium`)

| 入力タイプ | コスト |
|------------|------|
| PDFページ | $0.005 (5 milli-USD) |
| 画像 | $0.005 (5 milli-USD) |
| 音声（秒あたり） | $0.001 (1 milli-USD) |
| 動画（秒あたり） | $0.005 (5 milli-USD) |
| Docling洗練（ページあたり） | $0.003 (3 milli-USD) |

## XLSX変換

完了したジョブをXLSXに変換する場合、追加コストが発生します（最初の変換のみ、以降のダウンロードは無料）:

| 形式 | コスト |
|------|------|
| `xlsx_basic` | $0.001/単位 (1 milli-USD) |
| `xlsx_advanced` | $0.003/単位 (3 milli-USD) |

## 現在の料金を確認

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

**レスポンス:**
```json
{
  "currency": "USD",
  "charge_limits": { "min_amount": 5, "max_amount": 500 },
  "rates": {
    "basic_page_milli_usd": 1,
    "premium_page_milli_usd": 5,
    "premium_audio_sec_milli_usd": 1,
    "premium_video_sec_milli_usd": 5,
    "docling_refinement_page_milli_usd": 3
  }
}
```

## クレジット購入

PROOFウェブアプリの[支払いページ](pathname:///payment)で**Paddle**経由でクレジットを購入できます。$5〜$500 USDの範囲で任意の金額を購入可能です。

## 使用量トラッキング

- [今日の使用量](./api-reference/account/get-account) — アカウントレスポンスの`today_usage`を確認
- [日次使用量履歴](./api-reference/account/get-usage) — 日別集計
- [取引履歴](./api-reference/account/get-transactions) — クレジットチャージ/消費ログ
- [支払い履歴](./api-reference/account/get-payments) — 支払い記録
