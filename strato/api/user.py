from dataclasses import dataclass
from typing import Optional

from .client import ApiClient


@dataclass
class User:
    id: str
    name: str
    email: str
    authId: str
    avatarImage: str
    createdAt: str
    updatedAt: str


def get_me() -> Optional[User]:
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
        avatarImage=response.get("avatarImage", ""),
        createdAt=response.get("createdAt", ""),
        updatedAt=response.get("updatedAt", ""),
    )
