from typing import List

from qgis.core import Qgis, QgsDataItem, QgsMessageLog, QgsProject, QgsVectorLayer
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
        from .vector import VectorItem

        styled_items: List[StyledMapItem] = [
            i for i in selectedItems if isinstance(i, StyledMapItem)
        ]
        vector_items: List[VectorItem] = [
            i for i in selectedItems if isinstance(i, VectorItem)
        ]

        if styled_items:
            self._populate_styled_map_menu(menu, styled_items)
        elif vector_items:
            self._populate_vector_menu(menu, vector_items)

    def _populate_styled_map_menu(self, menu, styled_items) -> None:
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
                        self._delete_multiple_maps(items)
                    )
                )
                menu.addAction(delete_action)

            clear_action = QAction(
                self.tr("Clear Cache for {} Maps").format(len(styled_items)), menu
            )
            clear_action.triggered.connect(
                lambda checked=False, items=list(styled_items): (
                    self._clear_cache_multiple_maps(items)
                )
            )
            menu.addAction(clear_action)

    def _populate_vector_menu(self, menu, vector_items) -> None:
        if len(vector_items) == 1:
            for action in vector_items[0]._build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection: add all to map, clear cache, and delete
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

    def _add_multiple_vectors(self, items) -> None:
        errors = []
        for item in items:
            try:
                api.vector.get_vector(item.vector.id)
                layer = QgsVectorLayer(
                    item.vector_uri, item.vector.name, constants.DATA_PROVIDER_KEY
                )
                item._set_pixel_based_style(layer)
                if layer.isValid():
                    QgsProject.instance().addMapLayer(layer)
                else:
                    errors.append(item.vector.name)
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
        else:
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("{} vectors added to map.").format(len(items)),
            )

    def _clear_cache_multiple_vectors(self, items) -> None:
        # Check if any of the vectors is currently loaded on the map
        loaded_names = []
        for item in items:
            for layer in QgsProject.instance().mapLayers().values():
                if (
                    layer.providerType() == constants.DATA_PROVIDER_KEY
                    and layer.dataProvider().vector_id == item.vector.id
                ):
                    loaded_names.append(item.vector.name)
                    break

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

        failed = []
        for item in items:
            if not local_cache.vector.clear(item.vector.id):
                failed.append(item.vector.name)

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
                api.vector.delete_vector(item.vector.id)
                deleted_count += 1

                # Remove from map if loaded
                for layer in list(QgsProject.instance().mapLayers().values()):
                    if (
                        layer.providerType() == constants.DATA_PROVIDER_KEY
                        and layer.dataProvider().vector_id == item.vector.id
                    ):
                        QgsProject.instance().removeMapLayer(layer.id())

                local_cache.vector.clear(item.vector.id)
                QgsMessageLog.logMessage(
                    f"Vector '{item.vector.name}' deleted.",
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )
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
