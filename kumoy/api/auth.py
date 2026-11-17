"""better-auth endpoints: OAuth device authorization and sign-out."""

from dataclasses import dataclass
from typing import Optional

from . import client
from .error import AppError

CLIENT_ID = "kumoy-qgis-plugin"
DEVICE_CODE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


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


def request_device_code() -> DeviceCode:
    data = client.request(
        "POST",
        "/api/auth/device/code",
        data={"client_id": CLIENT_ID},
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


def poll_device_token(device_code: str) -> Optional[str]:
    """Return the session token, or None while approval is pending.

    Raises AppError whose `error` is the OAuth error code (access_denied,
    expired_token, slow_down, ...) for anything else.
    """
    try:
        data = client.request(
            "POST",
            "/api/auth/device/token",
            data={
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
    return data.get("access_token")


def sign_out(token: str) -> None:
    """Revoke the session on the server so a leaked token stops working."""
    client.request(
        "POST",
        "/api/auth/sign-out",
        data={},
        auth=False,
        headers={**_origin(), "Authorization": f"Bearer {token}"},
    )
