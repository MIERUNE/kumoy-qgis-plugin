"""
プロジェクト全体で使用する定数を管理するモジュール
"""

# プラグイン名・プロバイダ名
PLUGIN_NAME = "Kumoy"

# ログメッセージのカテゴリ名（QgsMessageLogで使用）
LOG_CATEGORY = PLUGIN_NAME

# ブラウザパネルのルートパス
BROWSER_ROOT_PATH = "kumoy:/"

# データプロバイダー関連
DATA_PROVIDER_KEY = "kumoy"
DATA_PROVIDER_DESCRIPTION = "Kumoy Data Provider"

# ラスタ用は別プロバイダキーにする。QGIS は同一キーのプロバイダを
# ベクタ／ラスタどちらかに紐づけるため、ベクタの "kumoy" と分けることで
# それぞれのメタデータを単一責務に保つ。
RASTER_DATA_PROVIDER_KEY = "kumoyraster"
RASTER_DATA_PROVIDER_DESCRIPTION = "Kumoy Raster Data Provider"

# 各種名称の最大文字数
MAX_CHARACTERS_ORGANIZATION_NAME = 32
MAX_CHARACTERS_PROJECT_NAME = 32
MAX_CHARACTERS_PROJECT_DESCRIPTION = 255
MAX_CHARACTERS_VECTOR_NAME = 32
MAX_CHARACTERS_VECTOR_ATTRIBUTION = 255
MAX_CHARACTERS_RASTER_NAME = 32
MAX_CHARACTERS_RASTER_ATTRIBUTION = 255
MAX_CHARACTERS_STYLEDMAP_NAME = 32
MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION = 255
MAX_CHARACTERS_STYLEDMAP_DESCRIPTION = 255

# Kumoyのシステム上の制限
MAX_CHARACTERS_STRING_FIELD = 255
# 旧JSON経路の10,000,000文字のbase64 bodyが表現できるraw bytesと同値。
MAX_FLATGEOBUF_BYTES = 7_500_000

# ラスタ(COG)アップロードの上限。BIGTIFF を使わず classic GeoTIFF に収める方針
# のため、その4GiB上限を下回る4GB(10進)にキャップする（S3の単一PUT 5GiBにも収まる）。
# 上限手前〜4GiB の出力は変換後バイト数で弾く。4GiB を超える出力はそもそも
# classic TIFF に書けず変換段階で失敗し、これが物理的な天井として働く。
MAX_RASTER_UPLOAD_BYTES = 4_000_000_000

# 予約しているカラム名の接頭辞
RESERVED_FIELD_NAME_PREFIX = "kumoy_"

# ドキュメントのURL
DOCUMENTATION_URL = "https://docs.kumoy.io/"
