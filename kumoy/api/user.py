from dataclasses import dataclass
from typing import Optional

from . import config as api_config
from .client import ApiClient


@dataclass
class User:
    id: str
    name: str
    email: str
    authId: str
    avatarImage: Optional[str]
    createdAt: str
    updatedAt: str


def get_me() -> User:
    """
    Get the current user information

    Returns:
        User object or None if not found
    """
    response = ApiClient.get("/user/me")
    return User(
        id=response.get("id", ""),
        name=response.get("name", ""),
        email=response.get("email", ""),
        authId=response.get("authId", ""),
        avatarImage=response.get("avatarImage"),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )


def resolve_avatar_url(avatar_image: str) -> str:
    """Build a displayable URL from the avatarImage returned by the API"""
    # The server returns an absolute URL for external providers (Google etc.)
    # and a server-relative path for self-hosted storage
    if avatar_image.startswith(("http://", "https://")):
        return avatar_image
    return api_config.get_api_config().SERVER_URL.rstrip("/") + avatar_image
