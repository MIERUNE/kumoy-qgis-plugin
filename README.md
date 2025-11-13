# strato-plugin

StratoGIS Plugin

## specification

- organization/team/project の一覧ために汎用エンドポイントを利用するが
- QgsVectorLayer の疎通には`/_qgis`エンドポイントを利用する

## Preparation

### 仮想環境の作成

```sh
# macOS
uv venv --python /Applications/QGIS.app/Contents/MacOS/bin/python3 --system-site-packages
```

### シンボリックリンクの作成

```sh
ln -s '/Users/hoge/GitHub/strato-plugin' '/Users/hoge/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/strato-plugin'
```

### (when VSCode) 仮想環境を VSCode 上の Python インタプリタとして選択

VSCode はカレントディレクトリの仮想環境を検出しますが、手動で選択する必要がある場合もあります。

1. [Cmd + Shift + P]でコマンドパレットを開く
2. [Python: Select Interpreter]を見つけてクリック
3. 利用可能なインタプリタ一覧が表示されるので、先ほど作成した仮想環境`/.venv/bin/python`を選択（通常、リストの一番上に"Recommended"として表示される）

## Development

### APIの呼び方

APIを呼び出す際の例外処理は統一した方法を利用してください。

```python
```
