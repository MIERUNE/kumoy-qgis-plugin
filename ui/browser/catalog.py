"""ブラウザのCatalogノード。

Catalogは組織直下のデータ束（組織横断のデータ共有）で、選択中のProjectとは
独立に、選択中のOrganizationに属するものを一覧する。各Catalogの下は
Project配下と同様に Vectors / Rasters のフォルダに分かれ、同じ操作
（マップへの追加・編集・削除・アップロードなど）ができる。role はCatalogの
所有組織でのユーザーロール（組織ADMIN/OWNER=編集可、MEMBER=閲覧のみ）。
"""

from typing import Literal

from qgis import processing
from qgis.core import Qgis, QgsDataItem, QgsMessageLog
from qgis.PyQt.QtWidgets import QAction, QMenu

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import UnauthorizedError, format_api_error
from ...kumoy.settings_manager import get_settings
from ...kumoy.upload.destinations import list_upload_destinations
from ..error_handler import handle_api_error
from ..icons import BROWSER_FOLDER_ICON
from .raster import RasterItem
from .utils import ErrorItem
from .vector import VectorItem


def _open_upload_dialog_for_catalog(
    item: QgsDataItem, catalog_id: str, algorithm_id: str
) -> None:
    """アップロードダイアログを対象Catalogを宛先の初期選択にして開く。

    アルゴリズム側も list_upload_destinations で選択肢を作り直すため、
    ここで求めたインデックスがそのまま初期選択になる。
    """
    params = {}
    try:
        for idx, destination in enumerate(list_upload_destinations()):
            if destination.kind == "CATALOG" and destination.id == catalog_id:
                params["PROJECT"] = idx
                break
    except Exception as e:
        # 初期選択の解決に失敗してもダイアログ自体は開ける
        QgsMessageLog.logMessage(
            f"Error resolving upload destination: {format_api_error(e)}",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )

    result = processing.execAlgorithmDialog(algorithm_id, params)
    if result:
        item.refresh()


class CatalogVectorRoot(QgsDataItem):
    """Catalog内のVector一覧フォルダ"""

    def __init__(
        self,
        parent,
        path: str,
        catalog: api.catalog.KumoyCatalog,
        role: Literal["ADMIN", "OWNER", "MEMBER"],
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=i18n.tr("Vectors"),
            path=path,
        )

        self.setIcon(BROWSER_FOLDER_ICON)
        self.catalog = catalog
        self.role = role

    def actions(self, parent: QMenu) -> list[QAction]:
        actions = []

        # Catalogへの書き込みは組織ADMIN/OWNERのみ
        if self.role in ["ADMIN", "OWNER"]:
            upload_vector_action = QAction(i18n.tr("Upload Vector"), parent)
            upload_vector_action.triggered.connect(self.upload_vector)
            actions.append(upload_vector_action)

        return actions

    def upload_vector(self) -> None:
        _open_upload_dialog_for_catalog(self, self.catalog.id, "kumoy:uploadvector")

    def createChildren(self) -> list[QgsDataItem]:
        try:
            detail = api.catalog.get_catalog(self.catalog.id)
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return [ErrorItem(self, i18n.tr("Session expired - please log in"))]
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading catalog: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, i18n.tr("Error loading catalog"))]

        if len(detail.vectors) == 0:
            return [ErrorItem(self, i18n.tr("No vectors found in this catalog"))]

        children = []

        # Catalog詳細のレスポンスは要約形なので、既存のVectorItemが要求する
        # dataclassへ詰め替える（attributionは含まれないため空。編集ダイアログは
        # 表示時に最新詳細を取得するので実害はない）。
        for idx, catalog_vector in enumerate(detail.vectors):
            vector = api.vector.KumoyVector(
                id=catalog_vector.id,
                name=catalog_vector.name,
                type=catalog_vector.type,
                projectId=None,
                catalogId=self.catalog.id,
                project=None,
                attribution="",
                storageUnits=catalog_vector.storageUnits,
                createdAt=catalog_vector.createdAt,
                updatedAt=catalog_vector.updatedAt,
            )
            vector_item = VectorItem(
                self, f"{self.path()}/vector/{vector.id}", vector, detail.role
            )
            vector_item.setSortKey(idx)
            children.append(vector_item)

        return children


