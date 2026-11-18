import webbrowser
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from qgis.core import Qgis, QgsDataItem, QgsMessageLog, QgsProject
from qgis.PyQt import sip
from qgis.PyQt.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants, local_cache, map_project
from ...kumoy.api.error import UnauthorizedError
from ...kumoy.api.models import (
    OrganizationDetail,
    ProjectDetail,
    StyledMap,
    is_editor,
)
from ...kumoy.tasks import run_task
from ...pyqt_version import (
    Q_MESSAGEBOX_STD_BUTTON,
    Q_SIZE_POLICY,
    QT_DIALOG_BUTTON_CANCEL,
    QT_DIALOG_BUTTON_OK,
    QT_TEXT_INTERACTION,
    QT_TEXTCURSOR_MOVE_OPERATION,
    exec_dialog,
)
from .. import project_storage
from ..error_handler import describe_error, handle_api_error, push_success
from ..icons import BROWSER_MAP_ICON
from .cache_size import cache_size_text, combined_cache_size, make_clear_cache_action
from .utils import ErrorItem, paged


def public_url(styled_map_id: str) -> str:
    return f"{api.client.server_url()}/public/map/{styled_map_id}"


class StyledMapItem(QgsDataItem):
    def __init__(self, parent, path: str, styled_map: StyledMap, role: str):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=styled_map.name,
            path=path,
        )
        self.styled_map = styled_map
        self.role = role
        self.setIcon(BROWSER_MAP_ICON)
        # A map has no children: populated now, so no expand arrow is shown
        self.populate(True)

    def build_actions(self, parent: QMenu) -> List[QAction]:
        """Context menu actions (used by KumoyDataItemGuiProvider)."""
        actions = []

        load_action = QAction(i18n.tr("Load into QGIS"), parent)
        load_action.triggered.connect(self.load)
        actions.append(load_action)

        if self.styled_map.isPublic:
            public_action = QAction(i18n.tr("Open Public Page"), parent)
            public_action.triggered.connect(self.open_public_page)
            actions.append(public_action)

        actions.append(
            make_clear_cache_action(
                parent,
                i18n.tr("Clear Cache Data"),
                self.cache_size,
                self.clear_map_cache,
            )
        )

        if is_editor(self.role):
            save_action = QAction(i18n.tr("Overwrite with current state"), parent)
            save_action.triggered.connect(self.overwrite)
            actions.append(save_action)

            edit_action = QAction(i18n.tr("Edit Metadata"), parent)
            edit_action.triggered.connect(self.edit_metadata)
            actions.append(edit_action)

            delete_action = QAction(i18n.tr("Delete"), parent)
            delete_action.triggered.connect(self.delete)
            actions.append(delete_action)

        return actions

    def handleDoubleClick(self) -> bool:  # noqa: N802
        self.load()
        return True

    def load(self) -> None:
        project_storage.open_map(self.styled_map.id)

    def open_public_page(self) -> None:
        webbrowser.open(public_url(self.styled_map.id))

    def overwrite(self) -> None:
        text = i18n.tr(
            "Are you sure you want to overwrite the map '{}' with the current "
            "project state?"
        ).format(self.styled_map.name)
        if not project_storage.is_open(self.styled_map.id):
            text += "\n\n" + i18n.tr(
                "The open project is then linked to this map: saving it (Ctrl+S) "
                "updates this map."
            )
        if not _confirm(i18n.tr("Save Map"), text):
            return
        project_storage.save_to_map(self.styled_map.id)

    def edit_metadata(self) -> None:
        values = _ask_map_fields(i18n.tr("Edit Map"), self.styled_map)
        if values is None:
            return
        map_id = self.styled_map.id
        was_public = self.styled_map.isPublic

        def updated(styled_map: StyledMap) -> None:
            if not sip.isdeleted(self):
                self.styled_map = styled_map
                self.setName(styled_map.name)
                self.refresh()
            if project_storage.is_open(map_id):
                # Renaming is not a save of the open project: keep its state
                project = QgsProject.instance()
                dirty = project.isDirty()
                project.setTitle(styled_map.name)
                project.setDirty(dirty)
            push_success(
                i18n.tr("Map '{}' has been updated successfully.").format(
                    styled_map.name
                )
            )
            if styled_map.isPublic and not was_public:
                show_public_url(styled_map)

        run_task(
            i18n.tr("Updating map"),
            lambda _: api.styledmap.update_styled_map(map_id, **values),
            updated,
            lambda e: handle_api_error(e, title=i18n.tr("Could not update the map")),
        )

    def delete(self) -> None:
        text = i18n.tr("Are you sure you want to delete map '{}'?").format(
            self.styled_map.name
        )
        if project_storage.is_open(self.styled_map.id):
            text += "\n\n" + _open_map_note()
        if _confirm(i18n.tr("Delete Map"), text):
            _delete_maps([self.styled_map], self.parent())

    def cache_size(self) -> int:
        return local_cache.map.get_cache_size(self.styled_map.id)

    def process_map_cache_clear(self) -> bool:
        return local_cache.map.clear(self.styled_map.id)

    def clear_map_cache(self) -> None:
        if not _confirm(
            i18n.tr("Clear Map Cache Data"),
            i18n.tr(
                "This will clear the local cache for map '{}' ({}).\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(self.styled_map.name, cache_size_text(self.cache_size)),
        ):
            return
        if self.process_map_cache_clear():
            push_success(
                i18n.tr("Cache cleared successfully for map '{}'.").format(
                    self.styled_map.name
                )
            )
        else:
            iface.messageBar().pushMessage(
                i18n.tr("Cache Clear Failed"),
                i18n.tr("Cache could not be cleared for map '{}'. ").format(
                    self.styled_map.name
                ),
            )


class StyledMapRoot(QgsDataItem):
    """The "Maps" node of a project in the Browser panel."""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        organization: OrganizationDetail,
        project: ProjectDetail,
    ):
        QgsDataItem.__init__(self, QgsDataItem.Collection, parent, name, path)
        # Set before anything can call createChildren(); children are created
        # lazily, when the node is expanded
        self.organization = organization
        self.project = project
        self.setIcon(BROWSER_MAP_ICON)

    def actions(self, parent: QMenu) -> List[QAction]:
        actions = []
        if is_editor(self.project.role):
            empty_map_action = QAction(i18n.tr("Create New Map"), parent)
            empty_map_action.triggered.connect(self.add_empty_map)
            actions.append(empty_map_action)

            save_as_action = QAction(i18n.tr("Save Current Project As..."), parent)
            save_as_action.triggered.connect(self.add_styled_map)
            actions.append(save_as_action)

        actions.append(
            make_clear_cache_action(
                parent,
                i18n.tr("Clear Map Cache Data"),
                local_cache.map.get_total_cache_size,
                self.clear_all_map_cache,
            )
        )
        return actions

    def createChildren(self) -> List[QgsDataItem]:  # noqa: N802
        # Runs in a QGIS worker thread
        try:
            styled_maps = api.styledmap.get_styled_maps(self.project.id)
        except UnauthorizedError as e:
            handle_api_error(e)
            return [ErrorItem(self, i18n.tr("Session expired - please log in"))]
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading maps: {describe_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, i18n.tr("Error loading maps"))]

        if not styled_maps:
            return [ErrorItem(self, i18n.tr("No maps available."))]
        return paged(
            self,
            styled_maps,
            lambda m: StyledMapItem(
                self, f"{self.path()}/{m.id}", m, self.project.role
            ),
        )

    def add_empty_map(self) -> None:
        values = _ask_map_fields(i18n.tr("Add Map"))
        if values is None:
            return
        # Asks to save unsaved changes first; False when canceled
        if not iface.newProject(True):
            return
        self._create_map(values)

    def add_styled_map(self) -> None:
        """Save the current project as a new map."""
        values = _ask_map_fields(i18n.tr("Add Map"))
        if values is not None:
            self._create_map(values)

    def _create_map(self, values: Dict[str, Any]) -> None:
        # The map is created empty, then saved like any map, so that the open
        # project is linked to it and saving later updates it
        empty = map_project.empty_project_xml()
        project_id = self.project.id

        def created(styled_map: StyledMap) -> None:
            if project_storage.save_to_map(styled_map.id):
                self._refresh()
                if styled_map.isPublic:
                    show_public_url(styled_map)
                return
            # Do not leave an empty map behind
            run_task(
                i18n.tr("Deleting map"),
                lambda _: api.styledmap.delete_styled_map(styled_map.id),
                lambda _: self._refresh(),
                lambda e: handle_api_error(
                    e, title=i18n.tr("Could not delete the unsaved map")
                ),
            )

        run_task(
            i18n.tr("Creating map"),
            lambda _: api.styledmap.create_styled_map(
                project_id, qgisproject=empty, **values
            ),
            created,
            lambda e: handle_api_error(e, title=i18n.tr("Could not create the map")),
        )

    def _refresh(self) -> None:
        if not sip.isdeleted(self):
            self.refresh()

    def clear_all_map_cache(self) -> None:
        if not _confirm(
            i18n.tr("Clear Map Cache"),
            i18n.tr(
                "This will clear all locally cached map files ({}). "
                "Data will be re-downloaded next time you access maps.\n\n"
                "Continue?"
            ).format(cache_size_text(local_cache.map.get_total_cache_size)),
        ):
            return
        if local_cache.map.clear_all():
            push_success(i18n.tr("All map cache files have been cleared successfully."))
        else:
            iface.messageBar().pushMessage(
                i18n.tr("Map Cache Clear Failed"),
                i18n.tr(
                    "Some map cache files could not be cleared. "
                    "Please try again after closing QGIS or ensure no files are locked."
                ),
            )


