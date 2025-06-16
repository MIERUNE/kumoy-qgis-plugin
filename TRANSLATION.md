# 翻訳ガイド (Translation Guide)

この QGIS プラグインは Qt 翻訳システムを使用して多言語対応しています。

## ファイル構成

```
qgis-plugin/
├── qgis_hub.pro          # Qt プロジェクトファイル（翻訳対象ファイルを定義）
├── i18n/                 # 翻訳ファイルディレクトリ
│   ├── qgis_hub_ja.ts    # 日本語翻訳ソースファイル
│   └── qgis_hub_ja.qm    # 日本語翻訳バイナリファイル
└── TRANSLATION.md        # このファイル
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
/Applications/QGIS.app/Contents/MacOS/bin/python3.9 -m PyQt5.pylupdate_main i18n/qgis_hub_ja.ts

# または手動で i18n/qgis_hub_ja.ts を編集
```

### 2. 翻訳の追加・編集

```bash
# Qt Linguistを使用（推奨）
linguist i18n/qgis_hub_ja.ts

# またはテキストエディタで直接編集
# i18n/qgis_hub_ja.ts ファイルを編集
```

### 3. バイナリファイルのコンパイル

```bash
# .ts から .qm ファイルを生成
lrelease i18n/qgis_hub_ja.ts
```

## 開発者向け情報

### 新しい翻訳可能文字列の追加

1. クラスに `tr()`メソッドを追加:

```python
def tr(self, message):
    return QCoreApplication.translate('ClassName', message)
```

2. 文字列を `self.tr()`でラップ:

```python
# 悪い例
QMessageBox.information(None, "Success", "Operation completed")

# 良い例
QMessageBox.information(None, self.tr("Success"), self.tr("Operation completed"))
```

3. プレースホルダー付き文字列:

```python
# 悪い例
self.tr(f"File {filename} saved")

# 良い例
self.tr("File {} saved").format(filename)
```

### 翻訳ファイル形式

```xml
<context>
    <name>ClassName</name>
    <message>
        <source>Original English text</source>
        <translation>翻訳されたテキスト</translation>
    </message>
</context>
```

## 現在翻訳されているコンポーネント

- `browser/styledmap.py` - スタイルマップ関連の全 UI
- `browser/root.py` - ルートコレクション、ログイン/ログアウト機能
- `browser/vector.py` - ベクターアイテム、ベクター管理機能  
- `ui/dialog_config.py` - 設定ダイアログの全 UI
- `qgishub/auth_manager.py` - 認証 HTML 画面

## トラブルシューティング

### 翻訳が表示されない場合

1. `.qm`ファイルが存在するか確認
2. QGIS のロケール設定を確認
3. プラグインの再読み込みを試す

### 新しい言語の追加

1. `qgis_hub.pro`に TRANSLATIONS を追加:

```
TRANSLATIONS = i18n/qgis_hub_ja.ts \
               i18n/qgis_hub_fr.ts
```

2. 新しい `.ts`ファイルを作成
3. `lrelease`でコンパイル
