# How to Store Icons

Map保存時にシンボルのアイコン（SVG/画像）をZIPアーカイブ化してS3に保存し、MapLibreスプライトも生成・アップロードする。

## 保存フロー

1. プロジェクト内の全ベクターレイヤーのレンダラーからシンボルを走査
2. 各シンボルレイヤーからファイル参照（SVG/画像パス）を収集
   - ビルトインSVG含む（バージョン間の互換性確保）
   - URL・存在しないファイルは除外
3. 収集したファイルをZIPアーカイブ化（ファイル名: `{symbolLayerID}.{ext}`）
4. QGS XML内のパスを `./{map_id}/{symbolLayerID}.{ext}` に書き換え
5. 各シンボルを `QgsSymbol.asImage(QSize(64,64))` で画像化し、MapLibreスプライト（sprite.json + sprite.png）を生成
6. スプライト名はシンボルレイヤーのID（UUID）を使用
7. ZIP・スプライトをpresigned URLでS3にアップロード
8. assetsHash（SHA256）をstyled mapに保存

## 読み込みフロー

1. styled mapの `assetsHash` が存在すれば、asset-zip APIからダウンロードURLを取得
2. ZIPをダウンロードし `{cache_dir}/{map_id}/` に展開
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
| ZIP内ファイル | `{symbolLayerID}.{元の拡張子}` | `a1b2c3d4-e5f6-7890-abcd-ef1234567890.svg` |
| スプライト名 | `{symbolLayerID}` | `a1b2c3d4-e5f6-7890-abcd-ef1234567890` |
| QGSパス | `./{map_id}/{symbolLayerID}.{ext}` | `./abc123/a1b2c3d4-e5f6-7890-abcd-ef1234567890.svg` |

## 制限事項

- スプライト: 各ファイル1MB以下
- ZIP: 10MB以下
- スプライト画像サイズ: 64x64px（1MB超過時は32x32にフォールバック）

## エラーハンドリング

- アセットアップロード失敗: QGS保存は続行、ワーニング表示
- アセットダウンロード失敗: Map読み込みは続行、アイコン欠損のみ
