import re
from typing import Dict

from qgis.core import QgsProviderMetadata

from .dataprovider import StratoDataProvider


class StratoProviderMetadata(QgsProviderMetadata):
    def __init__(self):
        super().__init__(
            StratoDataProvider.providerKey(),
            StratoDataProvider.description(),
            StratoDataProvider.createProvider,
        )

    def decodeUri(self, uri: str) -> Dict[str, str]:
        """Breaks a provider data source URI into its component paths
        (e.g. API URL, table name, API key).

        :param str uri: URI to convert
        :returns: dict of components as strings
        """
        matches = re.findall(r"(\w+)=([^;]+)", uri)
        params = {key: value for key, value in matches}
        return params

    def encodeUri(self, parts: Dict[str, str]) -> str:
        """Reassembles a provider data source URI from its component parts.

        :param Dict[str, str] parts: Parts as returned by decodeUri
        :returns: URI as string
        """
        project_id = parts.get("project_id", "")
        vector_id = parts.get("vector_id", "")
        uri = f"project_id={project_id};vector_id={vector_id}"
        return uri
