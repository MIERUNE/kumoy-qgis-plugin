from dataclasses import dataclass

from .. import settings_manager

DEFAULT_SERVER_URL = "https://app.kumoy.io"


@dataclass(frozen=True)
class ApiConfig:
    SERVER_URL: str


def get_api_config() -> ApiConfig:
    return ApiConfig(
        SERVER_URL=settings_manager.custom_server_url() or DEFAULT_SERVER_URL
    )