def _open_map_note() -> str:
    return i18n.tr(
        "This map is open in QGIS. The project stays open with your changes, but "
        "it is no longer saved to Kumoy: use Project > Save As to keep it."
    )


def _confirm(title: str, text: str) -> bool:
    answer = QMessageBox.question(
        None,
        title,
        text,
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    return answer == Q_MESSAGEBOX_STD_BUTTON.Yes


@dataclass
class _DeleteResult:
    deleted: List[StyledMap]
    failed: List[tuple]  # (name, reason)
    session_error: Optional[UnauthorizedError] = None


def _delete_maps(maps: List[StyledMap], parent_item: Optional[QgsDataItem]) -> None:
    def work(task) -> _DeleteResult:
        result = _DeleteResult([], [])
        for index, styled_map in enumerate(maps):
            try:
                api.styledmap.delete_styled_map(styled_map.id)
                result.deleted.append(styled_map)
            except UnauthorizedError as e:
                # Every further request would fail the same way
                result.session_error = e
                result.failed.extend(
                    (m.name, i18n.tr("not deleted: you are not logged in"))
                    for m in maps[index:]
                )
                break
            except Exception as e:
                result.failed.append((styled_map.name, describe_error(e)))
            task.setProgress(100 * (index + 1) / len(maps))
        return result

    def done(result: _DeleteResult) -> None:
        for styled_map in result.deleted:
            project_storage.unlink_map(styled_map.id)
            local_cache.map.clear(styled_map.id)
        if parent_item is not None and not sip.isdeleted(parent_item):
            parent_item.refresh()
        if result.session_error is not None:
            handle_api_error(result.session_error)
        if result.failed:
            QMessageBox.warning(
                None,
                i18n.tr("Delete Maps"),
                i18n.tr("{} of {} maps were deleted. Not deleted:\n{}").format(
                    len(result.deleted),
                    len(maps),
                    "\n".join(
                        f"  - {name}: {reason}" for name, reason in result.failed
                    ),
                ),
            )
        elif len(maps) == 1:
            push_success(
                i18n.tr("Map '{}' has been deleted successfully.").format(maps[0].name)
            )
        else:
            push_success(
                i18n.tr("{} maps have been deleted successfully.").format(len(maps))
            )

    run_task(
        i18n.tr("Deleting maps"),
        work,
        done,
        lambda e: handle_api_error(e, title=i18n.tr("Could not delete maps")),
    )


def show_public_url(styled_map: StyledMap) -> None:
    """Tell the user where the public map is, with a button to copy the link."""
    url = public_url(styled_map.id)
    box = QMessageBox(iface.mainWindow() if iface is not None else None)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(i18n.tr("Public Map"))
    box.setText(
        i18n.tr(
            "The map '{}' is public. Anyone with this link can view it:\n\n{}"
        ).format(styled_map.name, url)
    )
    box.setTextInteractionFlags(QT_TEXT_INTERACTION.TextSelectableByMouse)
    copy_button = box.addButton(i18n.tr("Copy Link"), QMessageBox.ButtonRole.ActionRole)
    open_button = box.addButton(i18n.tr("Open"), QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Close)
    exec_dialog(box)
    if box.clickedButton() is copy_button:
        QApplication.clipboard().setText(url)
        push_success(i18n.tr("Link copied to the clipboard."))
    elif box.clickedButton() is open_button:
        webbrowser.open(url)


def _ask_map_fields(
    title: str, styled_map: Optional[StyledMap] = None
) -> Optional[Dict[str, Any]]:
    """Show the map dialog; the entered fields (API names), or None if canceled."""
    dialog = QDialog(iface.mainWindow() if iface is not None else None)
    dialog.setWindowTitle(title)

    name_field = QLineEdit(styled_map.name if styled_map else "")
    name_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_NAME)

    attribution_field = QLineEdit((styled_map.attribution or "") if styled_map else "")
    attribution_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION)

    description_field = QPlainTextEdit(
        (styled_map.description or "") if styled_map else ""
    )
    description_field.setSizePolicy(Q_SIZE_POLICY.Expanding, Q_SIZE_POLICY.Expanding)

    def limit_description_length() -> None:
        text = description_field.toPlainText()
        if len(text) > constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION:
            description_field.setPlainText(
                text[: constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION]
            )
            cursor = description_field.textCursor()
            cursor.movePosition(QT_TEXTCURSOR_MOVE_OPERATION.End)
            description_field.setTextCursor(cursor)

    description_field.textChanged.connect(limit_description_length)

    is_public_field = QCheckBox(i18n.tr("Make Public"))
    is_public_field.setChecked(bool(styled_map and styled_map.isPublic))
    public_note = QLabel(
        i18n.tr(
            "Anyone with the link can view a public map, including the data of "
            "its layers, in a web browser without logging in."
        )
    )
    public_note.setWordWrap(True)

    form_layout = QFormLayout()
    form_layout.addRow(
        i18n.tr("Name:") + ' <span style="color: red;">*</span>', name_field
    )
    form_layout.addRow(i18n.tr("Description:"), description_field)
    form_layout.addRow(i18n.tr("Attribution:"), attribution_field)
    form_layout.addRow(i18n.tr("Public:"), is_public_field)
    form_layout.addRow("", public_note)

    button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)
    ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
    ok_button.setEnabled(bool(name_field.text().strip()))
    name_field.textChanged.connect(
        lambda text: ok_button.setEnabled(bool(text.strip()))
    )

    layout = QVBoxLayout()
    layout.addLayout(form_layout)
    layout.addWidget(button_box)
    dialog.setLayout(layout)

    if not exec_dialog(dialog) or not name_field.text().strip():
        return None
    return {
        "name": name_field.text().strip(),
        "description": description_field.toPlainText(),
        "attribution": attribution_field.text(),
        "isPublic": is_public_field.isChecked(),
    }


