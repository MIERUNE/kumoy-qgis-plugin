from qgis.core import QgsDataItem
from qgis.gui import QgsDataItemGuiContext, QgsDataItemGuiProvider
from qgis.PyQt.QtWidgets import QAction, QMenu

from ... import i18n
from .raster import RasterItem, delete_multiple_rasters
from .styledmap import StyledMapItem, clear_cache_multiple_maps, delete_multiple_maps
from .vector import (
    VectorItem,
    add_multiple_vectors,
    clear_cache_multiple_vectors,
    delete_multiple_vectors,
)


class KumoyDataItemGuiProvider(QgsDataItemGuiProvider):
    def name(self) -> str:
        return "Kumoy"

    def populateContextMenu(
        self,
        item: QgsDataItem,
        menu: QMenu,
        selectedItems: list[QgsDataItem],
        context: QgsDataItemGuiContext,
    ) -> None:

        if isinstance(item, StyledMapItem):
            styledmap_items: list[StyledMapItem] = [
                i for i in selectedItems if isinstance(i, StyledMapItem)
            ]
            self._populate_styled_map_menu(menu, styledmap_items)
        elif isinstance(item, VectorItem):
            vector_items: list[VectorItem] = [
                i for i in selectedItems if isinstance(i, VectorItem)
            ]
            self._populate_vector_menu(menu, vector_items)
        elif isinstance(item, RasterItem):
            raster_items: list[RasterItem] = [
                i for i in selectedItems if isinstance(i, RasterItem)
            ]
            self._populate_raster_menu(menu, raster_items)

    def _populate_styled_map_menu(
        self, menu: QMenu, styledmap_items: list[StyledMapItem]
    ) -> None:
        if len(styledmap_items) == 1:
            for action in styledmap_items[0].build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection
            clear_action = QAction(
                i18n.tr("Clear Cache for {} Maps").format(len(styledmap_items)), menu
            )
            clear_action.triggered.connect(
                lambda checked=False, items=list(styledmap_items): (
                    clear_cache_multiple_maps(items)
                )
            )
            menu.addAction(clear_action)

            can_delete = all(i.role in ["ADMIN", "OWNER"] for i in styledmap_items)
            if can_delete:
                delete_action = QAction(
                    i18n.tr("Delete {} Maps").format(len(styledmap_items)), menu
                )
                delete_action.triggered.connect(
                    lambda checked=False, items=list(styledmap_items): (
                        delete_multiple_maps(items)
                    )
                )
                menu.addAction(delete_action)

    def _populate_raster_menu(
        self, menu: QMenu, raster_items: list[RasterItem]
    ) -> None:
        if len(raster_items) == 1:
            for action in raster_items[0].build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection
            can_delete = all(i.role in ["ADMIN", "OWNER"] for i in raster_items)
            if can_delete:
                delete_action = QAction(
                    i18n.tr("Delete {} Rasters").format(len(raster_items)), menu
                )
                delete_action.triggered.connect(
                    lambda checked=False, items=list(raster_items): (
                        delete_multiple_rasters(items)
                    )
                )
                menu.addAction(delete_action)

    def _populate_vector_menu(
        self, menu: QMenu, vector_items: list[VectorItem]
    ) -> None:
        if len(vector_items) == 1:
            for action in vector_items[0].build_actions(menu):
                menu.addAction(action)
        else:
            # Multi-selection
            add_action = QAction(
                i18n.tr("Add {} Vectors to Map").format(len(vector_items)), menu
            )
            add_action.triggered.connect(
                lambda checked=False, items=list(vector_items): add_multiple_vectors(
                    items
                )
            )
            menu.addAction(add_action)

            clear_action = QAction(
                i18n.tr("Clear Cache for {} Vectors").format(len(vector_items)), menu
            )
            clear_action.triggered.connect(
                lambda checked=False, items=list(vector_items): (
                    clear_cache_multiple_vectors(items)
                )
            )
            menu.addAction(clear_action)

            can_delete = all(i.role in ["ADMIN", "OWNER"] for i in vector_items)
            if can_delete:
                delete_action = QAction(
                    i18n.tr("Delete {} Vectors").format(len(vector_items)), menu
                )
                delete_action.triggered.connect(
                    lambda checked=False, items=list(vector_items): (
                        delete_multiple_vectors(items)
                    )
                )
                menu.addAction(delete_action)
