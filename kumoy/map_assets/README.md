# kumoy/map_assets

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
| `__init__.py` | 公開API。`generate_sprite()` でスプライト生成+ハッシュ計算、`upload_sprites()` でアップロード |
| `symbol_collector.py` | KumoyベクターレイヤーからPointシンボル画像を収集。256x256でレンダリング後、透明余白をトリムして64px内にフィット |
| `sprite_packer.py` | 収集したスプライトをMapLibre互換のスプライトアトラス(sprite.json + sprite.png)にパッキング |
| `uploader.py` | S3 presigned URLを使ったmultipart/form-dataアップロード |

## 主要なデータ型

- `SpriteEntry` — シンボル1つ分の画像データ（name + QImage）
- `SpriteData` — 生成済みスプライト一式（json_bytes + png_bytes + hash）

## 呼び出し元

`kumoy/local_cache/map.py` の `upload_assets_and_update_map()` から呼び出される。ハッシュ値で変更を検知し、変更がある場合のみアップロードする。
