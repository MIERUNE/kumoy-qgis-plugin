from abc import ABC
from dataclasses import dataclass

from settings_manager import get_settings

DEFAULT_COGNITO_URL: str = (
    "https://strato-staging.auth.ap-northeast-1.amazoncognito.com"
)
DEFAULT_COGNITO_CLIENT_ID: str = "4us5qd97e5f471pdq7kk44d63s"
DEFAULT_SERVER_URL: str = "https://d28cu1u5by4hv7.cloudfront.net"


@dataclass(frozen=True)
class ApiConfig(ABC):
    COGNITO_URL: str
    COGNITO_CLIENT_ID: str
    SERVER_URL: str


def get_api_config() -> ApiConfig:
    # カスタムサーバー設定を読み込む
    use_custom_server = get_settings().use_custom_server == "true"
    custom_cognito_url = get_settings().custom_cognito_url
    custom_cognito_client_id = get_settings().custom_cognito_client_id
    custom_server_url = get_settings().custom_server_url

    if (
        use_custom_server
        and custom_server_url
        and custom_cognito_url
        and custom_cognito_client_id
    ):
        return ApiConfig(
            COGNITO_URL=custom_cognito_url,
            COGNITO_CLIENT_ID=custom_cognito_client_id,
            SERVER_URL=custom_server_url,
        )
    else:
        # デフォルト値
        return ApiConfig(
            COGNITO_URL=DEFAULT_COGNITO_URL,
            COGNITO_CLIENT_ID=DEFAULT_COGNITO_CLIENT_ID,
            SERVER_URL=DEFAULT_SERVER_URL,
        )
