from abc import ABC
from dataclasses import dataclass

from ...settings_manager import get_settings

# テスト環境
DEFAULT_SERVER_URL: str = "https://d2bpnuu07dui2w.cloudfront.net"


@dataclass(frozen=True)
class ApiConfig(ABC):
    SERVER_URL: str


def get_api_config() -> ApiConfig:
    # カスタムサーバー設定を読み込む
    use_custom_server = get_settings().use_custom_server == "true"
    custom_server_url = get_settings().custom_server_url

    if use_custom_server and custom_server_url:
        return ApiConfig(
            SERVER_URL=custom_server_url,
        )
    else:
        # デフォルト値
        return ApiConfig(
            SERVER_URL=DEFAULT_SERVER_URL,
        )
