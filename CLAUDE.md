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
    qgis/qgis:3.44 \
    sh -c "
      pip3 install --break-system-packages pytest pytest-qgis &&
      xvfb-run -s '+extension GLX -screen 0 1024x768x24' \
        python3 -m pytest tests/ -v
    "
  ```

## コードスタイル

- Python 3.9+。ruffでlint/format（設定は pyproject.toml）
- 型ヒントを積極的に使う。dataclassを活用する
- コメントはWHY/WHY NOTを簡潔に書く。英語で。

## アーキテクチャ

- `plugin.py` — プラグインエントリポイント（initGui/unload）。initGuiではネットワーク通信もダイアログもしない
- `kumoy/` — Kumoyドメインロジック（API・キャッシュ・プロバイダ・設定など、UI非依存の中核）
  - `kumoy/api/` — APIクライアント。`client.py` は同期（QgsBlockingNetworkRequest）で、HTTPステータスから型付きエラー（`error.py`）を投げる。401だけがセッション切れ、403は権限不足。レスポンスは `models.py` のdataclassに `from_dict` で変換
  - `kumoy/tasks.py` — `run_task()`。ブロッキング処理（API・ファイルI/O）をQgsTaskでワーカースレッドに逃がす。UI操作起点の通信はメインスレッドで直接呼ばず、必ずこれを使う
  - `kumoy/session.py` — セッショントークン。QGIS認証DBに暗号化保存（マスターパスワード必須、保存できなければメモリのみ）。ワーカースレッドはメモリ上のコピーを読むだけ
  - `kumoy/auth_manager.py` — OAuth Device Authorization Flow（非同期）
  - `kumoy/settings_manager.py` — 秘密でない設定（選択中のorganization/project、カスタムサーバURL）
  - `kumoy/provider/` — データプロバイダ。キャッシュがあれば通信せず即座に開き、同期はバックグラウンド（`sync_events` シグナルで通知）
  - `kumoy/local_cache/` — ローカルキャッシュ（純粋なファイル操作のみ）。ベクターはGPKG内に同期状態を持ち、再構築は新ファイル＋差し替え
  - `kumoy/map_project.py` — マップ（QGISプロジェクト）のシリアライズとURI（`kumoy:<map id>`）
- `ui/` — PyQt UI（ダイアログ、ブラウザパネル、レイヤーUI、共通エラーハンドラ等）
  - `ui/project_storage.py` — マップの保存・読み込み。`QgsProjectStorage`（type `kumoy`）としてQGIS標準の開く/保存に乗せる
  - `ui/account_actions.py` — セッション開始・ログアウト・設定リセット（ログアウトはここだけ）
  - `ui/layers/` — 地図上のKumoyレイヤーの扱い（レイヤー変換、ラスターのダウンロード後リロード、ベクター同期失敗の通知）
  - `ui/error_handler.py` — 共通APIエラーハンドラ（どのスレッドからも呼べる。表示はメインスレッドへ回す）
- `processing/` — QGIS Processing アルゴリズム。ツールボックスの階層とディレクトリを一致させる（グループ = ディレクトリ、1ツール = 1モジュール。補助モジュールを持つツールはパッケージにする）。`initAlgorithm()` では通信しない（起動時にも呼ばれるため）
  - `processing/base.py` — リソース操作系アルゴリズムの基底クラスとグループ名
  - `processing/{organization,vector,raster,map}/` — 各グループのツール（例: `vector/update.py`、`vector/upload/`）
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
- `kumoy/local_cache/` などのドメイン層は純粋なデータ・ファイル操作のみを担い、UI/API連携を伴うオーケストレーションは UI 層に切り出す（例: `ui/project_storage.py`）。
- Kumoyドメインの状態は `kumoy/session.py`（トークン）と `kumoy/settings_manager.py`（選択中のorganization/project、カスタムサーバURL等）に集約。`ui/` や `processing/` から読み書きするのはOK、`kumoy/` 内部からの参照もsibling同士の通常import。
- `ui/error_handler.py` は `kumoy/` 配下のみに依存し、QGISの公開API（`dataItemProviderRegistry`）を介してBrowserをリフレッシュする。`plugin.py` への callback 登録などの「隠れた逆向き依存」は持たない。
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
