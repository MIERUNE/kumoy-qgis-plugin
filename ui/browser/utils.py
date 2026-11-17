"""Browser building blocks shared by the Kumoy items.

Vector and raster items behave the same (add to map, edit, delete, clear
cache, multi-selection); ResourceItem / ResourceRoot hold that behaviour and
the subclasses supply the API calls, the cache module and their texts.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple

from qgis import processing
from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsMapLayer,
    QgsMessageLog,
    QgsMimeDataUtils,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMenu,
    QVBoxLayout,
)
from qgis.utils import iface

from ... import i18n
from ...kumoy.api.error import UnauthorizedError, format_api_error
from ...kumoy.api.models import OrganizationDetail, ProjectDetail, is_editor
from ...kumoy.constants import LOG_CATEGORY
from ...kumoy.tasks import run_task
from ...pyqt_version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK, exec_dialog
from ..error_handler import describe_error, handle_api_error, push_success
from ..icons import BROWSER_FOLDER_ICON, WARNING_ICON
from ..utils import confirm, layers_of
from .cache_size import (
    cache_size_text,
    combined_cache_size,
    format_data_size,
    make_clear_cache_action,
)


class ErrorItem(QgsDataItem):
    """A message in the tree (error or empty state). Double-click retries."""

    def __init__(self, parent, message: str = "", tooltip: str = ""):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent=parent, name=message, path=""
        )
        self.setIcon(WARNING_ICON)
        if tooltip:
            self.setToolTip(tooltip)

    def handleDoubleClick(self) -> bool:
        parent = self.parent()
        if parent is not None:
            parent.refresh()
        return True


class ActionItem(QgsDataItem):
    """A leaf that runs `callback` on double-click ("Log in…", "Select project…")."""

    def __init__(self, parent, name: str, path: str, callback: Callable[[], Any]):
        QgsDataItem.__init__(
            self, QgsDataItem.Custom, parent=parent, name=name, path=path
        )
        self._callback = callback

    def handleDoubleClick(self) -> bool:
        self._callback()
        return True


def error_item(parent, message: str, e: Exception) -> ErrorItem:
    """ErrorItem for a failed load, safe to call from createChildren's thread.

    401 goes to the error handler (it ends the session and refreshes the
    Browser); anything else stays in the tree with the reason as tooltip so a
    flaky connection does not pop up dialogs while browsing.
    """
    if isinstance(e, UnauthorizedError):
        handle_api_error(e)
        return ErrorItem(parent, i18n.tr("Session expired - please log in"))
    QgsMessageLog.logMessage(
        f"{message}: {format_api_error(e)}", LOG_CATEGORY, Qgis.Warning
    )
    tooltip = describe_error(e) + "\n" + i18n.tr("Double-click to retry.")
    return ErrorItem(parent, message, tooltip)


def _refresh(item: Optional[QgsDataItem]) -> None:
    try:
        if item is not None:
            item.refresh()
    except RuntimeError:
        pass  # the Browser rebuilt the tree meanwhile


def edit_dialog(
    title: str, name: str, attribution: str, max_name: int, max_attribution: int
) -> Optional[Tuple[str, str]]:
    """Name/attribution form. Returns the new values, or None if canceled."""
    dialog = QDialog()  # no parent: freed when the function returns
    dialog.setWindowTitle(title)
    dialog.resize(400, 250)

    form_layout = QFormLayout()
    name_field = QLineEdit(name)
    name_field.setMaxLength(max_name)
    attribution_field = QLineEdit(attribution or "")
    attribution_field.setMaxLength(max_attribution)
    form_layout.addRow(
        i18n.tr("Name:") + ' <span style="color: red;">*</span>', name_field
    )
    form_layout.addRow(i18n.tr("Attribution:"), attribution_field)

    button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
    ok_button.setEnabled(bool(name.strip()))
    name_field.textChanged.connect(lambda t: ok_button.setEnabled(bool(t.strip())))

    layout = QVBoxLayout()
    layout.addLayout(form_layout)
    layout.addWidget(button_box)
    dialog.setLayout(layout)

    if not exec_dialog(dialog):
        return None
    return name_field.text().strip(), attribution_field.text()


class ResourceItem(QgsDataItem):
    """A vector or raster in the Browser. Subclasses set the class attributes
    and implement the static hooks and texts()."""

    PROVIDER_KEY = ""
    ID_KEY = ""  # URI key holding the resource id, e.g. "vector_id"
    LAYER_TYPE = ""  # mime layer type: "vector" | "raster"
    MAX_NAME = 0
    MAX_ATTRIBUTION = 0
    CACHE: Any = None  # kumoy.local_cache.vector / raster

    @staticmethod
    def api_update(resource_id: str, name: str, attribution: str) -> Any:
        raise NotImplementedError

    @staticmethod
    def api_delete(resource_id: str) -> None:
        raise NotImplementedError

    @staticmethod
    def layer_uri(resource) -> str:
        raise NotImplementedError

    def create_layer(self) -> Optional[QgsMapLayer]:
        """The layer to add, or None when the item adds it itself later."""
        raise NotImplementedError

    @staticmethod
    def texts() -> Dict[str, str]:
        raise NotImplementedError

    def __init__(self, parent, path: str, resource, role: str, icon):
        QgsDataItem.__init__(
            self, QgsDataItem.Collection, parent=parent, name=resource.name, path=path
        )
        self.resource = resource
        self.role = role
        self.setIcon(icon)
        # A leaf: marking it populated hides the expand arrow without
        # spawning a createChildren thread
        self.setState(Qgis.BrowserItemState.Populated)

    def hasDragEnabled(self) -> bool:
        return True

    def mimeUris(self) -> List[QgsMimeDataUtils.Uri]:
        u = QgsMimeDataUtils.Uri()
        u.layerType = self.LAYER_TYPE
        u.providerKey = self.PROVIDER_KEY
        u.name = self.resource.name
        u.uri = self.layer_uri(self.resource)
        return [u]

    def handleDoubleClick(self) -> bool:
        add_to_map([self])
        return True

    def build_actions(self, parent: QMenu) -> List[QAction]:
        """Context menu of a single item (used by KumoyDataItemGuiProvider)."""
        t = self.texts()
        add_action = QAction(i18n.tr("Add to Map"), parent)
        add_action.triggered.connect(lambda: add_to_map([self]))
        actions = [
            add_action,
            make_clear_cache_action(
                parent,
                i18n.tr("Clear Cache Data"),
                self.cache_size,
                lambda: clear_cache([self]),
            ),
        ]
        if is_editor(self.role):
            edit_action = QAction(t["edit"], parent)
            edit_action.triggered.connect(self.edit)
            delete_action = QAction(t["delete"], parent)
            delete_action.triggered.connect(lambda: delete([self]))
            actions += [edit_action, delete_action]
        return actions

    def layers(self) -> List[QgsMapLayer]:
        return layers_of(self.PROVIDER_KEY, self.ID_KEY, self.resource.id)

    def cache_size(self) -> int:
        return self.CACHE.get_cache_size(self.resource.id)

    def edit(self) -> None:
        values = edit_dialog(
            self.texts()["edit"],
            self.resource.name,
            self.resource.attribution or "",
            self.MAX_NAME,
            self.MAX_ATTRIBUTION,
        )
        if values is None:
            return
        name, attribution = values
        resource_id = self.resource.id
        update = self.api_update

        def on_success(updated) -> None:
            push_success(i18n.tr("'{}' has been updated.").format(updated.name))
            try:
                self.resource.name = updated.name
                self.resource.attribution = updated.attribution
                self.setName(updated.name)
                self.dataChanged.emit(self)
            except RuntimeError:
                pass  # the Browser rebuilt the tree meanwhile

        run_task(
            self.texts()["edit"],
            lambda task: update(resource_id, name, attribution),
            on_success,
            lambda e: handle_api_error(e, title=self.texts()["edit"]),
        )


def multi_actions(menu: QMenu, items: List[ResourceItem]) -> List[QAction]:
    """Context menu of several selected items of one kind."""
    t = items[0].texts()
    n = len(items)
    add_action = QAction(t["add_many"].format(n), menu)
    add_action.triggered.connect(lambda: add_to_map(items))
    actions = [
        add_action,
        make_clear_cache_action(
            menu,
            t["clear_many"].format(n),
            lambda: combined_cache_size(items),
            lambda: clear_cache(items),
        ),
    ]
    if all(is_editor(i.role) for i in items):
        delete_action = QAction(t["delete_many"].format(n), menu)
        delete_action.triggered.connect(lambda: delete(items))
        actions.append(delete_action)
    return actions


def add_to_map(items: List[ResourceItem]) -> None:
    """Add the items' layers; one message lists everything that failed."""
    errors = []
    for item in items:
        try:
            layer = item.create_layer()
            if layer is not None:
                QgsProject.instance().addMapLayer(layer)
        except Exception as e:
            if isinstance(e, UnauthorizedError):
                handle_api_error(e)
                return
            QgsMessageLog.logMessage(
                f"Error adding '{item.resource.name}': {format_api_error(e)}",
                LOG_CATEGORY,
                Qgis.Warning,
            )
            errors.append(f"{item.resource.name}: {describe_error(e)}")
    if errors and iface is not None:
        iface.messageBar().pushMessage(
            items[0].texts()["add_failed"], "; ".join(errors), Qgis.Critical, 0
        )


