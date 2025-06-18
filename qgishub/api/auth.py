import json
import urllib.parse
import urllib.request
from typing import Dict, Optional

from PyQt5.QtCore import QEventLoop, QJsonDocument, QTextStream, QUrl
from PyQt5.QtNetwork import QNetworkReply, QNetworkRequest
from qgis.core import QgsNetworkAccessManager

from ..config import config as qgishub_config


def clear_tokens() -> bool:
    """
    すべてのトークンと認証情報を初期化し、何もない状態にする

    Returns:
        初期化が成功した場合True、失敗した場合False
    """
    try:
        from settings_manager import SettingsManager

        settings_manager = SettingsManager()

        # 認証関連の設定をすべて空にする
        settings_manager.store_setting("id_token", "")
        settings_manager.store_setting("refresh_token", "")
        settings_manager.store_setting("token_expires_at", "")
        settings_manager.store_setting("user_info", {})
        settings_manager.store_setting("selected_organization_id", "")
        settings_manager.store_setting("selected_project_id", "")

        return True
    except Exception as e:
        print(f"Error occurred during token initialization: {str(e)}")
        return False


def refresh_token(refresh_token: str) -> Optional[Dict]:
    """
    Cognitoを使用して期限切れのトークンをリフレッシュトークンで更新する

    Args:
        refresh_token: 使用するリフレッシュトークン

    Returns:
        新しいid_tokenなどの認証情報を含む辞書、または更新に失敗した場合はNone
    """
    if not refresh_token:
        return None

    try:
        # Cognitoのトークンエンドポイントを使用
        token_url = f"{qgishub_config.COGNITO_URL}/oauth2/token"

        # リクエストデータを準備
        data = {
            "grant_type": "refresh_token",
            "client_id": qgishub_config.COGNITO_CLIENT_ID,
            "refresh_token": refresh_token,
        }
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")

        # リクエストヘッダーを設定
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        # リクエストを作成して送信
        req = urllib.request.Request(token_url, data=encoded_data, headers=headers)

        # レスポンスを処理
        with urllib.request.urlopen(req) as response:
            response_data = json.loads(response.read().decode("utf-8"))
            return {
                "id_token": response_data.get("id_token"),
                "refresh_token": response_data.get(
                    "refresh_token", refresh_token
                ),  # 新しいリフレッシュトークンがない場合は古いものを保持
                "expires_in": response_data.get("expires_in"),
                "token_type": response_data.get("token_type"),
            }
    except urllib.error.HTTPError as e:
        # HTTPエラーの詳細を出力
        error_body = e.read().decode("utf-8")
        print(f"Cognito token refresh HTTP error: {e.code} - {error_body}")
        return None
    except Exception as e:
        print(f"Error occurred during Cognito token refresh: {str(e)}")
        return None
