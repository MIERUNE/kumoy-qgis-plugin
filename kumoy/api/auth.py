"""better-auth endpoints: OAuth device authorization, token refresh and revocation."""

from dataclasses import dataclass
from typing import Optional

from . import client
from .error import AppError

CLIENT_ID = "kumoy-qgis"
# read: every GET; qgis: the writes this plugin makes; offline_access: a refresh
# token, without which the user would log in again every hour
SCOPE = "read qgis offline_access"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
TOKEN_PATH = "/api/auth/oauth2/token"


def _origin() -> dict:
    # better-auth rejects POSTs whose Origin is not a trusted origin
    return {"Origin": client.server_url()}


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_url: str
    interval: int
    expires_in: int


@dataclass
class Tokens:
    access_token: str
    refresh_token: str


def _tokens(data: object) -> Tokens:
    if (
        not isinstance(data, dict)
        or not data.get("access_token")
        or not data.get("refresh_token")
    ):
        raise AppError("Invalid response", "The server did not return tokens")
    return Tokens(data["access_token"], data["refresh_token"])


def request_device_code() -> DeviceCode:
    data = client.request(
        "POST",
        "/api/auth/device/code",
        data={"client_id": CLIENT_ID, "scope": SCOPE},
        auth=False,
        headers=_origin(),
    )
    url = data.get("verification_uri_complete") or data.get("verification_uri")
    if not data.get("device_code") or not data.get("user_code") or not url:
        raise AppError("Invalid response", "The server did not return a device code")
    return DeviceCode(
        device_code=data["device_code"],
        user_code=data["user_code"],
        verification_url=url,
        interval=int(data.get("interval") or 5),
        expires_in=int(data.get("expires_in") or 1800),
    )


def poll_device_token(device_code: str) -> Optional[Tokens]:
    """Return the tokens, or None while approval is pending.

    Raises AppError whose `error` is the OAuth error code (access_denied,
    expired_token, slow_down, ...) for anything else.
    """
    try:
        data = client.request(
            "POST",
            TOKEN_PATH,
            form={
                "grant_type": DEVICE_CODE_GRANT,
                "device_code": device_code,
                "client_id": CLIENT_ID,
            },
            auth=False,
            headers=_origin(),
        )
    except AppError as e:
        if e.error == "authorization_pending":
            return None
        raise
    return _tokens(data)


def refresh(refresh_token: str) -> Tokens:
    """Exchange the refresh token. It is single use: the server revokes the
    whole login if a used one comes back, so never run two refreshes at once."""
    data = client.request(
        "POST",
        TOKEN_PATH,
        form={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": CLIENT_ID,
        },
        auth=False,
        headers=_origin(),
    )
    return _tokens(data)


def sign_out(token: str, refresh_token: Optional[str]) -> None:
    """Revoke the login on the server so a leaked token stops working."""
    if refresh_token:
        # Revoking the refresh token also revokes the access tokens issued from it
        client.request(
            "POST",
            "/api/auth/oauth2/revoke",
            form={
                "token": refresh_token,
                "token_type_hint": "refresh_token",
                "client_id": CLIENT_ID,
            },
            auth=False,
            headers=_origin(),
        )
        return
    # A login made before OAuth: a better-auth session
    client.request(
        "POST",
        "/api/auth/sign-out",
        data={},
        auth=False,
        headers={**_origin(), "Authorization": f"Bearer {token}"},
    )
