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
- `kumoy/` — Kumoyドメインロジック（API・キャッシュ・プロバイダ・設定など、UI非依存の中核）
  - `kumoy/api/` — APIクライアント。QgsBlockingNetworkRequestベースのHTTP通信、Bearer認証
  - `kumoy/provider/` — QGISデータプロバイダ実装（QgsVectorDataProvider）
  - `kumoy/local_cache/` — ローカルキャッシュ機構（純粋なファイル操作のみ）
  - `kumoy/auth_manager.py` — OAuth2認証（PKCE、ローカルHTTPサーバ port 9248）
  - `kumoy/settings_manager.py` — QSettingsラッパー（session_token等のドメイン状態を保持）
- `ui/` — PyQt UI（ダイアログ、ブラウザパネル、レイヤーUI、保存ハンドラ、共通エラーハンドラ等）
  - `ui/error_handler.py` — 共通APIエラーハンドラ（QMessageBox表示・Browserリフレッシュを含むのでUI責務）
- `processing/` — QGIS Processing アルゴリズム（ベクターアップロード等）
- `tests/` — pytest ベースのテスト（pytest-qgis使用）
- `i18n/` — 国際化（英語デフォルト、日本語対応済み）

### 依存方向のルール

import は上位レイヤから下位レイヤへの一方向のみ。下位から上位への import は循環参照や責務逸脱の温床になるので禁止。

許可される向き（上が上位）：

```
plugin.py
  ├→ ui/                  （ダイアログ・ブラウザ・レイヤー連携・保存ハンドラ・error_handler）
  └→ processing/          （Processingアルゴリズム。ui/error_handler を sideways で利用してOK）
       ↓
       kumoy/             （api, local_cache, provider, sprite, auth_manager,
                           settings_manager 等のドメインロジック。UI非依存）
       ↓
       pyqt_version.py / qgis_version.py （Qt/QGIS互換レイヤー）
```

具体ルール：

- `kumoy/` 配下から `ui/`・`processing/` を import しない。UI対話やユーザー操作起点のフロー（QMessageBoxを出す、保存ハンドラ、レイヤー変換ダイアログ等）はすべて `ui/` か `processing/` 側に置く。
- `kumoy/local_cache/` などのドメイン層は純粋なデータ・ファイル操作のみを担い、UI/API連携を伴うオーケストレーションは UI 層に切り出す（例: `ui/project_save_handler.py`）。
- Kumoyドメインの状態（session_token、選択中のorganization/project、カスタムサーバURL等）は `kumoy/settings_manager.py` に集約。`ui/` や `processing/` から読み書きするのはOK、`kumoy/` 内部からの参照もsibling同士の通常import。
- `ui/error_handler.py` は `kumoy.settings_manager` と `kumoy.api.error` のみに依存し、QGISの公開API（`dataItemProviderRegistry`）を介してBrowserをリフレッシュする。`plugin.py` への callback 登録などの「隠れた逆向き依存」は持たない。
- `processing/` → `ui/error_handler` は横方向の例外依存。`error_handler` はUI責務（QMessageBox表示）を持つため `ui/` 配下に置く一方、`processing/` からも共通利用したいので許可。それ以外の `processing/` ↔ `ui/` の横断 import は避ける。
- レイヤー間で何かを呼びたくなったら、まず依存方向を確認すること。逆向きの import が必要に思えたら設計を見直すサイン。

## 注意事項

- Qt5/Qt6両対応。`pyqt_version.py` が互換レイヤーを提供するので、PyQt5/6で異なるAPIはここを経由する
- 外部パッケージ依存なし（ランタイムはQGIS/PyQt/標準ライブラリのみ）
- UIテキストは `tr()` で翻訳対応すること

### 翻訳ヘルパーの書き方

Qt の .ts/.qm パイプラインは使わない。原文(英語)をキーにした JSON 辞書を `i18n/`
パッケージが引く（コンテキスト名は無い）。詳細は `i18n/README.md`。

- 翻訳したい文字列は `i18n.tr("英語原文")` を呼ぶ（QObject サブクラス内でも同じ）。
  `i18n` モジュールをインポートする（相対パスはファイル位置に合わせる）。出所が明示され
  読みやすいので、`from ..i18n import tr` ではなくモジュール経由で呼ぶ。プレースホルダは
  原文側に書き `.format()` で埋める。
  ```python
  from .. import i18n        # ui/ 直下なら .. 、ui/browser/ なら ... など
  label.setText(i18n.tr("Save Map"))
  msg = i18n.tr("An error occurred: {}").format(error_text)
  ```

- 文字列を追加・変更したら `python3 i18n/extract.py` を実行して `i18n/ja.json`
  に新規キー（空訳）を追加し、訳を埋める。`--check` で CI 検証できる。

## Git ワークフロー

- mainブランチへPR。CI（lint + test）が必須
