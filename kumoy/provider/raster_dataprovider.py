"""Raster data provider for Kumoy rasters (key `kumoyraster`).

The layer stores only the Kumoy URI; the pixels come from the cached COG,
read through an inner gdal provider. A saved project therefore keeps working
after the cache is cleared or on another machine.

QGIS creates providers on project load, on every clone and possibly off the
main thread, so the constructor never blocks or shows UI. Without a cached
COG the provider is an empty *placeholder* and a background download starts;
ui/layers/raster.py reloads the layers when it is done. The placeholder is
valid on purpose: an invalid layer makes QGIS show its "unavailable layers"
dialog on project load.
"""

from typing import Optional, Tuple

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDataProvider,
    QgsProviderRegistry,
    QgsRasterBlock,
    QgsRasterDataProvider,
    QgsRectangle,
)
from qgis.PyQt import sip

from .. import constants, download, local_cache


def parse_uri(uri: str) -> Tuple[str, str, str]:
    """Split a Kumoy raster URI into (project_id, raster_id, raster_name)."""
    parts = (
        QgsProviderRegistry.instance()
        .providerMetadata(constants.RASTER_DATA_PROVIDER_KEY)
        .decodeUri(uri)
    )
    project_id = parts.get("project_id", "")
    raster_id = parts.get("raster_id", "")
    if not project_id or not raster_id:
        raise ValueError("Invalid URI. 'project_id' and 'raster_id' are required.")
    return project_id, raster_id, parts.get("raster_name", "")


