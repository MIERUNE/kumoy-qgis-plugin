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
- `error_handler.py` — 共通APIエラーハンドラ
- `kumoy/` — Kumoyドメインロジック（API・キャッシュ・プロバイダ・設定など、UI非依存の中核）
  - `kumoy/api/` — APIクライアント。QgsBlockingNetworkRequestベースのHTTP通信、Bearer認証
  - `kumoy/provider/` — QGISデータプロバイダ実装（QgsVectorDataProvider）
  - `kumoy/local_cache/` — ローカルキャッシュ機構（純粋なファイル操作のみ）
  - `kumoy/auth_manager.py` — OAuth2認証（PKCE、ローカルHTTPサーバ port 9248）
  - `kumoy/settings_manager.py` — QSettingsラッパー（session_token等のドメイン状態を保持）
- `ui/` — PyQt UI（ダイアログ、ブラウザパネル、レイヤーUI、保存ハンドラ等）
- `processing/` — QGIS Processing アルゴリズム（ベクターアップロード等）
- `tests/` — pytest ベースのテスト（pytest-qgis使用）
- `i18n/` — 国際化（英語デフォルト、日本語対応済み）

### 依存方向のルール

import は上位レイヤから下位レイヤへの一方向のみ。下位から上位への import は循環参照や責務逸脱の温床になるので禁止。

許可される向き（上が上位）：

```
plugin.py
  ├→ ui/                 （ダイアログ・ブラウザ・レイヤー連携・保存ハンドラ等）
  ├→ processing/         （Processingアルゴリズム）
  └→ error_handler.py    （共通エラーハンドラ。UI/processingから呼ぶ）
       ↓
       kumoy/            （api, local_cache, provider, sprite, auth_manager,
                          settings_manager 等のドメインロジック。UI非依存）
       ↓
       pyqt_version.py / qgis_version.py （Qt/QGIS互換レイヤー）
```

具体ルール：

- `kumoy/` 配下から `ui/`・`processing/`・`error_handler.py` を import しない。UI対話やユーザー操作起点のフロー（QMessageBoxを出す、保存ハンドラ、レイヤー変換ダイアログ等）はすべて `ui/` か `processing/` 側に置く。
- `kumoy/local_cache/` などのドメイン層は純粋なデータ・ファイル操作のみを担い、UI/API連携を伴うオーケストレーションは UI 層に切り出す（例: `ui/project_save_handler.py`）。
- Kumoyドメインの状態（session_token、選択中のorganization/project、カスタムサーバURL等）は `kumoy/settings_manager.py` に集約。`ui/` や `processing/` から読み書きするのはOK、`kumoy/` 内部からの参照もsibling同士の通常import。
- `error_handler.py` は `kumoy.settings_manager` と `kumoy.api.error` のみに依存し、`ui/`・`processing/` のどこからでも import 可。
- レイヤー間で何かを呼びたくなったら、まず依存方向を確認すること。逆向きの import が必要に思えたら設計を見直すサイン。

## 注意事項

- Qt5/Qt6両対応。`pyqt_version.py` が互換レイヤーを提供するので、PyQt5/6で異なるAPIはここを経由する
- 外部パッケージ依存なし（ランタイムはQGIS/PyQt/標準ライブラリのみ）
- UIテキストは `tr()` で翻訳対応すること

### 翻訳ヘルパーの書き方

Qt の翻訳は「コンテキスト名」と「メッセージ」のペアで lookup される。コンテキスト名を間違えると翻訳が引かれず原文のまま表示されるので注意。

- **QObject サブクラス内（QDialog, QgsDataItem 等）**: クラスのメンバ `self.tr()` をそのまま使ってよい。コンテキストにはクラス名が自動で入る。`.ts` ファイル側もクラス名で揃える。
  ```python
  class MyDialog(QDialog):
      def tr(self, message):
          return QCoreApplication.translate("MyDialog", message)
  ```

- **モジュールレベル関数や非 QObject のクラス内**: `QCoreApplication.translate("@default", message)` を使う。`"@default"` は Qt が用意している共有コンテキスト。クラス名を勝手に入れると、その名前のクラスが存在しないため翻訳が引かれない。
  ```python
  # 良い例（error_handler.py, ui/browser/styledmap.py, kumoy/local_cache/map.py など）
  def tr(message: str, context: str = "@default") -> str:
      return QCoreApplication.translate(context, message)

  # 悪い例: クラス名でないコンテキストを勝手に作る
  def _tr(message): return QCoreApplication.translate("KumoyErrorHandler", message)
  ```

- 新規ファイル/関数を追加するときは既存の `tr()` ヘルパーの書き方に揃える。`grep` で `QCoreApplication.translate` を確認して、QObject 側はクラス名、非 QObject 側は `"@default"` という分け方になっているかを確認すること。

## Git ワークフロー

- mainブランチへPR。CI（lint + test）が必須
