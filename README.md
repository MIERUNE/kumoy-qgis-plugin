# kumoy-plugin

KumoyGIS Plugin

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
ln -s '/Users/hoge/GitHub/kumoy-plugin' '/Users/hoge/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/kumoy-plugin'
```

### (when VSCode) 仮想環境を VSCode 上の Python インタプリタとして選択

VSCode はカレントディレクトリの仮想環境を検出しますが、手動で選択する必要がある場合もあります。

1. [Cmd + Shift + P]でコマンドパレットを開く
2. [Python: Select Interpreter]を見つけてクリック
3. 利用可能なインタプリタ一覧が表示されるので、先ほど作成した仮想環境`/.venv/bin/python`を選択（通常、リストの一番上に"Recommended"として表示される）

## Development

デフォルトでは本番環境サーバーに接続しますが、開発中にはあまり使いたくありません。必要に応じて以下のURLをカスタムサーバー設定に入力してください

- テスト環境: `https://d2bpnuu07dui2w.cloudfront.net`
- 開発環境: `https://d2570m9xwzmcva.cloudfront.net`
- ローカル環境: `http://localhost:5173`

## Acknowledgements

### Sentry Integration

<https://github.com/getsentry/sentry-python> v2.44.0: MIT License