class KumoyRasterDataProvider(QgsRasterDataProvider):
    def __init__(
        self,
        uri="",
        providerOptions=QgsDataProvider.ProviderOptions(),
        flags=QgsDataProvider.ReadFlags(),
        placeholder: bool = False,
    ):
        super().__init__(uri)
        self._uri = uri
        self._provider_options = providerOptions
        self._flags = flags
        self._gdal: Optional[QgsRasterDataProvider] = None
        self._is_valid = False

        self.project_id, self.raster_id, self.raster_name = parse_uri(uri)

        if placeholder:
            # A clone of a placeholder: the original already started the download
            self._is_valid = True
            return

        if not local_cache.raster.is_cached(self.raster_id):
            download.fetch_raster(self.raster_id, self.raster_name)
            self._is_valid = True
            return

        self._gdal = QgsProviderRegistry.instance().createProvider(
            "gdal",
            local_cache.raster.get_cache_path(self.raster_id),
            providerOptions,
            flags,
        )
        # A corrupt cache file makes the layer invalid; clearing the cache fixes it
        self._is_valid = self._gdal is not None and self._gdal.isValid()

    @classmethod
    def providerKey(cls) -> str:
        return constants.RASTER_DATA_PROVIDER_KEY

    @classmethod
    def description(cls) -> str:
        return constants.RASTER_DATA_PROVIDER_DESCRIPTION

    @classmethod
    def createProvider(cls, uri, providerOptions, flags=QgsDataProvider.ReadFlags()):
        return KumoyRasterDataProvider(uri, providerOptions, flags)

    def name(self) -> str:
        return self.providerKey()

    def isValid(self) -> bool:
        return self._is_valid

    def clone(self):
        """Called by the render pipeline (QgsRasterPipe copies).

        Returning a Python subclass from clone() lets C++ own an object whose
        Python overrides get garbage collected: block() then falls back to the
        base implementation (blank map) or crashes on a pure virtual call. The
        clone only has to read the same COG, so hand out the gdal provider's
        own (pure C++) clone.
        """
        if self._gdal is not None:
            return self._gdal.clone()
        cloned = KumoyRasterDataProvider(
            self._uri, self._provider_options, self._flags, placeholder=True
        )
        sip.transferto(cloned, None)  # keep the Python overrides alive for C++
        return cloned

    # --- Pure virtuals: delegate, or describe an empty raster ---------------

    def extent(self) -> QgsRectangle:
        return self._gdal.extent() if self._gdal else QgsRectangle()

    def crs(self) -> QgsCoordinateReferenceSystem:
        return self._gdal.crs() if self._gdal else QgsCoordinateReferenceSystem()

    def bandCount(self) -> int:
        return self._gdal.bandCount() if self._gdal else 1

    def dataType(self, bandNo):
        return self._gdal.dataType(bandNo) if self._gdal else Qgis.DataType.Byte

    def sourceDataType(self, bandNo):
        return self._gdal.sourceDataType(bandNo) if self._gdal else Qgis.DataType.Byte

    def xSize(self) -> int:
        # 0 marks the placeholder for ui/layers/raster.py
        return self._gdal.xSize() if self._gdal else 0

    def ySize(self) -> int:
        return self._gdal.ySize() if self._gdal else 0

    def block(self, bandNo, boundingBox, width, height, feedback=None):
        if self._gdal is None:
            empty = QgsRasterBlock(Qgis.DataType.Byte, width, height)
            empty.setIsNoData()
            return empty
        return self._gdal.block(bandNo, boundingBox, width, height, feedback)

    # --- Read-side virtuals the renderer, identify and layer properties use.
    # The placeholder falls back to the base implementations.

    def capabilities(self):
        if self._gdal is None:
            return Qgis.RasterInterfaceCapabilities()
        return self._gdal.capabilities()

    def colorInterpretation(self, bandNo):
        if self._gdal is None:
            return super().colorInterpretation(bandNo)
        return self._gdal.colorInterpretation(bandNo)

    def colorTable(self, bandNo):
        # Paletted bands render with the base class's empty table otherwise
        if self._gdal is None:
            return super().colorTable(bandNo)
        return self._gdal.colorTable(bandNo)

    def generateBandName(self, bandNo):
        if self._gdal is None:
            return super().generateBandName(bandNo)
        return self._gdal.generateBandName(bandNo)

    # The COG's internal overviews: without these the pyramids tab and
    # pyramid-aware code believe there are none
    def hasPyramids(self) -> bool:
        return self._gdal.hasPyramids() if self._gdal else False

    def buildPyramidList(self, *args):
        return self._gdal.buildPyramidList(*args) if self._gdal else []

    def sourceNoDataValue(self, bandNo):
        if self._gdal is None:
            return super().sourceNoDataValue(bandNo)
        return self._gdal.sourceNoDataValue(bandNo)

    def sourceHasNoDataValue(self, bandNo):
        if self._gdal is None:
            return super().sourceHasNoDataValue(bandNo)
        return self._gdal.sourceHasNoDataValue(bandNo)

    def useSourceNoDataValue(self, bandNo):
        if self._gdal is None:
            return super().useSourceNoDataValue(bandNo)
        return self._gdal.useSourceNoDataValue(bandNo)

    def setUseSourceNoDataValue(self, bandNo, use):
        if self._gdal is None:
            return super().setUseSourceNoDataValue(bandNo, use)
        return self._gdal.setUseSourceNoDataValue(bandNo, use)

    def userNoDataValues(self, bandNo):
        if self._gdal is None:
            return super().userNoDataValues(bandNo)
        return self._gdal.userNoDataValues(bandNo)

    def setUserNoDataValue(self, bandNo, noData):
        if self._gdal is None:
            return super().setUserNoDataValue(bandNo, noData)
        return self._gdal.setUserNoDataValue(bandNo, noData)

    def userNoDataValuesContains(self, bandNo, value):
        if self._gdal is None:
            return super().userNoDataValuesContains(bandNo, value)
        return self._gdal.userNoDataValuesContains(bandNo, value)

    def enableProviderResampling(self, enable):
        return self._gdal.enableProviderResampling(enable) if self._gdal else False

    def setZoomedInResamplingMethod(self, method):
        return self._gdal.setZoomedInResamplingMethod(method) if self._gdal else False

    def zoomedInResamplingMethod(self):
        if self._gdal is None:
            return super().zoomedInResamplingMethod()
        return self._gdal.zoomedInResamplingMethod()

    def setZoomedOutResamplingMethod(self, method):
        return self._gdal.setZoomedOutResamplingMethod(method) if self._gdal else False

    def zoomedOutResamplingMethod(self):
        if self._gdal is None:
            return super().zoomedOutResamplingMethod()
        return self._gdal.zoomedOutResamplingMethod()

    def setMaxOversampling(self, factor):
        return self._gdal.setMaxOversampling(factor) if self._gdal else False

    def maxOversampling(self):
        return self._gdal.maxOversampling() if self._gdal else super().maxOversampling()

    def identify(
        self, point, format, boundingBox=QgsRectangle(), width=0, height=0, dpi=96
    ):
        if self._gdal is None:
            return super().identify(point, format, boundingBox, width, height, dpi)
        return self._gdal.identify(point, format, boundingBox, width, height, dpi)

    def htmlMetadata(self) -> str:
        return self._gdal.htmlMetadata() if self._gdal else ""
