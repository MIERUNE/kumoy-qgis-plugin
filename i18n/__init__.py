"""Lightweight translation utility.

Qt の .ts/.qm パイプラインの代わりに、原文(英語)をキーにした JSON 辞書を引く。
ドメイン知識を持たない汎用モジュール。ロケール検出は呼び出し側の責務とし、
ここは「辞書ロード + ルックアップ」だけを担うので QGIS 非依存でテストできる。
"""

import json
import os

# 現在ロード中の翻訳辞書（原文 -> 訳文）。未ロード時は空 = 全て原文フォールバック。
_translations: dict = {}


def load(locale: str) -> None:
    """同ディレクトリの ``<locale>.json`` を読み込む。

    locale は QGIS のロケール文字列（例 "ja", "en"）。ファイルが無ければ
    辞書を空にし、tr() は原文をそのまま返す（英語フォールバック）。
    """
    global _translations
    path = os.path.join(os.path.dirname(__file__), f"{locale}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            _translations = json.load(f)
    else:
        _translations = {}


def tr(message: str) -> str:
    """原文をキーに訳文を引く。未登録なら原文を返す。

    プレースホルダは原文側にそのまま書き（例 ``tr("count: {}").format(n)``）、
    .format() 等は呼び出し側で適用する。
    """
    return _translations.get(message, message)
