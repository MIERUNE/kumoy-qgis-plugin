from dataclasses import dataclass

from PyQt5.QtWidgets import QMessageBox

from settings_manager import SettingsManager


@dataclass
class Config:
    COGNITO_URL: str = "https://qgishubv3.auth.ap-northeast-1.amazoncognito.com"
    COGNITO_CLIENT_ID: str = "49fnn61i1bh3jongq62i290461"
    API_URL: str = "https://d3eqzgssnrhp33.cloudfront.net/api"

    def __post_init__(self):
        """初期化時に設定を読み込む"""
        self.load_settings()

    def load_settings(self) -> bool:
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
                # 必要な設定項目をチェック
                missing_settings = []
                if not custom_server_url:
                    missing_settings.append("Server URL")
                if not custom_cognito_url:
                    missing_settings.append("Cognito URL")
                if not custom_cognito_client_id:
                    missing_settings.append("Cognito Client ID")

                # 未入力項目がある場合はメッセージボックスを表示して処理を終了
                if missing_settings:
                    missing_text = ", ".join(missing_settings)
                    QMessageBox.warning(
                        None,
                        "Custom Server Configuration Error",
                        f"The following settings are missing:\n{missing_text}\n\nPlease configure them in the settings dialog.",
                    )
                    return False

                self.API_URL = custom_server_url
                self.COGNITO_URL = custom_cognito_url
                self.COGNITO_CLIENT_ID = custom_cognito_client_id

            return True
        except Exception:
            # 設定の読み込みに失敗した場合はデフォルト値を使用
            return True


config = Config()

"""
config = Config(
    COGNITO_URL="https://qgishubv3.auth.ap-northeast-1.amazoncognito.com",
    COGNITO_CLIENT_ID="49fnn61i1bh3jongq62i290461",
    API_URL="http://localhost:3000/api",
)
"""
