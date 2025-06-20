# 翻訳ガイド (Translation Guide)

この QGIS プラグインは Qt 翻訳システムを使用して多言語対応しています。

## ファイル構成

```
qgis-plugin/
├── strato.pro            # Qt プロジェクトファイル（翻訳対象ファイルを定義）
├── i18n/                 # 翻訳ファイルディレクトリ
│   ├── strato_ja.ts      # 日本語翻訳ソースファイル
│   └── strato_ja.qm      # 日本語翻訳バイナリファイル
```

## 翻訳の仕組み

1. **翻訳関数**: 各クラスで `tr()`メソッドを使用して文字列を翻訳可能にしています
2. **自動言語検出**: プラグイン初期化時に QGIS のロケール設定を自動検出
3. **フォールバック**: 翻訳ファイルが見つからない場合は英語（デフォルト）で表示

## 対応言語

- 英語 (en) - デフォルト
- 日本語 (ja) - 完全対応

## 翻訳ファイルの更新方法

### 1. 新しい翻訳文字列を追加した場合

```bash
# プロジェクトファイルを更新（必要に応じて）
# qgis_hub.pro のSOURCESセクションに新しいファイルを追加

# 翻訳ファイルを更新
/Applications/QGIS.app/Contents/MacOS/bin/python3.9 -m PyQt5.pylupdate_main strato.pro
```

### 2. 翻訳の追加・編集

```bash
# Qt Linguistを使用（推奨）
linguist i18n/strato_ja.ts

# またはテキストエディタで直接編集
# i18n/strato_ja.ts ファイルを編集
```

### 3. バイナリファイルのコンパイル

```bash
# .ts から .qm ファイルを生成
lrelease i18n/strato_ja.ts
```
