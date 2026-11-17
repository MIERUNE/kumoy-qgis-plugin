from typing import Dict

from qgis.core import QgsProviderMetadata

from .dataprovider import KumoyDataProvider, decode_uri, encode_uri


class KumoyProviderMetadata(QgsProviderMetadata):
    def __init__(self):
        super().__init__(
            KumoyDataProvider.providerKey(),
            KumoyDataProvider.description(),
            KumoyDataProvider.createProvider,
        )

    def decodeUri(self, uri: str) -> Dict[str, str]:
        return decode_uri(uri)

    def encodeUri(self, parts: Dict[str, str]) -> str:
        return encode_uri(parts)
