# qgishub-plugin

QGIS HUB(TBD)のBackendと疎通するためのPlugin

## specification

- organization/team/projectの一覧ために汎用エンドポイントを利用するが
- QgsVectorLayerの疎通には`/_qgis`エンドポイントを利用する

## Install

monorepoなのでプラグインフォルダにシンボリックリンクを貼りましょう

```sh
ln -s /Users/kanahiro/Documents/git/qgishub-backend/qgisplugin qgishub_plugin
```

## Preparation

```
packages = [
  { include = "qgis", from = "C:\\Program Files\\QGIS 3.28.2\\apps\\qgis\\python" },
]
```

1. install `Poetry`

    ```sh
    pip install poetry
    ```

2. install dependencies with Poetry

    ```sh
    # QGIS内のPython実行ファイルを参照する（開発ターゲットのバージョンのQGIS）
    # macOS, bash
    poetry env use /Applications/QGIS.app/Contents/MacOS/bin/python3
    poetry install
    ```

    仮想環境がカレントディレクトリに作成されます。

3. (when VSCode) 仮想環境をVSCode上のPythonインタプリタとして選択

    VSCodeはカレントディレクトリの仮想環境を検出しますが、手動で選択する必要がある場合もあります。  

    1. [Cmd + Shift + P]でコマンドパレットを開く
    2. [Python: Select Interpreter]を見つけてクリック
    3. 利用可能なインタプリタ一覧が表示されるので、先ほど作成した仮想環境を選択（通常、リストの一番上に"Recommended"として表示される）
