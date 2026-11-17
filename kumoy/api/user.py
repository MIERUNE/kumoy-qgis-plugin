from . import client
from .models import PublicParams, User, from_dict


def get_me() -> User:
    return from_dict(User, client.get("/user/me"))


def resolve_avatar_url(avatar_image: str) -> str:
    """External providers give absolute URLs, self-hosted storage a path."""
    if avatar_image.startswith(("http://", "https://")):
        return avatar_image
    return client.server_url().rstrip("/") + avatar_image


def get_public_params() -> PublicParams:
    data = client.request("GET", "/api/_public/params", auth=False)
    return from_dict(PublicParams, data or {})
