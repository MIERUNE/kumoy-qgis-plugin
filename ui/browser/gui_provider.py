from typing import List

from qgis.core import Qgis, QgsDataItem, QgsMessageLog
from qgis.gui import QgsDataItemGuiContext, QgsDataItemGuiProvider
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.utils import iface

from ...kumoy import constants
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
        from .vector import VectorItem

        styledmap_items: List[StyledMapItem] = [
            i for i in selectedItems if isinstance(i, StyledMapItem)
        ]
        vector_items: List[VectorItem] = [
            i for i in selectedItems if isinstance(i, VectorItem)
        ]

        if styledmap_items:
            self._populate_styled_map_menu(menu, styledmap_items)
        elif vector_items:
            self._populate_vector_menu(menu, vector_items)

    def _populate_styled_map_menu(self, menu, styledmap_items) -> None:
        if len(styledmap_items) == 1:
            for action in styledmap_items[0]._build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection
            can_delete = all(i.role in ["ADMIN", "OWNER"] for i in styledmap_items)
            if can_delete:
                delete_action = QAction(
                    self.tr("Delete {} Maps").format(len(styledmap_items)), menu
                )
                delete_action.triggered.connect(
                    lambda checked=False, items=list(styledmap_items): (
                        self._delete_multiple_maps(items)
                    )
                )
                menu.addAction(delete_action)

            clear_action = QAction(
                self.tr("Clear Cache for {} Maps").format(len(styledmap_items)), menu
            )
            clear_action.triggered.connect(
                lambda checked=False, items=list(styledmap_items): (
                    self._clear_cache_multiple_maps(items)
                )
            )
            menu.addAction(clear_action)

    def _populate_vector_menu(self, menu, vector_items) -> None:
        if len(vector_items) == 1:
            for action in vector_items[0]._build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection
            add_action = QAction(
                self.tr("Add {} Vectors to Map").format(len(vector_items)), menu
            )
            add_action.triggered.connect(
                lambda checked=False, items=list(vector_items): (
                    self._add_multiple_vectors(items)
                )
            )
            menu.addAction(add_action)

            clear_action = QAction(
                self.tr("Clear Cache for {} Vectors").format(len(vector_items)), menu
            )
            clear_action.triggered.connect(
                lambda checked=False, items=list(vector_items): (
                    self._clear_cache_multiple_vectors(items)
                )
            )
            menu.addAction(clear_action)

            can_delete = all(i.role in ["ADMIN", "OWNER"] for i in vector_items)
            if can_delete:
                delete_action = QAction(
                    self.tr("Delete {} Vectors").format(len(vector_items)), menu
                )
                delete_action.triggered.connect(
                    lambda checked=False, items=list(vector_items): (
                        self._delete_multiple_vectors(items)
                    )
                )
                menu.addAction(delete_action)

    def _delete_multiple_maps(self, items) -> None:
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
                item.process_delete_map()
                deleted_count += 1
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

    def _clear_cache_multiple_maps(self, items) -> None:
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

        failed = [i.styled_map.name for i in items if not i.process_map_cache_clear()]

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

    def _add_multiple_vectors(self, items) -> None:
        errors = []
        for item in items:
            try:
                item.import_vector()
            except Exception as e:
                error_text = format_api_error(e)
                QgsMessageLog.logMessage(
                    f"Error adding vector '{item.vector.name}': {error_text}",
                    constants.LOG_CATEGORY,
                    Qgis.Critical,
                )
                errors.append(f"{item.vector.name}: {error_text}")

        if errors:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Some vectors could not be added:\n{}").format(
                    "\n".join(errors)
                ),
            )

    def _clear_cache_multiple_vectors(self, items) -> None:
        # Check if any of the vectors is currently loaded on the map
        loaded_names = [i.vector.name for i in items if i._is_loaded_on_map()]

        if loaded_names:
            iface.messageBar().pushMessage(
                self.tr("Cannot Clear Cache"),
                self.tr("Cannot clear cache for vectors loaded on the map: {}").format(
                    ", ".join(loaded_names)
                ),
            )
            return

        confirm = QMessageBox.question(
            None,
            self.tr("Clear Cache Data"),
            self.tr(
                "This will clear the local cache for {} vectors.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(len(items)),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )
        if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return

        failed = [i.vector.name for i in items if not i.process_vector_cache_clear()]

        if failed:
            iface.messageBar().pushMessage(
                self.tr("Cache Clear Failed"),
                self.tr("Could not clear cache for: {}").format(", ".join(failed)),
            )
        else:
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("Cache cleared successfully for {} vectors.").format(
                    len(items)
                ),
            )

    def _delete_multiple_vectors(self, items) -> None:
        names = "\n".join(f"  - {i.vector.name}" for i in items)
        confirm = QMessageBox.question(
            None,
            self.tr("Delete Vectors"),
            self.tr("Are you sure you want to delete {} vectors?\n{}").format(
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
                item.process_delete_vector()
                deleted_count += 1
            except Exception as e:
                error_text = format_api_error(e)
                QgsMessageLog.logMessage(
                    f"Error deleting vector '{item.vector.name}': {error_text}",
                    constants.LOG_CATEGORY,
                    Qgis.Critical,
                )
                errors.append(f"{item.vector.name}: {error_text}")

        if parent_item:
            parent_item.refresh()

        iface.mapCanvas().refresh()

        if errors:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Some vectors could not be deleted:\n{}").format(
                    "\n".join(errors)
                ),
            )
        else:
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("{} vectors have been deleted successfully.").format(
                    deleted_count
                ),
            )
