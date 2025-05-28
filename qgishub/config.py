import os
import sys
from dataclasses import dataclass

from settings_manager import SettingsManager


@dataclass
class Config:
    COGNITO_URL: str = "https://qgishubv3.auth.ap-northeast-1.amazoncognito.com"
    COGNITO_CLIENT_ID: str = "49fnn61i1bh3jongq62i290461"
    API_URL: str = "https://d3eqzgssnrhp33.cloudfront.net/api"

    def __post_init__(self):
        """初期化時に設定を読み込む"""
        self.load_settings()

    def load_settings(self):
        """設定マネージャーから設定を読み込む"""
        # プラグインがロードされている場合のみ設定を読み込む
        try:
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
            if use_custom_server:
                if custom_server_url:
                    self.API_URL = custom_server_url
                if custom_cognito_url:
                    self.COGNITO_URL = custom_cognito_url
                if custom_cognito_client_id:
                    self.COGNITO_CLIENT_ID = custom_cognito_client_id
        except Exception:
            # 設定の読み込みに失敗した場合はデフォルト値を使用
            pass


config = Config()

"""
config = Config(
    COGNITO_URL="https://qgishubv3.auth.ap-northeast-1.amazoncognito.com",
    COGNITO_CLIENT_ID="49fnn61i1bh3jongq62i290461",
    API_URL="http://localhost:3000/api",
)
"""
