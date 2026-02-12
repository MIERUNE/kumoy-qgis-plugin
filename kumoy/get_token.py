import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from typing import Dict, Optional
from urllib.error import HTTPError

from qgis.core import Qgis
from qgis.utils import iface

from ..settings_manager import get_settings, store_setting
from .api import config as api_config
from .api.error import format_api_error, raise_error


class TokenExpiredOrInvalidError(Exception):
    """Exception raised when refresh token is expired or invalid"""

    pass


def _clear_authentication_state() -> None:
    """
    Clear all authentication data when session is completely expired.
    """

    print("Session expired - clearing authentication state")

    # Show message to user
    iface.messageBar().pushMessage(
        "Kumoy",
        "Session expired. Please reconnect again.",
        level=Qgis.Warning,
        duration=10,
    )

    # Clear all tokens
    store_setting("id_token", "")
    store_setting("refresh_token", "")
    store_setting("token_expires_at", "")
    store_setting("user_info", "")


def _refresh_token(refresh_token: str) -> Optional[Dict]:
    """
    Cognitoを使用して期限切れのトークンをリフレッシュトークンで更新する

    Args:
        refresh_token: 使用するリフレッシュトークン

    Returns:
        新しいid_tokenなどの認証情報を含む辞書、または更新に失敗した場合はNone
    """
    if not refresh_token:
        return None

    config = api_config.get_api_config()

    try:
        # /api/_public/params エンドポイントからCognito設定を取得
        params_response = urllib.request.urlopen(
            f"{config.SERVER_URL}/api/_public/params"
        )
        params_data = json.loads(params_response.read().decode("utf-8"))
        cognito_domain = params_data.get("cognitoDomain")
        cognito_client_id = params_data.get("cognitoClientId")

        # Cognitoのトークンエンドポイントを使用
        token_url = f"https://{cognito_domain}/oauth2/token"

        # リクエストデータを準備
        data = {
            "grant_type": "refresh_token",
            "client_id": cognito_client_id,
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
    except HTTPError as e:
        error_body = e.read().decode("utf-8")
        try:
            error_data = json.loads(error_body)
        except json.JSONDecodeError:
            error_data = {}

        # Handle invalid_grant from Cognito (HTTP 400)
        if error_data.get("error") == "invalid_grant":
            print(
                f"Refresh token expired or invalid ({e.code}): "
                f"{error_data.get('error', '')}"
            )
            raise TokenExpiredOrInvalidError("Refresh token is no longer valid")
        # Other HTTP errors
        raise_error(error_data)
    except Exception as e:
        print(f"Error occurred during Cognito token refresh: {format_api_error(e)}")
        return None


def _is_token_valid(expires_at: str) -> bool:
    """
    Check if the token is still valid based on expiration time

    Args:
        expires_at: ISO format timestamp when the token expires

    Returns:
        bool: True if token is still valid, False otherwise
    """
    if not expires_at:
        return False

    try:
        # Parse the expiration timestamp
        expiration_time = datetime.fromisoformat(expires_at)
        current_time = datetime.now()

        # Add a 5-minute buffer to avoid edge cases
        buffer_seconds = 300  # 5 minutes

        # Check if the token is still valid with buffer
        return current_time < (expiration_time - timedelta(seconds=buffer_seconds))
    except Exception as e:
        print(f"Error checking token validity: {format_api_error(e)}")
        return False


def _save_token_to_cache(auth_response: Dict) -> None:
    """
    Save authentication tokens to settings cache

    Args:
        auth_response: Authentication response containing tokens
    """
    try:
        # Save id token
        if "id_token" in auth_response:
            store_setting("id_token", auth_response["id_token"])

        # Save refresh token if available
        if "refresh_token" in auth_response:
            store_setting("refresh_token", auth_response["refresh_token"])

        # Calculate and save expiration time
        if "expires_in" in auth_response:
            # Convert expires_in (seconds) to timestamp
            expires_at = datetime.now().timestamp() + int(auth_response["expires_in"])
            expiration_datetime = datetime.fromtimestamp(expires_at)
            store_setting("token_expires_at", expiration_datetime.isoformat())
    except Exception as e:
        print(f"Error saving token to cache: {format_api_error(e)}")


def get_token() -> Optional[str]:
    """
    Get authentication token from cache or by authenticating with credentials

    Returns:
        str: Authentication token or None if authentication fails
    """
    # Try to get token from cache first
    cached_token = get_settings().id_token
    token_expires_at = get_settings().token_expires_at

    # If we have a valid cached token, use it
    if cached_token and _is_token_valid(token_expires_at):
        return cached_token

    # Try to refresh the token if we have a refresh token
    cached_refresh_token = get_settings().refresh_token
    if cached_refresh_token:
        print("Attempting to refresh token...")

        try:
            refresh_response = _refresh_token(cached_refresh_token)

            if refresh_response and "id_token" in refresh_response:
                # Save the refreshed token to cache
                _save_token_to_cache(refresh_response)
                return refresh_response["id_token"]
            else:
                print("Token refresh failed, will try with credentials")
        except TokenExpiredOrInvalidError:
            _clear_authentication_state()
            return None