def clear_cache(items: List[ResourceItem]) -> None:
    loaded = [i.resource.name for i in items if i.layers()]
    if loaded:
        iface.messageBar().pushMessage(
            i18n.tr("Cannot Clear Cache"),
            i18n.tr(
                "Cannot clear the cache of data loaded on the map: {}. "
                "Remove the layers first."
            ).format(", ".join(loaded)),
            Qgis.Warning,
            10,
        )
        return
    names = ", ".join(f"'{i.resource.name}'" for i in items)
    size = cache_size_text(lambda: combined_cache_size(items))
    if not confirm(
        None,
        i18n.tr("Clear Cache Data"),
        i18n.tr(
            "This will clear the local cache for {} ({}).\n"
            "The cached data will be re-downloaded when you access it next time.\n"
            "Do you want to continue?"
        ).format(names, size),
    ):
        return
    failed = [i.resource.name for i in items if not i.CACHE.clear(i.resource.id)]
    if failed:
        iface.messageBar().pushMessage(
            i18n.tr("Cache Clear Failed"),
            i18n.tr(
                "Could not clear the cache for: {}. Please try again after "
                "restarting QGIS."
            ).format(", ".join(failed)),
            Qgis.Warning,
            10,
        )
    else:
        push_success(i18n.tr("Cache cleared for {}.").format(names))


