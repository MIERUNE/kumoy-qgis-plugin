from dataclasses import dataclass

from qgis.core import Qgis, QgsMessageLog

from qgishub.constants import LOG_CATEGORY
from settings_manager import SettingsManager


@dataclass(init=False, frozen=True)
class DefaultConfig:
    COGNITO_URL: str = "https://strato-staging.auth.ap-northeast-1.amazoncognito.com"
    COGNITO_CLIENT_ID: str = "4us5qd97e5f471pdq7kk44d63s"
    API_URL: str = "https://d28cu1u5by4hv7.cloudfront.net/api"


@dataclass
class Config:
    COGNITO_URL: str = DefaultConfig.COGNITO_URL
    COGNITO_CLIENT_ID: str = DefaultConfig.COGNITO_CLIENT_ID
    API_URL: str = DefaultConfig.API_URL

    def __post_init__(self):
        """初期化時に設定を読み込む"""
        self.load_settings()

    def refresh(self):
        """Server設定を初期化"""
        self.COGNITO_URL = DefaultConfig.COGNITO_URL
        self.COGNITO_CLIENT_ID = DefaultConfig.COGNITO_CLIENT_ID
        self.API_URL = DefaultConfig.API_URL

    def load_settings(self):
        """設定マネージャーから設定を読み込む"""
        # プラグインがロードされている場合のみ設定を読み込む
        try:
            # Lazy import to avoid circular dependency
            from .api import auth

            auth.clear_tokens()
            settings_manager = SettingsManager()

            # カスタムサーバー設定を読み込む
            use_custom_server = (
                settings_manager.get_setting("use_custom_server") == "true"
            )
            custom_cognito_url = settings_manager.get_setting("custom_cognito_url")
            custom_cognito_client_id = settings_manager.get_setting(
                "custom_cognito_client_id"
            )
            custom_server_url = settings_manager.get_setting("custom_server_url")

            # カスタムサーバーが有効で各設定が存在すれば使用する
            if (
                use_custom_server
                and custom_server_url
                and custom_cognito_url
                and custom_cognito_client_id
            ):
                self.API_URL = custom_server_url
                self.COGNITO_URL = custom_cognito_url
                self.COGNITO_CLIENT_ID = custom_cognito_client_id
        except Exception as e:
            # 設定の読み込みに失敗した場合はデフォルト値を使用
            QgsMessageLog.logMessage(
                f"Failed to load settings, using default values. Error: {str(e)}",
                LOG_CATEGORY,
                Qgis.Warning,
            )
            pass


config = Config()
