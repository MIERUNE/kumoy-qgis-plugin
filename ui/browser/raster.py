from typing import Literal

from qgis import processing
from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsMessageLog,
    QgsMimeDataUtils,
    QgsProject,
    QgsRasterLayer,
)
from qgis.PyQt.QtWidgets import QAction, QMenu, QMessageBox
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants, local_cache
from ...kumoy.api.error import UnauthorizedError, format_api_error
from ...kumoy.settings_manager import get_settings
from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from ..error_handler import handle_api_error
from ..icons import BROWSER_FOLDER_ICON, BROWSER_RASTER_ICON
from .utils import ErrorItem


class RasterItem(QgsDataItem):
    """Raster item for browser.

    マップへの追加・ダブルクリック・ドラッグドロップに対応する。実体（COG）は
    ローカルにキャッシュし、無ければ追加時にダウンロードする（ベクタと同方針）。
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
        self.raster_uri = (
            f"project_id={self.raster.projectId};"
            f"raster_id={self.raster.id};"
            f"raster_name={self.raster.name};"
        )
        self.role = role
        self.setIcon(BROWSER_RASTER_ICON)
        self.populate()  # 子を持たない葉アイテムにする

    def hasDragEnabled(self) -> bool:
        return True

    def mimeUris(self) -> list[QgsMimeDataUtils.Uri]:
        u = QgsMimeDataUtils.Uri()
        u.layerType = "raster"
        u.providerKey = constants.RASTER_DATA_PROVIDER_KEY
        u.name = self.raster.name
        u.uri = self.raster_uri
        return [u]

    def build_actions(self, parent: QMenu) -> list[QAction]:
        """Build context menu actions (used by KumoyDataItemGuiProvider)."""
        actions = []

        add_action = QAction(i18n.tr("Add to Map"), parent)
        add_action.triggered.connect(self.add_to_map)
        actions.append(add_action)

        clear_cache_action = QAction(i18n.tr("Clear Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_cache)
        actions.append(clear_cache_action)

        if self.role in ["ADMIN", "OWNER"]:
            delete_action = QAction(i18n.tr("Delete Raster"), parent)
            delete_action.triggered.connect(self.delete_raster)
            actions.append(delete_action)

        return actions

    def import_raster(self) -> None:
        """Kumoy ラスタプロバイダ経由でレイヤーをマップに追加する。

        プロバイダ生成時にキャッシュが無ければダウンロードが走る（進捗ダイアログは
        プロバイダ側が出す）。中断・失敗時は無効レイヤーになるので追加しない。
        """
        layer = QgsRasterLayer(
            self.raster_uri, self.raster.name, constants.RASTER_DATA_PROVIDER_KEY
        )
        if layer.isValid():
            QgsProject.instance().addMapLayer(layer)
        else:
            raise RuntimeError(i18n.tr("Layer is invalid: {}").format(self.raster_uri))

    def add_to_map(self) -> None:
        """Add raster layer to QGIS map"""
        try:
            self.import_raster()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=i18n.tr("Error adding raster to map"),
            )

    def handleDoubleClick(self) -> bool:
        self.add_to_map()
        return True

    def is_loaded_on_map(self) -> bool:
        """Return True if this raster is currently loaded on the QGIS map."""
        for layer in QgsProject.instance().mapLayers().values():
            if (
                layer.providerType() == constants.RASTER_DATA_PROVIDER_KEY
                and layer.dataProvider().raster_id == self.raster.id
            ):
                return True
        return False

    def process_raster_cache_clear(self) -> bool:
        return local_cache.raster.clear(self.raster.id)

    def clear_cache(self) -> None:
        """Clear cache for this specific raster"""
        if self.is_loaded_on_map():
            iface.messageBar().pushMessage(
                i18n.tr("Cannot Clear Cache"),
                i18n.tr(
                    "Cannot clear cache for raster '{}' while it is loaded on the map. "
                    "Please close the map first."
                ).format(self.raster.name),
            )
            return

        confirm = QMessageBox.question(
            None,
            i18n.tr("Clear Cache Data"),
            i18n.tr(
                "This will clear the local cache for raster '{}'.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(self.raster.name),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            if self.process_raster_cache_clear():
                iface.messageBar().pushSuccess(
                    i18n.tr("Success"),
                    i18n.tr("Cache cleared successfully for raster '{}'.").format(
                        self.raster.name
                    ),
                )
            else:
                iface.messageBar().pushMessage(
                    i18n.tr("Cache Clear Failed"),
                    i18n.tr(
                        "Cache could not be cleared for raster '{}'. "
                        "Please try again while raster is not open after restarting QGIS"
                    ).format(self.raster.name),
                )

    def process_delete_raster(self) -> None:
        """Call API to delete the raster, remove from map and clear cache."""
        api.raster.delete_raster(self.raster.id)

        # Remove from QGIS project if loaded
        for layer in list(QgsProject.instance().mapLayers().values()):
            if (
                layer.providerType() == constants.RASTER_DATA_PROVIDER_KEY
                and layer.dataProvider().raster_id == self.raster.id
            ):
                QgsProject.instance().removeMapLayer(layer.id())

        local_cache.raster.clear(self.raster.id)

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
        iface.mapCanvas().refresh()
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

        self.setIcon(BROWSER_FOLDER_ICON)
        self.organization = organization
        self.project = project

    def actions(self, parent: QMenu) -> list[QAction]:
        actions = []

        if self.project.role in ["ADMIN", "OWNER"]:
            upload_raster_action = QAction(i18n.tr("Upload Raster"), parent)
            upload_raster_action.triggered.connect(self.upload_raster)
            actions.append(upload_raster_action)

        # Clear cache action
        clear_cache_action = QAction(i18n.tr("Clear Raster Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_cache)
        actions.append(clear_cache_action)

        return actions

    def clear_cache(self) -> None:
        """Clear all raster cache data"""
        # Check if any kumoy raster layer is currently loaded on the map
        for layer in QgsProject.instance().mapLayers().values():
            if layer.providerType() == constants.RASTER_DATA_PROVIDER_KEY:
                iface.messageBar().pushMessage(
                    i18n.tr("Cannot Clear Cache"),
                    i18n.tr(
                        "Cannot clear raster cache while raster layers are loaded on the map. "
                        "Please close your map first."
                    ),
                )
                return

        confirm = QMessageBox.question(
            None,
            i18n.tr("Clear Raster Cache"),
            i18n.tr(
                "This will clear all locally cached raster files. "
                "Data will be re-downloaded next time you access rasters.\n\n"
                "Continue?"
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            cache_cleared = local_cache.raster.clear_all()

            if cache_cleared:
                QgsMessageLog.logMessage(
                    i18n.tr("All raster cache files cleared successfully."),
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )
                iface.messageBar().pushSuccess(
                    i18n.tr("Success"),
                    i18n.tr("All raster cache files have been cleared successfully."),
                )
            else:
                iface.messageBar().pushMessage(
                    i18n.tr("Raster Cache Clear Failed"),
                    i18n.tr(
                        "Some raster cache files could not be cleared. "
                        "Please try again after closing QGIS or ensure no files are locked."
                    ),
                )

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


def add_multiple_rasters(items: list[RasterItem]) -> None:
    errors = []
    for item in items:
        try:
            item.import_raster()
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error adding raster '{item.raster.name}': {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            errors.append(f"{item.raster.name}: {error_text}")

    if errors:
        QMessageBox.critical(
            None,
            i18n.tr("Error"),
            i18n.tr("Some rasters could not be added:\n{}").format("\n".join(errors)),
        )


def clear_cache_multiple_rasters(items: list[RasterItem]) -> None:
    loaded_names = [i.raster.name for i in items if i.is_loaded_on_map()]

    if loaded_names:
        iface.messageBar().pushMessage(
            i18n.tr("Cannot Clear Cache"),
            i18n.tr("Cannot clear cache for rasters loaded on the map: {}").format(
                ", ".join(loaded_names)
            ),
        )
        return

    confirm = QMessageBox.question(
        None,
        i18n.tr("Clear Cache Data"),
        i18n.tr(
            "This will clear the local cache for {} rasters.\n"
            "The cached data will be re-downloaded when you access it next time.\n"
            "Do you want to continue?"
        ).format(len(items)),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    failed = [i.raster.name for i in items if not i.process_raster_cache_clear()]

    if failed:
        iface.messageBar().pushMessage(
            i18n.tr("Cache Clear Failed"),
            i18n.tr("Could not clear cache for: {}").format(", ".join(failed)),
        )
    else:
        iface.messageBar().pushSuccess(
            i18n.tr("Success"),
            i18n.tr("Cache cleared successfully for {} rasters.").format(len(items)),
        )


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

    iface.mapCanvas().refresh()

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
