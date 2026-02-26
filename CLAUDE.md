# Kumoy QGIS Plugin

QGIS用クラウド連携プラグイン。QGISプロジェクトをWebに公開し、データ管理・チーム共同作業を実現する。

## コマンド

- 仮想環境作成: `uv venv --python /Applications/QGIS.app/Contents/MacOS/bin/python3 --system-site-packages`
- 依存インストール: `uv sync`
- Lint: `uv run ruff check .`
- フォーマットチェック: `uv run ruff format . --check --diff`
- フォーマット修正: `uv run ruff format .`
- テスト: `python test_suite.py`（ローカル実行にはQGIS環境が必要）

## コードスタイル

- Python 3.9+。ruffでlint/format（設定は pyproject.toml）
- F401（未使用import）は無視設定
- 型ヒントを積極的に使う。dataclassを活用する
- 関数・変数はsnake_case、クラスはPascalCase、定数はUPPER_CASE

## アーキテクチャ

- `plugin.py` — プラグインエントリポイント（initGui/unload）
- `kumoy/api/` — APIクライアント。QgsBlockingNetworkRequestベースのHTTP通信、Bearer認証
- `kumoy/provider/` — QGISデータプロバイダ実装（QgsVectorDataProvider）
- `kumoy/local_cache/` — ローカルキャッシュ機構
- `kumoy/auth_manager.py` — OAuth2認証（PKCE、ローカルHTTPサーバ port 9248）
- `ui/` — PyQt UI（ダイアログ、ブラウザパネル、レイヤーUI）
- `processing/` — QGIS Processing アルゴリズム（ベクターアップロード等）
- `tests/` — unittest ベースのテスト
- `i18n/` — 国際化（英語デフォルト、日本語対応済み）

## 注意事項

- Qt5/Qt6両対応。`pyqt_version.py` が互換レイヤーを提供するので、PyQt5/6で異なるAPIはここを経由する
- 外部パッケージ依存なし（ランタイムはQGIS/PyQt/標準ライブラリのみ）
- UIテキストは `tr()` で翻訳対応すること
- WKBの最大長は10,000,000文字（`MAX_WKB_LENGTH`）
- QGIS 3.40〜4.99をサポート（metadata.txt参照）

## Git ワークフロー

- mainブランチへPR。CI（lint + test）が必須
- ブランチ命名: `feat/`, `fix/`, `chore/`, `docs/`
- リリースはGitHub Releaseの公開でトリガー（タグからバージョン自動設定）
