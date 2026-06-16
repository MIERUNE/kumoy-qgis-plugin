from typing import Literal

from qgis import processing
from qgis.core import Qgis, QgsDataItem, QgsMessageLog
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import UnauthorizedError, format_api_error
from ...kumoy.settings_manager import get_settings
from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from ..error_handler import handle_api_error
from ..icons import BROWSER_MAP_ICON
from .utils import ErrorItem


class RasterItem(QgsDataItem):
    """Raster item for browser.

    同期ダウンロード（マップへの追加）は未対応なので、ここでは一覧表示と
    管理操作（削除）のみを提供する。
    """

    def __init__(
        self,
        parent,
        path: str,
        raster: api.raster.KumoyRaster,
        role: Literal["ADMIN", "OWNER", "MEMBER"],
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=raster.name,
            path=path,
        )

        self.raster = raster
        self.role = role
        self.setIcon(BROWSER_MAP_ICON)
        self.populate()  # 子を持たない葉アイテムにする

    def build_actions(self, parent: QMenu) -> list[QAction]:
        """Build context menu actions (used by KumoyDataItemGuiProvider)."""
        actions = []

        if self.role in ["ADMIN", "OWNER"]:
            delete_action = QAction(i18n.tr("Delete Raster"), parent)
            delete_action.triggered.connect(self.delete_raster)
            actions.append(delete_action)

        return actions

    def process_delete_raster(self) -> None:
        """Call API to delete the raster."""
        api.raster.delete_raster(self.raster.id)

    def delete_raster(self) -> None:
        confirm = QMessageBox.question(
            None,
            i18n.tr("Delete Raster"),
            i18n.tr("Are you sure you want to delete raster '{}'?").format(
                self.raster.name
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )
        if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return

        try:
            self.process_delete_raster()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error deleting raster"),
            )
            return

        self.parent().refresh()
        iface.messageBar().pushSuccess(
            i18n.tr("Success"),
            i18n.tr("Raster '{}' deleted successfully.").format(self.raster.name),
        )


class RasterRoot(QgsDataItem):
    """Root item for rasters in a project"""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        organization: api.organization.OrganizationDetail,
        project: api.project.ProjectDetail,
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=name,
            path=path,
        )

        self.setIcon(BROWSER_MAP_ICON)
        self.organization = organization
        self.project = project

    def actions(self, parent: QMenu) -> list[QAction]:
        actions = []

        if self.project.role in ["ADMIN", "OWNER"]:
            upload_raster_action = QAction(i18n.tr("Upload Raster"), parent)
            upload_raster_action.triggered.connect(self.upload_raster)
            actions.append(upload_raster_action)

        return actions

    def upload_raster(self) -> None:
        """processingを利用してラスターレイヤーをアップロード"""
        result = processing.execAlgorithmDialog("kumoy:uploadraster")
        if result:
            self.refresh()

    def createChildren(self) -> list[QgsDataItem]:
        """Create child items for rasters in project"""
        project_id = get_settings().selected_project_id

        if not project_id:
            return [ErrorItem(self, i18n.tr("No project selected"))]

        try:
            rasters = api.raster.get_rasters(project_id)
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return [ErrorItem(self, i18n.tr("Session expired - please log in"))]
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading rasters: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, i18n.tr("Error loading rasters"))]

        if len(rasters) == 0:
            return [ErrorItem(self, i18n.tr("No rasters found in this project"))]

        children = []
        for idx, raster in enumerate(rasters):
            raster_path = f"{self.path()}/raster/{raster.id}"
            raster_item = RasterItem(self, raster_path, raster, self.project.role)
            raster_item.setSortKey(idx)
            children.append(raster_item)

        return children


def delete_multiple_rasters(items: list[RasterItem]) -> None:
    names = "\n".join(f"  - {i.raster.name}" for i in items)
    confirm = QMessageBox.question(
        None,
        i18n.tr("Delete Rasters"),
        i18n.tr("Are you sure you want to delete {} rasters?\n{}").format(
            len(items), names
        ),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    errors = []
    deleted_count = 0
    parent_item = items[0].parent() if items else None

    for item in items:
        try:
            item.process_delete_raster()
            deleted_count += 1
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            break
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error deleting raster '{item.raster.name}': {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            errors.append(f"{item.raster.name}: {error_text}")

    if parent_item:
        parent_item.refresh()

    if errors:
        QMessageBox.critical(
            None,
            i18n.tr("Error"),
            i18n.tr("Some rasters could not be deleted:\n{}").format("\n".join(errors)),
        )
    else:
        iface.messageBar().pushSuccess(
            i18n.tr("Success"),
            i18n.tr("{} rasters have been deleted successfully.").format(deleted_count),
        )
