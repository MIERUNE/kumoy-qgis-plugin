"""Kumoy maps as QGIS projects: the "kumoy" project storage.

A map is opened in QGIS as the project ``kumoy:<map id>`` (see
kumoy/map_project.py). QGIS then reads and writes it through this storage like
any other project, so Ctrl+S, the "save changes?" prompts and the recent
projects list work as usual, and saving uploads the map.

QGIS calls readProject() / writeProject() synchronously on the main thread and
waits for the result, so they block (with a busy cursor) on the network.
Saving asks questions on the way (local layer conversion, symbol embedding),
which is why this storage lives in the UI layer.

Maps opened by plugin versions before this storage are .qgs files in the old
map cache (kumoy/local_cache/map.py); opening one switches it to its URI.
"""

import io
import zipfile
from contextlib import contextmanager
from typing import Dict, List, Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsMessageLog,
    QgsProject,
    QgsProjectStorage,
)
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QApplication, QMessageBox
from qgis.utils import iface

from .. import i18n
from ..kumoy import api, local_cache, map_project, settings_manager
from ..kumoy.api.error import UnauthorizedError
from ..kumoy.api.models import StyledMapDetail, is_editor
from ..kumoy.constants import LOG_CATEGORY
from ..kumoy.sprite import (
    embed_local_symbol_files,
    embedding_size_increase,
    generate_sprite,
    local_symbol_files,
)
from ..kumoy.sprite.uploader import upload_sprites
from ..kumoy.tasks import run_task
from ..pyqt_version import Q_MESSAGEBOX_STD_BUTTON, QT_CURSOR_SHAPE
from ..qgis_version import restore_project_crs_if_invalid, restore_xyz_layer_datasources
from .error_handler import (
    describe_error,
    handle_api_error,
    push_success,
    refresh_kumoy_browser,
)
from .layers.convert import convert_local_layers


class _NotSaved(Exception):
    """The save stopped for a reason the user is told (message), or canceled."""

    def __init__(self, message: str, canceled: bool = False):
        super().__init__(message)
        self.canceled = canceled


