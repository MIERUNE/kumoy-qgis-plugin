import re
from typing import Dict

from qgis.core import QgsProviderMetadata

from .dataprovider import KumoyDataProvider


class KumoyProviderMetadata(QgsProviderMetadata):
    def __init__(self):
        super().__init__(
            KumoyDataProvider.providerKey(),
            KumoyDataProvider.description(),
            KumoyDataProvider.createProvider,
        )

    def decodeUri(self, uri: str) -> Dict[str, str]:
        """Breaks a provider data source URI into its component paths
        (e.g. API URL, table name, API key).

        :param str uri: URI to convert
        :returns: dict of components as strings
        """
        # Parse key=value pairs separated by semicolons.
        # `subset` is always the last parameter and its value may contain
        # semicolons (e.g. SQL expressions), so extract it first.
        params: Dict[str, str] = {}
        subset_prefix = ";subset="
        subset_idx = uri.find(subset_prefix)
        if subset_idx != -1:
            params["subset"] = uri[subset_idx + len(subset_prefix) :]
            uri = uri[:subset_idx]

        for part in uri.split(";"):
            m = re.match(r"(\w+)=(.*)", part)
            if m:
                params[m.group(1)] = m.group(2)
        return params

    def encodeUri(self, parts: Dict[str, str]) -> str:
        """Reassembles a provider data source URI from its component parts.

        :param Dict[str, str] parts: Parts as returned by decodeUri
        :returns: URI as string
        """
        project_id = parts.get("project_id", "")
        vector_id = parts.get("vector_id", "")
        uri = f"project_id={project_id};vector_id={vector_id}"
        subset = parts.get("subset", "")
        if subset:
            uri += f";subset={subset}"
        return uri
