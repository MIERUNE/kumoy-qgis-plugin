import os

from qgis.core import Qgis, QgsProcessingProvider

from ..kumoy.constants import PLUGIN_NAME
from ..ui.icons import MAIN_ICON
from .resources.project import (
    GetProjectAlgorithm,
    ListOrganizationsAlgorithm,
    ListProjectsAlgorithm,
)
from .resources.raster import (
    AddRasterToMapAlgorithm,
    DeleteRasterAlgorithm,
    GetRasterAlgorithm,
    UpdateRasterAlgorithm,
)
from .resources.styled_map import (
    CreateMapAlgorithm,
    DeleteMapAlgorithm,
    GetMapAlgorithm,
    UpdateMapAlgorithm,
)
from .resources.vector import (
    AddVectorToMapAlgorithm,
    DeleteVectorAlgorithm,
    GetVectorAlgorithm,
    UpdateVectorAlgorithm,
)
from .upload_raster.algorithm import UploadRasterAlgorithm
from .upload_vector.algorithm import UploadVectorAlgorithm


class KumoyProcessingProvider(QgsProcessingProvider):
    """Processing provider for Kumoy plugin"""

    def __init__(self):
        super().__init__()

    def flags(self):
        """
        CompatibleWithVirtualRaster: これがないと Processing の入力UIがvirtualrasterを候補から除外してしまう
        非ファイルラスタを一括で候補に含めるため WMS/WCS 等も UI 上は選べてしまうが
        それらは algorithm 側(materialize)が実行時に明示的に弾く。
        """
        return Qgis.ProcessingProviderFlag.CompatibleWithVirtualRaster

    def id(self):
        """Unique ID for this provider"""
        return PLUGIN_NAME.lower()

    def name(self):
        """Human-readable name for this provider"""
        return PLUGIN_NAME

    def icon(self):
        """Icon for this provider"""
        return MAIN_ICON

    def loadAlgorithms(self):
        """Load algorithms"""
        self.addAlgorithm(UploadVectorAlgorithm())
        self.addAlgorithm(UploadRasterAlgorithm())
        self.addAlgorithm(ListOrganizationsAlgorithm())
        self.addAlgorithm(ListProjectsAlgorithm())
        self.addAlgorithm(GetProjectAlgorithm())
        self.addAlgorithm(GetVectorAlgorithm())
        self.addAlgorithm(AddVectorToMapAlgorithm())
        self.addAlgorithm(UpdateVectorAlgorithm())
        self.addAlgorithm(DeleteVectorAlgorithm())
        self.addAlgorithm(GetRasterAlgorithm())
        self.addAlgorithm(AddRasterToMapAlgorithm())
        self.addAlgorithm(UpdateRasterAlgorithm())
        self.addAlgorithm(DeleteRasterAlgorithm())
        self.addAlgorithm(CreateMapAlgorithm())
        self.addAlgorithm(GetMapAlgorithm())
        self.addAlgorithm(UpdateMapAlgorithm())
        self.addAlgorithm(DeleteMapAlgorithm())

    def longName(self):
        """Longer version of the provider name"""
        return self.name()
