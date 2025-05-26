from datetime import datetime, timedelta
from typing import Dict, Optional

from ..settings_manager import SettingsManager
from ..ui.dialog_config import DialogConfig
from .api.auth import refresh_token


def is_token_valid(expires_at: str) -> bool:
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
        print(f"Error checking token validity: {str(e)}")
        return False


def save_token_to_cache(auth_response: Dict) -> None:
    """
    Save authentication tokens to settings cache

    Args:
        auth_response: Authentication response containing tokens
    """
    try:
        settings_manager = SettingsManager()

        # Save id token
        if "id_token" in auth_response:
            settings_manager.store_setting("id_token", auth_response["id_token"])

        # Save refresh token if available
        if "refresh_token" in auth_response:
            settings_manager.store_setting(
                "refresh_token", auth_response["refresh_token"]
            )

        # Calculate and save expiration time
        if "expires_in" in auth_response:
            # Convert expires_in (seconds) to timestamp
            expires_at = datetime.now().timestamp() + int(auth_response["expires_in"])
            expiration_datetime = datetime.fromtimestamp(expires_at)
            settings_manager.store_setting(
                "token_expires_at", expiration_datetime.isoformat()
            )
    except Exception as e:
        print(f"Error saving token to cache: {str(e)}")


def get_token() -> Optional[str]:
    """
    Get authentication token from cache or by authenticating with credentials

    Returns:
        str: Authentication token or None if authentication fails
    """
    settings_manager = SettingsManager()

    # Try to get token from cache first
    cached_token = settings_manager.get_setting("id_token")
    token_expires_at = settings_manager.get_setting("token_expires_at")

    # If we have a valid cached token, use it
    if cached_token and is_token_valid(token_expires_at):
        return cached_token

    # Try to refresh the token if we have a refresh token
    cached_refresh_token = settings_manager.get_setting("refresh_token")
    if cached_refresh_token:
        try:
            print("Attempting to refresh token...")
            refresh_response = refresh_token(cached_refresh_token)

            if refresh_response and "id_token" in refresh_response:
                # Save the refreshed token to cache
                save_token_to_cache(refresh_response)
                return refresh_response["id_token"]
            else:
                print("Token refresh failed, will try with credentials")
        except Exception as e:
            print(f"Error refreshing token: {str(e)}")

    return None
