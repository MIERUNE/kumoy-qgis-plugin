# kumoy/sprite

QGISプロジェクトからスプライトアセットを収集し、Kumoyクラウドへアップロードするモジュール。

## 処理フロー

```
QGISプロジェクト
    ↓
collect_sprites()    → Pointシンボルからスプライト画像を収集
    ↓
generate_sprite()    → MapLibre用スプライトアトラス生成
  └ pack_sprites()      → 収集したスプライトをsprite.json + sprite.pngにパッキング
    ↓
upload_sprites()     → presigned URLで sprite.json / sprite.png をアップロード
    ↓
Kumoyクラウドストレージ
```

## 各ファイルの役割

| ファイル | 役割 |
|---|---|
| `__init__.py` | 公開API。`generate_sprite()` でスプライト生成+ハッシュ計算（`v2-` 接頭辞付き）、`upload_sprites()` でアップロード |
| `symbol_collector.py` | KumoyベクターレイヤーからPointシンボル画像を収集。実寸・回転なしで512x512に描き、中心を保って透明余白をトリム |
| `sprite_packer.py` | 収集したスプライトをMapLibre互換のスプライトアトラス(sprite.json + sprite.png、`pixelRatio: 2`)にパッキング |
| `uploader.py` | S3 presigned URLを使ったmultipart/form-dataアップロード |

## スプライトの形式（v2）

Web側（kumoy-services の `@kumoy-packages/qgisproject`）は `assetsHash` の接頭辞 `v2-` で形式を判別する。
接頭辞の無い旧形式（高さ64pxに正規化・回転を焼き込み）も引き続き表示できる。
詳細は kumoy-services の `docs/qgis-sprite-flow.md`。

- **大きさ**: Web側の `convertToPixel` と同じ 72dpi で換算した実寸を、`SPRITE_PIXEL_RATIO`（2）倍の解像度で描く。
  `QgsRenderContext.scaleFactor` ではなく painter ごと拡大する（Pixel単位のサイズが追従しないため）。
  SVGがぼやけないよう `ForceVectorOutput` で描く
- **回転**: シンボル全体の角度を0にして描き、シンボルレイヤー間の相対的な角度だけを焼き込む。
  シンボルの角度（データ定義の回転を含む）はWeb側が `icon-rotate` で掛ける
- **キャンバス**: 512px四方（表示上256px ≒ 90mm）。これを超えるシンボルは切れる
- **トリム**: 画像中心＝シンボルのアンカーなので、中心を保ったまま対称に切り落とす（オフセットと回転の中心を保つ）
- `SPRITE_FORMAT_PREFIX`（`__init__.py`）・72dpi・`SPRITE_PIXEL_RATIO` はWeb側と揃えること。
  接頭辞に未対応のサーバーには保存できない（`assetsHash` のバリデーションで400になる）

## 主要なデータ型

- `SpriteEntry` — シンボル1つ分の画像データ（name + QImage）
- `SpriteData` — 生成済みスプライト一式（json_bytes + png_bytes + hash）
