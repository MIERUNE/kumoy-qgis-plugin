# kumoy/map_assets

QGISプロジェクトからマップアセット（シンボル・スプライト・ファイル）を収集し、Kumoyクラウドへアップロードするモジュール。

## 処理フロー

```
QGISプロジェクト
    ↓
collect_assets()  → スプライト画像 + ファイル参照の収集
    ↓
├→ rewrite_paths()      → シンボルパスを相対パスへ書き換え
├→ build_asset_zip()    → アセットファイルをZIP化
└→ generate_sprites()   → MapLibre用スプライトアトラス生成
    ↓
upload_to_presigned_url() × 3 (sprite.json, sprite.png, assets.zip)
    ↓
Kumoyクラウドストレージ
```

## 各ファイルの役割

| ファイル | 役割 |
|---|---|
| `symbol_collector.py` | ベクターレイヤーからシンボル画像(64x64)とファイル参照(SVG/PNG)を収集 |
| `sprite_generator.py` | 収集したスプライトからMapLibre互換のスプライトアトラス(sprite.json + sprite.png)を生成 |
| `qgs_path_rewriter.py` | シンボルレイヤーのファイルパスを絶対パスから相対パス(`./assets/{id}.{ext}`)へ書き換え |
| `zip_builder.py` | アセットファイルをZIPアーカイブにパッケージング（上限10MB） |
| `uploader.py` | S3プリサインドURLを使ったマルチパートアップロード |

## 呼び出し元

`kumoy/local_cache/map.py` の `collect_and_upload_assets()` から呼び出される。ユーザーがQGISプロジェクトをKumoyへ保存する際に実行される。