def delete(items: List[ResourceItem]) -> None:
    """Confirm, then delete in the background.

    Stops at a 401 (the session is gone, the rest would fail too) and reports
    exactly which items were deleted and which failed.
    """
    t = items[0].texts()
    if len(items) == 1:
        text = t["confirm_delete"].format(items[0].resource.name)
    else:
        names = "\n".join(f"  - {i.resource.name}" for i in items)
        text = t["confirm_delete_many"].format(len(items), names)
    layers = [layer for i in items for layer in i.layers()]
    if layers:
        text += "\n\n" + i18n.tr(
            "{} layer(s) in the current QGIS project will be removed."
        ).format(len(layers))
        if any(isinstance(lay, QgsVectorLayer) and lay.isModified() for lay in layers):
            text += " " + i18n.tr("Their unsaved edits will be lost.")
    if not confirm(
        None, t["delete"] if len(items) == 1 else t["delete_title_many"], text
    ):
        return

    parent = items[0].parent()
    targets = [(i.resource.id, i.resource.name) for i in items]
    kind = type(items[0])
    api_delete = kind.api_delete

    def work(task):
        deleted: List[str] = []
        failed: List[Tuple[str, Exception]] = []
        for resource_id, name in targets:
            try:
                api_delete(resource_id)
                deleted.append(resource_id)
            except UnauthorizedError as e:
                return deleted, failed, e
            except Exception as e:
                failed.append((name, e))
        return deleted, failed, None

    def on_success(result) -> None:
        deleted, failed, unauthorized = result
        project = QgsProject.instance()
        for resource_id in deleted:
            for layer in layers_of(kind.PROVIDER_KEY, kind.ID_KEY, resource_id):
                project.removeMapLayer(layer.id())
            kind.CACHE.clear(resource_id)
        _refresh(parent)
        if unauthorized is not None:
            handle_api_error(unauthorized)
        if len(deleted) == len(targets):
            if len(targets) == 1:
                push_success(t["deleted"].format(targets[0][1]))
            else:
                push_success(t["deleted_many"].format(len(deleted)))
            return
        details = "; ".join(f"{name}: {describe_error(e)}" for name, e in failed)
        message = i18n.tr("Deleted {} of {}.").format(len(deleted), len(targets))
        if details:
            message += " " + details
        iface.messageBar().pushMessage(t["delete_failed"], message, Qgis.Critical, 0)

    run_task(t["delete"], work, on_success, handle_api_error)


