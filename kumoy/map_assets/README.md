# kumoy/map_assets

QGISプロジェクトからスプライトアセットを収集し、Kumoyクラウドへアップロードするモジュール。

## 処理フロー

```
QGISプロジェクト
    ↓
collect_sprites()  → Pointシンボルからスプライト画像を収集
    ↓
generate_sprites() → MapLibre用スプライトアトラス生成
    ↓
upload_to_presigned_url() × 2 (sprite.json, sprite.png)
    ↓
Kumoyクラウドストレージ
```

## 各ファイルの役割

| ファイル | 役割 |
|---|---|
| `symbol_collector.py` | ベクターレイヤーからPointシンボル画像(64x64)を収集 |
| `sprite_generator.py` | 収集したスプライトからMapLibre互換のスプライトアトラス(sprite.json + sprite.png)を生成 |
| `uploader.py` | S3プリサインドURLを使ったマルチパートアップロード |

## 呼び出し元

`kumoy/local_cache/map.py` の `upload_assets_and_update_map()` から呼び出される。ユーザーがQGISプロジェクトをKumoyへ保存する際に実行される。
