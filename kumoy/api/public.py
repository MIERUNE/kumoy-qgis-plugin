from dataclasses import dataclass
from typing import Optional

from qgis.core import QgsBlockingNetworkRequest
from qgis.PyQt.QtCore import QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from . import config as api_config
from . import error as api_error
from .client import handle_blocking_reply


@dataclass
class PublicParams:
    minQgisPluginVersion: Optional[str]


def get_params() -> PublicParams:
    """Fetch public server parameters (no authentication required).

    Returns:
        PublicParams: Parsed server parameters

    Raises:
        AppError: If the server returns an HTTP error or a network error
    """
    _api_config = api_config.get_api_config()
    qurl = QUrl(f"{_api_config.SERVER_URL}/api/_public/params")

    req = QNetworkRequest(qurl)
    blocking_request = QgsBlockingNetworkRequest()
    err = blocking_request.get(req, forceRefresh=True)

    reply = blocking_request.reply()
    status_code = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
    content = handle_blocking_reply(reply.content())

    if err != QgsBlockingNetworkRequest.NoError:
        if status_code is not None:
            # HTTP error (4xx/5xx): body may contain error details
            if content:
                api_error.raise_error(content)
            api_error.raise_error(
                {
                    "message": "Application Error",
                    "error": f"Server error (HTTP {status_code})",
                }
            )
        else:
            # Network-level error (no HTTP response)
            api_error.raise_error(
                {
                    "message": "Application Error",
                    "error": blocking_request.errorMessage(),
                }
            )

    return PublicParams(
        minQgisPluginVersion=content.get("minQgisPluginVersion"),
    )
