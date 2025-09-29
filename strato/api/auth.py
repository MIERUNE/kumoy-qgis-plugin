import json
import urllib.parse
import urllib.request
from typing import Dict, Optional

from . import config as api_config


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

    config = api_config.get_api_config()

    try:
        # /api/_public/params エンドポイントからCognito設定を取得
        params_response = urllib.request.urlopen(
            f"{config.SERVER_URL}/api/_public/params"
        )
        params_data = json.loads(params_response.read().decode("utf-8"))
        cognito_domain = params_data.get("cognitoDomainUrl")
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
    except urllib.error.HTTPError as e:
        # HTTPエラーの詳細を出力
        error_body = e.read().decode("utf-8")
        print(f"Cognito token refresh HTTP error: {e.code} - {error_body}")
        return None
    except Exception as e:
        print(f"Error occurred during Cognito token refresh: {str(e)}")
        return None