class KumoyProjectStorage(QgsProjectStorage):
    def __init__(self):
        super().__init__()
        # Maps fetched by open_map(), handed to readProject() without a 2nd request
        self.prefetched: Dict[str, StyledMapDetail] = {}
        # Maps just read, for the readProject signal handler
        self.read_maps: Dict[str, StyledMapDetail] = {}
        # Base path for relative layer paths while a map is being read
        self.read_base: Dict[str, str] = {}
        # Local symbol files the user chose not to embed, by map URI
        self.declined_symbol_files: Dict[str, frozenset] = {}
        # Why the last write failed (None: canceled by the user)
        self.last_error: Optional[str] = None

    def type(self) -> str:
        return map_project.STORAGE_TYPE

    def listProjects(self, uri: str) -> List[str]:  # noqa: N802
        return []

    def filePath(self, uri: str) -> str:  # noqa: N802
        # Older plugin versions saved paths relative to the map's cache file, so
        # those resolve against it while reading. Otherwise "" makes QGIS write
        # absolute paths, as a map has no directory to be relative to.
        return self.read_base.get(uri, "")

    def readProject(self, uri, device, context) -> bool:  # noqa: N802
        map_id = map_project.map_id_from_uri(uri)
        if map_id is None:
            return False
        detail = self.prefetched.pop(map_id, None)
        if detail is None:
            try:
                with _busy():
                    detail = api.styledmap.get_styled_map(map_id)
            except Exception as e:
                context.pushMessage(_describe(e), Qgis.Critical)
                if isinstance(e, UnauthorizedError):
                    handle_api_error(e)
                return False

        self.read_maps[map_id] = detail
        self.read_base[uri] = local_cache.map.get_filepath(map_id)
        buffer = io.BytesIO()
        # Stored, not deflated: QGIS 3.44 failed to unzip a deflated one here
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("project.qgs", detail.qgisproject)
        device.write(buffer.getvalue())
        return True

    def writeProject(self, uri, device, context) -> bool:  # noqa: N802
        # The XML QGIS hands over (device) is not used: the project changes while
        # saving (conversion, embedding), so it is serialized again afterwards
        project = QgsProject.instance()
        map_id = map_project.map_id_from_uri(uri)
        self.last_error = None
        try:
            if map_id is None:
                raise _NotSaved(i18n.tr("Invalid Kumoy map: {}").format(uri))
            self._save(project, uri, map_id)
        except _NotSaved as e:
            if not e.canceled:
                self.last_error = str(e)
            message = str(e)
        except Exception as e:
            if isinstance(e, UnauthorizedError):
                handle_api_error(e)
            self.last_error = message = i18n.tr(
                "Could not save the map to Kumoy: {}"
            ).format(_describe(e))
        else:
            project.setDirty(False)
            return True

        QgsMessageLog.logMessage(message, LOG_CATEGORY, Qgis.Warning)
        context.pushMessage(message, Qgis.Critical)
        # QGIS has already marked the project clean, but nothing was saved
        project.setDirty(True)
        return False

    def _save(self, project: QgsProject, uri: str, map_id: str) -> None:
        with _busy():
            detail = api.styledmap.get_styled_map(map_id)
        if not is_editor(detail.role):
            raise _NotSaved(
                i18n.tr(
                    "You are a Viewer of map '{}', so you cannot save it to Kumoy. "
                    "To keep your changes, save a copy with Project > Save As."
                ).format(detail.name)
            )
        foreign = map_project.foreign_kumoy_layers(project, detail.projectId)
        if foreign:
            raise _NotSaved(
                i18n.tr(
                    "These layers belong to another Kumoy project than map '{}': "
                    "{}. A map can only use the vectors and rasters of its own "
                    "project. Remove them and save again."
                ).format(detail.name, ", ".join(foreign))
            )

        map_project.prepare(project)
        qgisproject = _serialize(project, uri)
        if self._embed_symbol_files(project, uri, len(qgisproject)):
            qgisproject = _serialize(project, uri)
        # Checked before converting, which uploads layers for nothing otherwise
        _check_size(qgisproject)

        conversion = convert_local_layers(detail.projectId)
        if conversion.cancelled:
            raise _NotSaved(
                i18n.tr(
                    "The map '{}' was not saved because converting the local "
                    "layers was canceled."
                ).format(detail.name),
                canceled=True,
            )
        if conversion.converted:
            map_project.prepare(project)
            qgisproject = _serialize(project, uri)
            _check_size(qgisproject)

        with _busy():
            sprite = generate_sprite(project)
            assets_hash = sprite.assets_hash if sprite else None
            changes = {}
            if assets_hash != detail.assetsHash:
                if sprite is not None:
                    upload_sprites(map_id, sprite)
                changes["assetsHash"] = assets_hash  # None clears the old sprite
            updated = api.styledmap.update_styled_map(
                map_id, qgisproject=qgisproject, **changes
            )

        project.setTitle(updated.name)
        show_map_save_result(updated.name, conversion.errors, conversion.skipped)
        if conversion.converted:
            # Deferred: a Browser item may have started this save
            QTimer.singleShot(0, refresh_kumoy_browser)

    def _embed_symbol_files(self, project: QgsProject, uri: str, size: int) -> bool:
        """Offer to embed local symbol files; True when they were embedded.

        Asks again only when the files differ from the ones last declined.
        """
        files = local_symbol_files(project)
        if not files or files <= self.declined_symbol_files.get(uri, frozenset()):
            return False
        # Not asked again for these files, whatever the answer
        self.declined_symbol_files[uri] = files

        if (
            size + embedding_size_increase(project)
            > api.styledmap.MAX_QGISPROJECT_LENGTH
        ):
            # Embedding would make the save fail; the size check reports a
            # project that is too large already
            if size <= api.styledmap.MAX_QGISPROJECT_LENGTH:
                QMessageBox.warning(
                    None,
                    i18n.tr("Embed Symbol Files"),
                    i18n.tr(
                        "This project contains symbols that point to files on your "
                        "computer. They will display on the Kumoy map, but other "
                        "users who open this project in QGIS will not see them."
                    ),
                )
            return False

        answer = QMessageBox.question(
            None,
            i18n.tr("Embed Symbol Files"),
            i18n.tr(
                "This project contains symbols that point to files on your computer. "
                "They will display on the Kumoy map, but other users who open this "
                "project in QGIS will not see them. Embedding the files in the project "
                "lets other users see the symbols too. "
                "Do you want to embed the files in the project?"
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.Yes,
        )
        if answer != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return False
        embed_local_symbol_files(project)
        return True

    def on_project_read(self, *_) -> None:
        """QgsProject.readProject: the layers are loaded, the read not finished."""
        project = QgsProject.instance()
        uri = project.fileName()
        map_id = map_project.map_id_from_uri(uri)
        if map_id is None:
            legacy_id = local_cache.map.legacy_map_id(uri)
            if legacy_id:
                QTimer.singleShot(0, lambda: _migrate_legacy_file(uri, legacy_id))
            return

        self.read_base.pop(uri, None)
        detail = self.read_maps.pop(map_id, None)
        if detail is None:
            return
        # What is changed here is how the map is, not unsaved changes
        dirty = project.isDirty()
        project.setTitle(detail.name)
        # Projects saved by a newer QGIS may not open cleanly in this one
        restore_project_crs_if_invalid(detail.qgisproject)
        restore_xyz_layer_datasources()
        project.setDirty(dirty)
        QTimer.singleShot(0, lambda: _offer_project_switch(detail))


_storage: Optional[KumoyProjectStorage] = None


def register() -> None:
    """Register the storage (plugin initGui)."""
    global _storage
    if _storage is not None:
        return
    _storage = KumoyProjectStorage()
    QgsApplication.projectStorageRegistry().registerProjectStorage(_storage)
    QgsProject.instance().readProject.connect(_storage.on_project_read)


def unregister() -> None:
    """Unregister the storage (plugin unload)."""
    global _storage
    if _storage is None:
        return
    try:
        QgsProject.instance().readProject.disconnect(_storage.on_project_read)
    except TypeError:
        pass
    # The registry owns and deletes the instance
    QgsApplication.projectStorageRegistry().unregisterProjectStorage(_storage)
    _storage = None


def open_map(styled_map_id: str) -> None:
    """Open the map in QGIS.

    The map is downloaded first, in the background: if that fails, the open
    project is left alone. Unsaved changes are handled by QGIS's usual prompt.
    """

    def opened(detail: StyledMapDetail) -> None:
        if _storage is None:
            return
        project = QgsProject.instance()
        # Save / Discard / Cancel; False when canceled
        if project.isDirty() and not iface.newProject(True):
            return
        _storage.prefetched[styled_map_id] = detail
        try:
            iface.addProject(map_project.map_uri(styled_map_id))
        finally:
            _storage.prefetched.pop(styled_map_id, None)

    run_task(
        i18n.tr("Loading map from Kumoy"),
        lambda _: api.styledmap.get_styled_map(styled_map_id),
        opened,
        lambda e: handle_api_error(e, title=i18n.tr("Could not open the map")),
    )


def is_open(styled_map_id: str) -> bool:
    return QgsProject.instance().fileName() == map_project.map_uri(styled_map_id)


def save_to_map(styled_map_id: str) -> bool:
    """Save the open project to the map, which it is then linked to.

    On failure the project keeps its previous link and its unsaved changes,
    and the user is told why (nothing when they canceled).
    """
    project = QgsProject.instance()
    previous = project.fileName()
    if project.write(map_project.map_uri(styled_map_id)):
        return True
    # QgsProject.write() has already switched the project to the new URI
    project.setFileName(previous)
    project.setDirty(True)
    error = _storage.last_error if _storage is not None else project.error()
    if error and iface is not None:
        iface.messageBar().pushMessage(i18n.tr("Map not saved"), error, Qgis.Warning, 0)
    return False


def unlink_map(styled_map_id: str) -> None:
    """Detach the open project from a deleted map; it stays open, unsaved."""
    if not is_open(styled_map_id):
        return
    project = QgsProject.instance()
    was_dirty = project.isDirty()
    # Saving now asks where to save, instead of failing against a missing map
    project.setFileName("")
    project.setDirty(was_dirty)


def show_map_save_result(
    map_name: str,
    conversion_errors: List[tuple],
    skipped_layers: Optional[List[str]] = None,
) -> None:
    """Report a save: message bar, or a dialog when layers were not converted."""
    warnings = []
    if skipped_layers:
        warnings.append(
            i18n.tr(
                "Upload was cancelled: {} layers were not converted and remain local."
            ).format(len(skipped_layers))
        )
    if conversion_errors:
        details = "\n".join(f"• {name}\n{error}\n" for name, error in conversion_errors)
        if len(details) > 1000:
            details = details[:1000] + "..."
        warnings.append(
            i18n.tr("Warning: {} layers could not be converted:\n\n{}").format(
                len(conversion_errors), details
            )
        )

    message = i18n.tr("Map '{}' has been saved successfully.").format(map_name)
    if warnings:
        QMessageBox.warning(
            None,
            i18n.tr("Map Saved with Warnings"),
            message + "\n\n" + "\n\n".join(warnings),
        )
    else:
        push_success(message)


def _describe(e: Exception) -> str:
    if isinstance(e, UnauthorizedError):
        return i18n.tr(
            "You are not logged in to Kumoy, or your session has expired. Log in "
            "from the Kumoy item in the Browser panel and try again."
        )
    return describe_error(e)


@contextmanager
def _busy():
    QApplication.setOverrideCursor(QT_CURSOR_SHAPE.WaitCursor)
    try:
        yield
    finally:
        QApplication.restoreOverrideCursor()


def _serialize(project: QgsProject, uri: str) -> str:
    try:
        return map_project.write_xml(project)
    finally:
        # write_xml() pointed the project at its temporary file
        project.setFileName(uri)


def _check_size(qgisproject: str) -> None:
    error = map_project.size_error(qgisproject)
    if error:
        raise _NotSaved(error)


def _offer_project_switch(detail: StyledMapDetail) -> None:
    """Offer to select the map's project when another one is selected.

    New maps are created in the selected project, and its layers are listed in
    the Browser panel, so working on a map of another project is confusing.
    """
    kumoy_project = detail.project
    if (
        kumoy_project is None
        or kumoy_project.team is None
        or detail.projectId == settings_manager.selected_project_id()
        or not is_open(detail.id)
    ):
        return
    answer = QMessageBox.question(
        iface.mainWindow() if iface is not None else None,
        i18n.tr("Different Kumoy Project"),
        i18n.tr(
            "The map '{}' belongs to the Kumoy project '{}', which is not the "
            "project selected in the Browser panel.\n\n"
            "Select '{}' in the Browser panel?"
        ).format(detail.name, kumoy_project.name, kumoy_project.name),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.Yes,
    )
    if answer == Q_MESSAGEBOX_STD_BUTTON.Yes:
        settings_manager.select_project(
            kumoy_project.team.organizationId, detail.projectId
        )
        refresh_kumoy_browser()


def _migrate_legacy_file(path: str, map_id: str) -> None:
    """Link a map file of the old cache to its map, then reload it from Kumoy.

    Linked first so that saving uploads the map even if the reload fails; the
    reload gets changes others saved since the file was written.
    """
    project = QgsProject.instance()
    if project.fileName() != path:
        return
    project.setFileName(map_project.map_uri(map_id))
    project.setDirty(False)
    QgsMessageLog.logMessage(
        f"Opened the old map cache file {path}; switched to map {map_id}",
        LOG_CATEGORY,
        Qgis.Info,
    )
    open_map(map_id)
