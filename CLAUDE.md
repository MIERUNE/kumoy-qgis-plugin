# Kumoy QGIS Plugin

QGIS向けクラウドサービス「Kumoy」を利用するためのプラグイン

## コマンド

- 依存インストール: `uv sync`
- フォーマット修正: `uv run ruff format .`
- テスト:

  ```bash
  docker run --rm \
    -v "$(pwd)":/plugin \
    -w /plugin \
    qgis/qgis:3.40 \
    sh -c "
      pip3 install --break-system-packages pytest pytest-qgis &&
      xvfb-run -s '+extension GLX -screen 0 1024x768x24' \
        python3 -m pytest tests/ -v
    "
  ```

## コードスタイル

- Python 3.9+。ruffでlint/format（設定は pyproject.toml）
- 型ヒントを積極的に使う。dataclassを活用する

## アーキテクチャ

- `plugin.py` — プラグインエントリポイント（initGui/unload）
- `kumoy/api/` — APIクライアント。QgsBlockingNetworkRequestベースのHTTP通信、Bearer認証
- `kumoy/provider/` — QGISデータプロバイダ実装（QgsVectorDataProvider）
- `kumoy/local_cache/` — ローカルキャッシュ機構
- `kumoy/auth_manager.py` — OAuth2認証（PKCE、ローカルHTTPサーバ port 9248）
- `ui/` — PyQt UI（ダイアログ、ブラウザパネル、レイヤーUI）
- `processing/` — QGIS Processing アルゴリズム（ベクターアップロード等）
- `tests/` — pytest ベースのテスト（pytest-qgis使用）
- `i18n/` — 国際化（英語デフォルト、日本語対応済み）

## 注意事項

- Qt5/Qt6両対応。`pyqt_version.py` が互換レイヤーを提供するので、PyQt5/6で異なるAPIはここを経由する
- 外部パッケージ依存なし（ランタイムはQGIS/PyQt/標準ライブラリのみ）
- UIテキストは `tr()` で翻訳対応すること

## Git ワークフロー

- mainブランチへPR。CI（lint + test）が必須