class ResourceRoot(QgsDataItem):
    """The "Vectors" / "Rasters" folder of the selected project."""

    ITEM_CLASS: Any = ResourceItem
    UPLOAD_ALGORITHM = ""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        organization: OrganizationDetail,
        project: ProjectDetail,
    ):
        QgsDataItem.__init__(
            self, QgsDataItem.Collection, parent=parent, name=name, path=path
        )
        self.setIcon(BROWSER_FOLDER_ICON)
        self.organization = organization
        self.project = project

    @staticmethod
    def fetch(project_id: str) -> list:
        raise NotImplementedError

    def new_item(self, path: str, resource) -> ResourceItem:
        raise NotImplementedError

    def editor_actions(self, parent: QMenu) -> List[QAction]:
        return []

    def actions(self, parent: QMenu) -> List[QAction]:
        t = self.ITEM_CLASS.texts()
        actions = self.editor_actions(parent) if is_editor(self.project.role) else []
        # No size in the label: computing it walks the cache directory, which
        # would run on every right-click
        clear_action = QAction(t["clear_all"], parent)
        clear_action.triggered.connect(self.clear_cache)
        actions.append(clear_action)
        return actions

    def upload(self) -> None:
        # The tool refreshes the Kumoy Browser itself after a GUI run (see
        # processing/base.py CHANGES_RESOURCES). Refreshing here as well would
        # touch this item after that rebuild has deleted it
        processing.execAlgorithmDialog(self.UPLOAD_ALGORITHM)

    def createChildren(self) -> List[QgsDataItem]:
        # Worker thread: no widgets, no iface
        t = self.ITEM_CLASS.texts()
        try:
            resources = self.fetch(self.project.id)
        except Exception as e:
            return [error_item(self, t["load_failed"], e)]
        if not resources:
            return [ErrorItem(self, t["empty"])]
        children = []
        for key, resource in enumerate(resources):
            child = self.new_item(f"{self.path()}/{resource.id}", resource)
            child.setSortKey(key)  # keep the server's order
            children.append(child)
        return children

    def clear_cache(self) -> None:
        item_class = self.ITEM_CLASS
        t = item_class.texts()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.providerType() == item_class.PROVIDER_KEY:
                iface.messageBar().pushMessage(
                    i18n.tr("Cannot Clear Cache"),
                    t["clear_all_loaded"],
                    Qgis.Warning,
                    10,
                )
                return
        try:
            size_bytes: Optional[int] = item_class.CACHE.get_total_cache_size()
        except OSError:
            size_bytes = None  # unknown size: still let the user try
        if size_bytes == 0:
            push_success(i18n.tr("There is no cached data to clear."))
            return
        size = format_data_size(size_bytes) if size_bytes else i18n.tr("size unknown")
        if not confirm(None, t["clear_all"], t["confirm_clear_all"].format(size)):
            return
        if item_class.CACHE.clear_all():
            push_success(t["all_cleared"])
        else:
            iface.messageBar().pushMessage(
                i18n.tr("Cache Clear Failed"),
                i18n.tr(
                    "Some cache files could not be cleared. Please try again "
                    "after restarting QGIS."
                ),
                Qgis.Warning,
                10,
            )
