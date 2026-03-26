# How to Store Icons

Map保存時にシンボルのアイコン（SVG/画像）をZIPアーカイブ化してS3に保存し、MapLibreスプライトも生成・アップロードする。

## 保存フロー

1. プロジェクト内の全ベクターレイヤーのレンダラーからシンボルを走査
2. 各シンボルをスプライト用に画像化。識別子は`{レイヤーID}_{シンボルインデックス}`（例: `layer123_0`）
3. 全ての画像をマージしてMapLibre用スプライトを生成
4. 各シンボルに含まれる全てのシンボルレイヤーについて
    - SVG/画像ファイルのパスを解決
    - ファイルをローカルにコピー（ファイル名はシンボルレイヤーのID、例: `local_cache/map/{map_id}/assets/{symbollayer_id}.svg`）
    - シンボルレイヤーが参照するファイルパスをコピーしたファイルに書き換え（例: `./assets/{symbollayer_id}.svg`）
    - SVG/画像ファイルをZIPアーカイブに追加（assets.zip）
5. ZIP・スプライトをpresigned URLでS3にアップロード
6. assetsHash（SHA256）をstyled mapに保存

## 読み込みフロー

1. styled mapの `assetsHash` が存在すれば、asset-zip APIからダウンロードURLを取得
2. ZIPをダウンロードし `./assets` に展開
3. QGSファイルをロード（相対パスが展開先に解決される）

## API エンドポイント

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/styled-map/:id/sprite-upload` | POST | スプライトアップロード用presigned URL取得 |
| `/styled-map/:id/asset-zip-upload` | POST | ZIPアップロード用presigned URL取得 |
| `/styled-map/:id/asset-zip` | GET | ZIPダウンロード用presigned URL取得 |
| `/styled-map/:id` | PUT | `assetsHash` フィールドでアセット存在を記録 |

## ファイル命名規則

| 対象 | 命名規則 | 例 |
|---|---|---|
| ZIP内ファイル | `{layerID}_{symbolIndex}.{元の拡張子}` | `layer123_0.svg` |
| スプライト名 | `{symbolLayerID}` | `{a1b2c3d4-e5f6-7890-abcd-ef1234567890}` |
| QGSパス | `./assets/{symbolLayerID}.{ext}` | `./assets/a1b2c3d4-e5f6-7890-abcd-ef1234567890.svg` |

## 制限事項

- スプライト: 各ファイル1MB以下
- ZIP: 10MB以下
- スプライト画像サイズ: 64x64px（1MB超過時は32x32にフォールバック）

## エラーハンドリング

- アセットアップロード失敗: QGS保存は続行、ワーニング表示
- アセットダウンロード失敗: Map読み込みは続行、アイコン欠損のみ
