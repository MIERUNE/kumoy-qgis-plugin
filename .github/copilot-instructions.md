# Kumoy QGIS Plugin — Copilot Review Instructions

QGIS用クラウド連携プラグイン。Python 3.9+、Qt5/Qt6両対応。

## コードスタイル

- 型ヒントを積極的に使う。dataclassを活用する
- 関数・変数は `snake_case`、クラスは `PascalCase`、定数は `UPPER_CASE`
- プライベートメソッドは `_` プレフィックス

## Qt5/Qt6 互換性（最重要）

- PyQt5/PyQt6でAPIが異なるクラスが存在するため、それらを用いる場合は必ず `pyqt_version.py` の互換レイヤーを経由する
- 例: `Qt.UserRole` → `QT_USER_ROLE`、`dialog.exec_()` → `exec_dialog(dialog)`

## API クライアントパターン

- HTTP通信は原則 `QgsBlockingNetworkRequest` ベース。
- エラーハンドリングは `kumoy/api/error.py` のカスタム例外を使用する

## 依存関係

- ランタイムは QGIS/PyQt/Python標準ライブラリ、もしくはQGISのPython環境にプリインストールされているもののみ（最小限とする）。外部パッケージ依存は禁止
- devDependencies（ruff等）はOK

## 国際化（i18n）

- UIテキストは必ず `self.tr()` または `QCoreApplication.translate()` で翻訳対応する
- ユーザーに表示されない内部ログ・デバッグメッセージは翻訳不要

## テスト

- ロジックが追加される場合はなるべくユニットテストを追加する
