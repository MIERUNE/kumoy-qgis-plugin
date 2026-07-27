"""ブラウザの選択中Projectノード。

選択中のProjectを1つのノードとして表し、その配下に Maps / Vectors / Rasters
のフォルダを持つ。組織直下のCatalogノードと並列に並び、サービスの階層
（Organization → {Project, Catalog}）と対応する。Projectの切り替えは
このノードの右クリックメニューから行う（処理自体はダイアログの再利用や
ブラウザ全体のリフレッシュを担うRootCollection側にある）。
"""

from qgis.core import QgsDataItem
from qgis.PyQt.QtWidgets import QAction, QMenu

from ... import i18n
from ...kumoy import api
from ..icons import BROWSER_FOLDER_ICON
from .raster import RasterRoot
from .styledmap import StyledMapRoot
from .vector import VectorRoot


class ProjectRoot(QgsDataItem):
    """選択中Projectのノード。Maps / Vectors / Rasters のフォルダを持つ。"""

    def __init__(
        self,
        parent,
        path: str,
        organization: api.organization.OrganizationDetail,
        project: api.project.ProjectDetail,
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=i18n.tr("Project: {}").format(project.name),
            path=path,
        )

        self.setIcon(BROWSER_FOLDER_ICON)
        self.organization = organization
        self.project = project
        if project.description:
            self.setToolTip(project.description)

    def actions(self, parent: QMenu) -> list[QAction]:
        # Projectの切り替え（ダイアログ管理とリフレッシュはRootCollectionが担う）
        select_project_action = QAction(i18n.tr("Select Project"), parent)
        select_project_action.triggered.connect(self.parent().select_project)
        return [select_project_action]

    def createChildren(self) -> list[QgsDataItem]:
        styled_map_root = StyledMapRoot(
            self,
            i18n.tr("Maps"),
            f"{self.path()}/styledmaps",
            self.organization,
            self.project,
        )
        styled_map_root.setSortKey(0)

        vector_root = VectorRoot(
            self,
            i18n.tr("Vectors"),
            f"{self.path()}/vectors",
            self.organization,
            self.project,
        )
        vector_root.setSortKey(1)

        raster_root = RasterRoot(
            self,
            i18n.tr("Rasters"),
            f"{self.path()}/rasters",
            self.organization,
            self.project,
        )
        raster_root.setSortKey(2)

        return [styled_map_root, vector_root, raster_root]
