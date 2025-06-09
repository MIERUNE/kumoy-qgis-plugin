from PyQt5.QtCore import QSettings

# QSettings holds variables as list or dict or str.
# if int or bool value is set, they are converted to str in the Class.


def DEFAULT_SETTINGS():
    return {
        "id_token": "",
        "refresh_token": "",
        "token_expires_at": "",
        "user_info": {},
        "selected_organization_id": "",
        "selected_project_id": "",
        "use_custom_server": "false",
        "custom_server_url": "",
        "custom_cognito_url": "",
        "custom_cognito_client_id": "",
    }


class SettingsManager:
    SETTING_GROUP = "/QGISHUB"

    def __init__(self):
        self.__settings = DEFAULT_SETTINGS()

        self.load_settings()
        self.validate_settings()

    def load_setting(self, key):
        qsettings = QSettings()
        qsettings.beginGroup(self.SETTING_GROUP)
        value = qsettings.value(key)
        qsettings.endGroup()
        if value:
            self.__settings[key] = value

    def load_settings(self):
        for key in self.__settings:
            self.load_setting(key)

    def validate_settings(self):
        """
        読込済の設定値をチェックして不正な値があれば初期値で上書きする
        """
        for key, value in self.__settings.items():
            if self.validate_setting(key, value) is not None:
                self.store_setting(key, DEFAULT_SETTINGS()[key])

    @staticmethod
    def validate_setting(key, value):
        """
        設定値のエラーチェック
        エラーがあればエラーメッセージが、なければNoneが返る
        """
        if isinstance(value, list):
            if not isinstance(DEFAULT_SETTINGS().get(key), list):
                return "値の型が定義と一致しません"

            if len(value) != len(DEFAULT_SETTINGS().get(key, [])):
                return "値の数が定義と一致しません"

        return None

    def store_settings(self, settings_dict: dict):
        for key, value in settings_dict.items():
            self.store_setting(key, value)

    def store_setting(self, key, value):
        error_message = self.validate_setting(key, value)
        if error_message is not None:
            raise Exception(f"{key}:{value} -> {error_message}")

        qsettings = QSettings()
        qsettings.beginGroup(self.SETTING_GROUP)
        qsettings.setValue(key, value)
        qsettings.endGroup()
        self.load_settings()

    def restore_default_settings(self):
        self.store_settings(DEFAULT_SETTINGS())

    def get_setting(self, key):
        return self.__settings[key]

    def get_settings(self):
        return self.__settings
