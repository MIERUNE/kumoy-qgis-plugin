# 翻訳ガイド (Translation Guide)

このプラグインは Qt の .ts/.qm パイプラインを使わず、**原文(英語)をキーにした
JSON 辞書**で翻訳する。`i18n/__init__.py` が辞書のロードとルックアップを担う。

## ファイル構成

```
i18n/
├── __init__.py   # load(locale) と tr(message)
├── ja.json       # 日本語訳（原文 -> 訳文）
└── en.json       # （任意）英語。原文=英語なので無ければ原文フォールバック
scripts/
└── extract_i18n.py   # コードから tr("...") を抽出して JSON を更新（pylupdate 相当）
```

## 仕組み

1. **翻訳関数**: コード側は `tr("英語原文")` を呼ぶ。`tr()` は辞書を引き、未登録なら
   原文をそのまま返す（＝英語フォールバック）。
2. **言語検出**: プラグイン初期化時に `i18n.load(QgsApplication.instance().locale())` を
   1回呼び、`<locale>.json` を読み込む。QGIS のロケール変更は QGIS 再起動で反映される
   （Qt 方式と同じ挙動）。
3. プレースホルダは原文側に書き、`.format()` は呼び出し側で適用する:
   `tr("count: {}").format(n)`

## 使い方

### コード中で翻訳する

```python
from ..i18n import tr   # 相対パスはファイル位置に合わせる（.. / ... 等）

label.setText(tr("Save Map"))
msg = tr("An error occurred: {}").format(error_text)
```

QObject サブクラス（QDialog 等）の中でも `self.tr(...)` ではなく、import した
`tr(...)` を直接呼ぶ。Qt 標準の `QObject.tr` はクラス名コンテキストで JSON を引けない
ため使わない。クラスに `def tr` を定義する必要はない。

### 翻訳キーを追加・更新する

新しい `tr("...")` を書いたら抽出スクリプトを実行する。コードに在って JSON に無い
キーは空訳 `""` で追加され、JSON に在ってコードに無いキーは「未使用」として報告される
（自動削除はしない）:

```bash
python3 scripts/extract_i18n.py            # i18n/ja.json を更新
python3 scripts/extract_i18n.py --check    # 未更新なら非0終了（CI 用）
```

その後 `i18n/ja.json` の空訳を埋める（エディタで直接編集。バイナリ化・コンパイル不要）。

## 対応言語

- 英語 (en) — デフォルト（原文）
- 日本語 (ja) — `ja.json`