def delete_multiple_maps(items: List[StyledMapItem]) -> None:
    names = "\n".join(f"  - {i.styled_map.name}" for i in items)
    text = i18n.tr("Are you sure you want to delete {} maps?\n{}").format(
        len(items), names
    )
    if any(project_storage.is_open(i.styled_map.id) for i in items):
        text += "\n\n" + _open_map_note()
    if not _confirm(i18n.tr("Delete Maps"), text):
        return
    _delete_maps([i.styled_map for i in items], items[0].parent() if items else None)


def clear_cache_multiple_maps(items: List[StyledMapItem]) -> None:
    if not _confirm(
        i18n.tr("Clear Map Cache Data"),
        i18n.tr(
            "This will clear the local cache for {} maps ({}).\n"
            "The cached data will be re-downloaded when you access it next time.\n"
            "Do you want to continue?"
        ).format(len(items), cache_size_text(lambda: combined_cache_size(items))),
    ):
        return

    failed = [i.styled_map.name for i in items if not i.process_map_cache_clear()]
    if failed:
        iface.messageBar().pushMessage(
            i18n.tr("Cache Clear Failed"),
            i18n.tr("Could not clear cache for: {}").format(", ".join(failed)),
        )
    else:
        push_success(
            i18n.tr("Cache cleared successfully for {} maps.").format(len(items))
        )