class CatalogRasterRoot(QgsDataItem):
    """Catalog内のRaster一覧フォルダ"""

    def __init__(
        self,
        parent,
        path: str,
        catalog: api.catalog.KumoyCatalog,
        role: Literal["ADMIN", "OWNER", "MEMBER"],
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=i18n.tr("Rasters"),
            path=path,
        )

        self.setIcon(BROWSER_FOLDER_ICON)
        self.catalog = catalog
        self.role = role

    def actions(self, parent: QMenu) -> list[QAction]:
        actions = []

        # Catalogへの書き込みは組織ADMIN/OWNERのみ
        if self.role in ["ADMIN", "OWNER"]:
            upload_raster_action = QAction(i18n.tr("Upload Raster"), parent)
            upload_raster_action.triggered.connect(self.upload_raster)
            actions.append(upload_raster_action)

        return actions

    def upload_raster(self) -> None:
        _open_upload_dialog_for_catalog(self, self.catalog.id, "kumoy:uploadraster")

    def createChildren(self) -> list[QgsDataItem]:
        try:
            detail = api.catalog.get_catalog(self.catalog.id)
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return [ErrorItem(self, i18n.tr("Session expired - please log in"))]
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading catalog: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, i18n.tr("Error loading catalog"))]

        if len(detail.rasters) == 0:
            return [ErrorItem(self, i18n.tr("No rasters found in this catalog"))]

        children = []
        for idx, catalog_raster in enumerate(detail.rasters):
            raster = api.raster.KumoyRaster(
                id=catalog_raster.id,
                name=catalog_raster.name,
                projectId=None,
                catalogId=self.catalog.id,
                attribution="",
                bytes=0,
                createdAt=catalog_raster.createdAt,
                updatedAt=catalog_raster.updatedAt,
            )
            raster_item = RasterItem(
                self, f"{self.path()}/raster/{raster.id}", raster, detail.role
            )
            raster_item.setSortKey(idx)
            children.append(raster_item)

        return children


class CatalogItem(QgsDataItem):
    """単一のCatalogノード。Vectors / Rasters のフォルダを持つ。"""

    def __init__(
        self,
        parent,
        path: str,
        catalog: api.catalog.KumoyCatalog,
        role: Literal["ADMIN", "OWNER", "MEMBER"],
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=catalog.name,
            path=path,
        )

        self.setIcon(BROWSER_FOLDER_ICON)
        self.catalog = catalog
        self.role = role
        if catalog.description:
            self.setToolTip(catalog.description)

    def createChildren(self) -> list[QgsDataItem]:
        vector_root = CatalogVectorRoot(
            self, f"{self.path()}/vectors", self.catalog, self.role
        )
        vector_root.setSortKey(0)

        raster_root = CatalogRasterRoot(
            self, f"{self.path()}/rasters", self.catalog, self.role
        )
        raster_root.setSortKey(1)

        return [vector_root, raster_root]


class CatalogRoot(QgsDataItem):
    """Root item for catalogs in the selected organization"""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        organization: api.organization.OrganizationDetail,
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=name,
            path=path,
        )

        self.setIcon(BROWSER_FOLDER_ICON)
        self.organization = organization

    def createChildren(self) -> list[QgsDataItem]:
        organization_id = get_settings().selected_organization_id

        if not organization_id:
            return [ErrorItem(self, i18n.tr("No organization selected"))]

        try:
            catalogs = api.catalog.get_catalogs(organization_id)
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return [ErrorItem(self, i18n.tr("Session expired - please log in"))]
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading catalogs: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, i18n.tr("Error loading catalogs"))]

        if len(catalogs) == 0:
            return [ErrorItem(self, i18n.tr("No catalogs found in this organization"))]

        children = []
        for idx, catalog in enumerate(catalogs):
            catalog_item = CatalogItem(
                self,
                f"{self.path()}/catalog/{catalog.id}",
                catalog,
                self.organization.role,
            )
            catalog_item.setSortKey(idx)
            children.append(catalog_item)

        return children
