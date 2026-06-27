---
sidebar_position: 4
---

# 料金

Chunguはプリペイドポイントシステムを使用します。ポイントは入力タイプとボリュームに基づいて差し引かれます。

## ポイントコスト

| 入力タイプ | コスト |
|------------|------|
| PDFページ | 3ポイント |
| 画像 | 3ポイント |
| 音声（秒あたり） | 1ポイント |
| 動画（秒あたり） | 3ポイント |

## XLSX変換

完了したジョブをXLSXに変換するには、**単位あたり3ポイント**が追加で消費されます（ページまたはファイル）。最初の変換のみ適用され、同じ形式の後続ダウンロードは無料です。

## 現在の料金を確認

```bash
curl -H "X-API-Key: chu_live_xxxxxxxx" \
  https://your-domain.com/api/v1/account/pricing
```

**レスポンス:**
```json
{
  "packages": [
    { "name": "Starter", "points": 10000, "price_krw": 33000, "price_usd": 25 }
  ],
  "rates": {
    "krw_per_page": 3,
    "krw_per_image": 3,
    "krw_per_audio_second": 1,
    "krw_per_video_second": 3,
    "usd_per_point": "0.002"
  }
}
```

## ポイント購入

Chunguウェブアプリの[支払いページ](../../payment)でToss（韓国）またはPaddle（海外）経由でポイントパッケージを購入できます。

## 使用量トラッキング

- [今日の使用量](./api-reference/account/get-account) — アカウントレスポンスの`today_usage`を確認
- [日次使用量履歴](./api-reference/account/get-usage) — 日別集計
- [取引履歴](./api-reference/account/get-transactions) — ポイントチャージ/消費ログ
- [支払い履歴](./api-reference/account/get-payments) — 支払い記録
