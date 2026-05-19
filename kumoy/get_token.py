from typing import Optional

from .settings_manager import get_settings


def get_token() -> Optional[str]:
    """
    キャッシュからセッショントークンを取得する。

    Device flow が返すトークンはセッショントークンなので、
    サーバー側でセッションの有効期限が管理される。
    セッションが無効な場合はサーバーが 401 を返す。

    Returns:
        str: Session token or None if not authenticated
    """
    cached_token = get_settings().session_token
    if cached_token:
        return cached_token

    return None
