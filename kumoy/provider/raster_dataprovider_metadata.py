import re
from typing import Dict

from qgis.core import QgsProviderMetadata

from .raster_dataprovider import KumoyRasterDataProvider


class KumoyRasterProviderMetadata(QgsProviderMetadata):
    def __init__(self):
        super().__init__(
            KumoyRasterDataProvider.providerKey(),
            KumoyRasterDataProvider.description(),
            KumoyRasterDataProvider.createProvider,
        )

    def decodeUri(self, uri: str) -> Dict[str, str]:
        """``project_id=..;raster_id=..;raster_name=..`` を dict に分解する。"""
        params: Dict[str, str] = {}
        for part in uri.split(";"):
            m = re.match(r"(\w+)=(.*)", part)
            if m:
                params[m.group(1)] = m.group(2)
        return params

    def encodeUri(self, parts: Dict[str, str]) -> str:
        return ";".join(f"{key}={value}" for key, value in parts.items())
