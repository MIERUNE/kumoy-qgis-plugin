from qgis.core import QgsDataItem
from qgis.gui import QgsDataItemGuiContext, QgsDataItemGuiProvider
from qgis.PyQt.QtWidgets import QAction, QMenu

from ... import i18n
from ...kumoy.api.models import is_editor
from .cache_size import combined_cache_size, make_clear_cache_action
from .styledmap import StyledMapItem, clear_cache_multiple_maps, delete_multiple_maps
from .utils import ResourceItem, multi_actions


class KumoyDataItemGuiProvider(QgsDataItemGuiProvider):
    def name(self) -> str:
        return "Kumoy"

    def populateContextMenu(
        self,
        item: QgsDataItem,
        menu: QMenu,
        selectedItems: list,
        context: QgsDataItemGuiContext,
    ) -> None:
        # Only items of the clicked item's kind take part in a multi-selection
        same_kind = [i for i in selectedItems if type(i) is type(item)] or [item]
        if isinstance(item, ResourceItem):
            if len(same_kind) == 1:
                actions = item.build_actions(menu)
            else:
                actions = multi_actions(menu, same_kind)
        elif isinstance(item, StyledMapItem):
            actions = self._styled_map_actions(menu, same_kind)
        else:
            return
        for action in actions:
            menu.addAction(action)

    def _styled_map_actions(self, menu: QMenu, items: list) -> list:
        if len(items) == 1:
            return items[0].build_actions(menu)
        n = len(items)
        actions = [
            make_clear_cache_action(
                menu,
                i18n.tr("Clear Cache for {} Maps").format(n),
                lambda: combined_cache_size(items),
                lambda checked=False: clear_cache_multiple_maps(items),
            )
        ]
        if all(is_editor(i.role) for i in items):
            delete_action = QAction(i18n.tr("Delete {} Maps").format(n), menu)
            delete_action.triggered.connect(
                lambda checked=False: delete_multiple_maps(items)
            )
            actions.append(delete_action)
        return actions
