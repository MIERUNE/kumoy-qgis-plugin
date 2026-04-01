from typing import List

from qgis.core import Qgis, QgsDataItem, QgsMessageLog
from qgis.gui import QgsDataItemGuiContext, QgsDataItemGuiProvider
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.utils import iface

from ...kumoy import api, constants, local_cache
from ...kumoy.api.error import format_api_error
from ...pyqt_version import Q_MESSAGEBOX_STD_BUTTON


class KumoyDataItemGuiProvider(QgsDataItemGuiProvider):
    def name(self) -> str:
        return "Kumoy"

    def tr(self, message: str) -> str:
        return QCoreApplication.translate("KumoyDataItemGuiProvider", message)

    def populateContextMenu(
        self,
        item: QgsDataItem,
        menu,
        selectedItems: List[QgsDataItem],
        context: QgsDataItemGuiContext,
    ) -> None:
        from .styledmap import StyledMapItem

        styled_items: List[StyledMapItem] = [
            i for i in selectedItems if isinstance(i, StyledMapItem)
        ]

        if not styled_items:
            return

        if len(styled_items) == 1:
            for action in styled_items[0]._build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection: only bulk actions
            can_delete = all(i.role in ["ADMIN", "OWNER"] for i in styled_items)
            if can_delete:
                delete_action = QAction(
                    self.tr("Delete {} Maps").format(len(styled_items)), menu
                )
                delete_action.triggered.connect(
                    lambda checked=False, items=list(styled_items): (
                        self._delete_multiple(items)
                    )
                )
                menu.addAction(delete_action)

            clear_action = QAction(
                self.tr("Clear Cache for {} Maps").format(len(styled_items)), menu
            )
            clear_action.triggered.connect(
                lambda checked=False, items=list(styled_items): (
                    self._clear_cache_multiple(items)
                )
            )
            menu.addAction(clear_action)

    def _delete_multiple(self, items) -> None:
        names = "\n".join(f"  - {i.styled_map.name}" for i in items)
        confirm = QMessageBox.question(
            None,
            self.tr("Delete Maps"),
            self.tr("Are you sure you want to delete {} maps?\n{}").format(
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
                api.styledmap.delete_styled_map(item.styled_map.id)
                deleted_count += 1
                local_cache.map.clear(item.styled_map.id)
                QgsMessageLog.logMessage(
                    f"Map '{item.styled_map.name}' deleted.",
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )
            except Exception as e:
                error_text = format_api_error(e)
                QgsMessageLog.logMessage(
                    f"Error deleting map '{item.styled_map.name}': {error_text}",
                    constants.LOG_CATEGORY,
                    Qgis.Critical,
                )
                errors.append(f"{item.styled_map.name}: {error_text}")

        if parent_item:
            parent_item.refresh()

        if errors:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Some maps could not be deleted:\n{}").format(
                    "\n".join(errors)
                ),
            )
        else:
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("{} maps have been deleted successfully.").format(
                    deleted_count
                ),
            )

    def _clear_cache_multiple(self, items) -> None:
        confirm = QMessageBox.question(
            None,
            self.tr("Clear Map Cache Data"),
            self.tr(
                "This will clear the local cache for {} maps.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(len(items)),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )
        if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return

        failed = []
        for item in items:
            if not local_cache.map.clear(item.styled_map.id):
                failed.append(item.styled_map.name)

        if failed:
            iface.messageBar().pushMessage(
                self.tr("Cache Clear Failed"),
                self.tr("Could not clear cache for: {}").format(", ".join(failed)),
            )
        else:
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("Cache cleared successfully for {} maps.").format(len(items)),
            )
