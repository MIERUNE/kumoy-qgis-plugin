"""E2E test script for the Kumoy QGIS plugin.

This script exercises the full happy-path user workflow against a real Kumoy
server, from the QGIS Python console. It complements the pytest-qgis tests
in ``tests/`` (which run headless against mocks) by validating the real
plumbing end-to-end: auth flow, provider, Processing, save hook, API roundtrips.

How to run
----------
1. Open QGIS with the Kumoy plugin loaded.
2. From the QGIS Python console::

       exec(open("/abs/path/to/kumoy-qgis-plugin/scripts/e2e_qgis_console.py").read())

   A configuration dialog opens on each run. Fields are persisted to QSettings,
   so they're pre-filled on subsequent runs. If you have an unsaved project,
   the script asks whether to save / discard / cancel before replacing it.

What the script does
--------------------
0. Pre-flight: ask for config via dialog, validate, clear the current session.
1. Login: AuthManager device flow. Token is persisted via settings_manager.
   Post-login, ``api.user.get_me().email`` is checked against the email
   entered in the dialog to prevent running against the wrong account.
   No server resource is created if this check fails.
2. Server setup (via API direct, as setup): look up the team by ID (the
   organization is derived from it), then create a project and an empty
   styled map, both named ``__E2E_TEST__<timestamp>``.
3. Open map in QGIS: reproduce ``apply_style`` from ``ui/browser/styledmap.py``
   — write the project file to the local cache, ``iface.addProject``,
   set ``kumoy_map_id`` custom variable.
4. Add local layers: OSM XYZ basemap + memory polygons + lines + points,
   ordered so points render on top.
5. Save: monkey-patch the modal dialogs that ``handle_project_saved`` /
   ``convert_local_layers`` would normally open, then call ``QgsProject.write()``
   to fire ``projectSaved``. The full hook chain runs: vectors are converted
   and uploaded via ``convert_to_kumoy``, then ``update_styled_map`` pushes
   the resulting .qgs back to the server.
6. Verify via API direct: at least 3 vectors uploaded (points + lines +
   polygons), styled map qgisproject references Kumoy layers and preserves
   the OSM basemap.
7. Read back through the Kumoy vector provider: open each uploaded vector as a
   ``QgsVectorLayer``, and check feature counts, the feature iterator, geometry
   and attribute roundtrips, a bbox-filtered request and a subset string.
8. Edit features through the provider: add / move / re-attribute / delete a
   feature and add / delete an attribute in real QGIS edit sessions, verifying
   each commit against the server (this also exercises the cache diff sync
   and the column-order cache recreation path).
9. Sprite: put a star marker on the Kumoy point layer, re-save, and check the
   styled map's ``assetsHash`` changed (i.e. sprites were regenerated and
   uploaded).
10. Reopen roundtrip: clear QGIS, re-download the saved .qgs and load it —
    every layer must resolve, including the Kumoy ones and the OSM basemap.
11. Raster: build a small GeoTIFF, upload it with the ``kumoy:uploadraster``
    Processing algorithm (COG conversion + presigned upload), read it back
    through the Kumoy raster provider and check a pixel value, then clear the
    cache and re-open to exercise the download path.
12. Metadata: organization usage / planSettings consistency, teams, projects,
    public params, renaming every resource type, and deleting a raster and a
    vector (verifying they disappear from the listings).
13. Cleanup: delete the project (cascade), clear local caches, logout.

Cleanup robustness
------------------
The cleanup phase is in a ``finally`` block so it runs even if a previous phase
failed. Leftovers can be identified by the ``__E2E_TEST__`` prefix (or
``__E2E_REN__`` if the run got as far as the rename phase) and removed manually
if necessary.

Design notes
------------
- Vectors and styled maps are created via plugin entry points where it makes
  sense (Processing algo + save hook), via API direct otherwise (project create,
  empty styled map create). See ``CLAUDE.md`` / GitHub issue #391 for context.
- Monkey-patching dialogs is intrusive but pragmatic: a future refactor that
  extracts the non-UI logic of ``handle_project_saved`` would make it
  unnecessary. That refactor is out of scope for this script.
- Warning/critical message boxes are recorded instead of shown during a save:
  they are modal, so an unnoticed one would hang the run. A recorded critical
  fails the phase, which is what we want — the plugin only shows one when the
  save actually went wrong.
- This script is meant to be run interactively by a developer. It is NOT
  automated in CI: the OAuth flow requires a real human in a real browser.

- New string fields are requested with ``MAX_CHARACTERS_STRING_FIELD`` as their
  length, because that is what the provider advertises for Varchar in its
  native types (``minLen == maxLen``) and reports back from ``fields()``. QGIS
  compares the requested field against the provider's after ``addAttributes()``,
  so any other length fails the commit with "field with index N is not the
  same!". The Fields dialog pins the length to the same value, so this matches
  what a user actually does.
"""

import importlib
import os
import sys
import tempfile
from datetime import datetime

from qgis import processing
from qgis.core import (
    Qgis,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsMarkerSymbol,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsSingleSymbolRenderer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEventLoop, QSettings, QUrl, QVariant
from qgis.PyQt.QtGui import QDesktopServices
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
from qgis.utils import iface

# ─── Settings persistence ──────────────────────────────────────────────────
# Values are gathered via a Qt dialog at startup and persisted to QSettings,
# so they're pre-filled on subsequent runs. No editing of the script needed.
_E2E_SETTINGS_GROUP = "/KumoyE2ETest"


# ─── Plugin module discovery ───────────────────────────────────────────────
# The plugin folder's name on disk depends on how it was installed (zip name,
# repo clone, symlink, ...), so we don't hardcode it. Instead we look for the
# `KumoyPlugin` class in sys.modules.


def _find_plugin_package():
    for mod_name, mod in list(sys.modules.items()):
        if mod is None:
            continue
        if mod_name.endswith(".plugin") and hasattr(mod, "KumoyPlugin"):
            return mod_name.rsplit(".", 1)[0]
    return None


_PLUGIN_PACKAGE = _find_plugin_package()
if not _PLUGIN_PACKAGE:
    raise RuntimeError(
        "Kumoy plugin not found in sys.modules. "
        "Make sure the plugin is loaded (Plugins → Manage and Install Plugins)."
    )


def _imp(submodule):
    return importlib.import_module(f"{_PLUGIN_PACKAGE}.{submodule}")


api = _imp("kumoy.api")
constants = _imp("kumoy.constants")
settings_manager = _imp("kumoy.settings_manager")
auth_module = _imp("kumoy.auth_manager")
cache_map_module = _imp("kumoy.local_cache.map")
cache_vector_module = _imp("kumoy.local_cache.vector")
cache_raster_module = _imp("kumoy.local_cache.raster")
raster_algorithm_module = _imp("processing.upload_raster.algorithm")
pyqt_version_module = _imp("pyqt_version")
convert_local_module = _imp("ui.layers.convert")
dialog_layer_select_module = _imp("ui.dialog_layer_select")

LayerSelectDialog = dialog_layer_select_module.LayerSelectDialog
QDIALOG_CODE = pyqt_version_module.QDIALOG_CODE
Q_MESSAGEBOX_STD_BUTTON = pyqt_version_module.Q_MESSAGEBOX_STD_BUTTON
QT_DIALOG_BUTTON_OK = pyqt_version_module.QT_DIALOG_BUTTON_OK
QT_DIALOG_BUTTON_CANCEL = pyqt_version_module.QT_DIALOG_BUTTON_CANCEL


# ─── Test data ─────────────────────────────────────────────────────────────
# Shared by the layer-creation phase and every later verification, so the
# expected counts / coordinates can't drift apart.
POINT_COORDS = [
    (139.70, 35.70),
    (139.80, 35.65),
    (139.75, 35.68),
    (139.72, 35.72),
    (139.78, 35.69),
]
LINE_COORDS = [
    ((139.70, 35.70), (139.80, 35.70)),
    ((139.75, 35.65), (139.75, 35.75)),
]
POLYGON_RING = [
    (139.70, 35.65),
    (139.80, 35.65),
    (139.75, 35.75),
    (139.70, 35.65),
]

POINTS_LAYER_NAME = "e2e_points"
LINES_LAYER_NAME = "e2e_lines"
POLYGONS_LAYER_NAME = "e2e_polygons"
BASEMAP_LAYER_NAME = "OpenStreetMap"
RASTER_LAYER_NAME = "e2e_raster"

# name -> (server geometry type, expected feature count)
EXPECTED_VECTORS = {
    POINTS_LAYER_NAME: ("POINT", len(POINT_COORDS)),
    LINES_LAYER_NAME: ("LINESTRING", len(LINE_COORDS)),
    POLYGONS_LAYER_NAME: ("POLYGON", 1),
}

# Feature added / moved in the editing phase.
ADDED_POINT = (139.76, 35.71)
MOVED_POINT = (139.71, 35.74)
ADDED_POINT_NAME = "e2e_added"
RENAMED_POINT_NAME = "e2e_renamed"
EXTRA_FIELD_NAME = "e2e_extra"

# Test raster: 64x64 single band, pixel value = (col + row) % 256, 0.001° per
# pixel with its top-left corner north-west of the vector test data.
RASTER_SIZE = 64
RASTER_ORIGIN = (139.70, 35.75)
RASTER_PIXEL_SIZE = 0.001
RASTER_PROBE_COL_ROW = (10, 20)


# ─── Errors ────────────────────────────────────────────────────────────────
class E2EUserError(Exception):
    """Raised for known/expected user-facing errors (bad config, wrong account, …).

    All errors are shown as a clean one-line message in ``_run()``; the
    traceback is suppressed for both user errors and unexpected ones to keep
    the console output readable. To get a traceback for debugging, run the
    failing phase in isolation from the Python console.
    """


# ─── Output helpers ────────────────────────────────────────────────────────
def _phase(num, title):
    print()
    print(f"═══ PHASE {num} : {title} ═══")


def _step(msg):
    print(f"  {msg}")


def _ok(msg):
    print(f"  ✓ {msg}")


# ─── Configuration dialog ──────────────────────────────────────────────────
def _gather_config():
    """Show a single Qt form dialog asking for the E2E config.

    Values are read from / written back to QSettings under
    ``_E2E_SETTINGS_GROUP``, so the dialog is pre-filled on subsequent runs.

    Returns a dict with keys: email, team_id, custom_server.
    The organization is derived from the team in phase 2.
    Raises E2EUserError if the user cancels.
    """
    settings = QSettings()
    settings.beginGroup(_E2E_SETTINGS_GROUP)
    defaults = {
        "email": settings.value("email", "", type=str),
        "team_id": settings.value("team_id", "", type=str),
        "custom_server": settings.value("custom_server", "", type=str),
    }
    settings.endGroup()

    dialog = QDialog(iface.mainWindow() if iface else None)
    dialog.setWindowTitle("Kumoy E2E test configuration")
    dialog.setMinimumWidth(500)

    layout = QVBoxLayout(dialog)
    intro = QLabel(
        "⚠️ The test will create and delete resources under the team "
        "specified below. The organization is derived from the team."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    form = QFormLayout()
    email_field = QLineEdit(defaults["email"])
    email_field.setPlaceholderText("you@example.com")
    team_id_field = QLineEdit(defaults["team_id"])
    team_id_field.setPlaceholderText("Team ID (from the Kumoy web UI)")
    custom_server_field = QLineEdit(defaults["custom_server"])
    custom_server_field.setPlaceholderText("Leave empty to use the default server")

    form.addRow("User email*", email_field)
    form.addRow("Team ID*", team_id_field)
    form.addRow("Custom server URL", custom_server_field)
    layout.addLayout(form)

    buttons = QDialogButtonBox(
        QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL,
        parent=dialog,
    )
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    layout.addWidget(buttons)

    result = pyqt_version_module.exec_dialog(dialog)
    if result != QDIALOG_CODE.Accepted:
        raise E2EUserError("Configuration cancelled by user")

    config = {
        "email": email_field.text().strip(),
        "team_id": team_id_field.text().strip(),
        "custom_server": custom_server_field.text().strip(),
    }

    # Persist for next run, even if validation later fails. Otherwise users
    # would re-type everything when they fix a typo.
    settings.beginGroup(_E2E_SETTINGS_GROUP)
    for k, v in config.items():
        settings.setValue(k, v)
    settings.endGroup()

    return config


def _handle_unsaved_current_project():
    """If the current QGIS project has unsaved changes, let the user save or
    discard them before the script clears the project. Cancel aborts the run.

    We do this AFTER the config dialog (so cancelling the config doesn't
    trigger a save prompt for nothing) and BEFORE phase 0.
    """
    project = QgsProject.instance()
    if not project.isDirty():
        return

    buttons = (
        Q_MESSAGEBOX_STD_BUTTON.Save
        | Q_MESSAGEBOX_STD_BUTTON.Discard
        | Q_MESSAGEBOX_STD_BUTTON.Cancel
    )
    default_button = Q_MESSAGEBOX_STD_BUTTON.Cancel  # safest if user hits Enter
    response = QMessageBox.question(
        iface.mainWindow() if iface else None,
        "Kumoy E2E test",
        "Your current QGIS project has unsaved changes. The E2E test will "
        "replace it. What do you want to do?",
        buttons,
        default_button,
    )

    if response == Q_MESSAGEBOX_STD_BUTTON.Cancel:
        raise E2EUserError("Cancelled by user (unsaved project).")
    if response == Q_MESSAGEBOX_STD_BUTTON.Save:
        # Trigger QGIS's native save action. If the project has no file path
        # yet, this opens the standard "Save As" dialog.
        if iface is not None:
            iface.actionSaveProject().trigger()
        # If the user cancelled the Save As dialog, the project is still dirty.
        if project.isDirty():
            raise E2EUserError("Save cancelled — aborting test.")


# ─── Phase 0 : Pre-flight ──────────────────────────────────────────────────
def phase_0_preflight(config):
    _phase(0, "Pre-flight")

    # Strict config validation. The email check post-login is the safety net
    # that prevents the script from running against the wrong account, so it
    # cannot be skipped.
    if not config["email"]:
        raise E2EUserError(
            "Email is required — set it in the configuration dialog. "
            "It's the safety check that prevents writing to the wrong account."
        )
    if not config["team_id"]:
        raise E2EUserError("Team ID is required.")

    # Custom server is auto-detected from the URL field: filled = use it,
    # empty = use the plugin's default.
    if config["custom_server"]:
        if not config["custom_server"].startswith(("http://", "https://")):
            raise E2EUserError(
                f"Custom server URL must start with http:// or https:// "
                f"(got {config['custom_server']!r})"
            )
        settings_manager.store_setting("use_custom_server", "true")
        settings_manager.store_setting("custom_server_url", config["custom_server"])
    else:
        settings_manager.store_setting("use_custom_server", "false")

    server_url = api.config.get_api_config().SERVER_URL
    _step(f"Server URL    : {server_url}")
    _step(f"Expected email: {config['email']}")
    _step(f"Team ID       : {config['team_id']}")

    # Wipe the current QGIS-side session so we exercise the real login.
    # If the wrong account is used during login, phase 1 will refuse to
    # continue (via the email check) — no resources are created in that case.
    settings_manager.store_setting("session_token", "")
    _ok("Cleared QGIS session token")

    return server_url


# ─── Phase 1 : Login ───────────────────────────────────────────────────────
def phase_1_login(config, server_url, state):
    _phase(1, "Login")

    auth = auth_module.AuthManager(server_url)

    _step("Requesting device code...")
    ok, code_or_err = auth.request_device_code()
    if not ok:
        raise RuntimeError(f"request_device_code failed: {code_or_err}")
    _ok(f"User code: {code_or_err}")

    verification_url = auth.get_verification_url()
    _step(f"Verification URL: {verification_url}")
    _step("Opening URL in your default browser — confirm the code on the page.")
    QDesktopServices.openUrl(QUrl(verification_url))

    # Wait for the polling to complete using a QEventLoop driven by the signal.
    _step("Polling for token (timeout depends on server, typically ~30 min)...")
    loop = QEventLoop()
    result = {"success": False, "error": ""}

    def _on_completed(success, error):
        result["success"] = success
        result["error"] = error
        loop.quit()

    auth.auth_completed.connect(_on_completed)
    auth.start_polling()
    pyqt_version_module.exec_event_loop(loop)

    if not result["success"]:
        raise RuntimeError(f"Login failed: {result['error']}")

    settings_manager.store_setting("session_token", auth.get_access_token())
    state["session_logged_in"] = True
    _ok("Token persisted to QSettings")

    # Identity check — refuses to continue if the wrong account was used.
    # Compare case-insensitively since the server may normalize emails and
    # we don't want to abort over "Foo@bar.com" vs "foo@bar.com".
    me = api.user.get_me()
    _ok(f"Authenticated as: {me.email} (id={me.id})")
    if me.email.lower() != config["email"].lower():
        raise E2EUserError(
            f"Wrong account! Got {me.email!r}, expected {config['email']!r}. "
            "Aborting before touching any resource."
        )
    return me


# ─── Phase 2 : Server setup ────────────────────────────────────────────────
def phase_2_setup(config, timestamp, state):
    _phase(2, "Server setup")

    # Look up the team directly by ID. The response embeds the organization
    # so we don't need a separate org lookup. The API returns 401/403 if the
    # user has no access, which surfaces as UnauthorizedError.
    try:
        team = api.team.get_team(config["team_id"])
    except Exception as e:
        raise E2EUserError(f"Could not access team {config['team_id']!r}: {e}") from e
    org = team.organization
    state["organization_id"] = org.id
    _ok(f"Using organization: {org.name} (id={org.id})")
    _ok(f"Using team        : {team.name} (id={team.id}, role={team.role})")
    if team.role == "MEMBER":
        # MEMBER role typically can't create projects on Kumoy. Warn upfront
        # so the user can pick a different team if needed.
        print(
            f"  ⚠ Your role in team {team.name!r} is MEMBER — project creation "
            "will likely fail. Use a team where you are OWNER or ADMIN."
        )

    project_name = f"__E2E_TEST__{timestamp}"
    _step(f"Creating project: {project_name}")
    project = api.project.create_project(
        team.id, project_name, "Created by scripts/e2e_qgis_console.py"
    )
    state["project"] = project
    _ok(f"Project created: id={project.id}")

    # We need a valid (empty) QGIS project XML to bootstrap the styled map.
    # Easiest way: clear, write to a temp file, read it back. About to mutate
    # the user's current QGIS project — track it for cleanup.
    state["qgis_project_touched"] = True
    QgsProject.instance().clear()
    tmp = tempfile.NamedTemporaryFile(suffix=".qgs", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        if not QgsProject.instance().write(tmp_path):
            raise RuntimeError(
                f"QgsProject.write({tmp_path!r}) returned False — "
                "could not bootstrap the empty styled map."
            )
        with open(tmp_path, "r", encoding="utf-8") as f:
            empty_qgs = f.read()
    finally:
        # Best-effort cleanup of the temp file. A leftover .qgs in /tmp is
        # harmless, so we log and continue rather than aborting.
        try:
            os.unlink(tmp_path)
        except OSError as e:
            print(f"  ⚠ Could not remove temp file {tmp_path}: {e}")

    map_name = f"__E2E_TEST__{timestamp}"
    _step(f"Creating empty styled map: {map_name}")
    styled_map = api.styledmap.add_styled_map(
        project.id,
        api.styledmap.AddStyledMapOptions(
            name=map_name,
            qgisproject=empty_qgs,
        ),
    )
    _ok(f"Styled map created: id={styled_map.id}")

    # Update the active selection so the rest of the plugin code sees this
    # project/org. (Mostly defensive — the save hook reads kumoy_map_id from
    # custom variables anyway.)
    settings_manager.store_setting("selected_organization_id", org.id)
    settings_manager.store_setting("selected_project_id", project.id)

    return project, styled_map


# ─── Phase 3 : Open the map in QGIS ────────────────────────────────────────
def phase_3_open_map(styled_map):
    _phase(3, "Open map in QGIS")

    _step("Downloading styled map detail...")
    detail = api.styledmap.get_styled_map(styled_map.id)

    qgs_path = cache_map_module.get_filepath(detail.id)
    _step(f"Writing project file to cache: {qgs_path}")
    with open(qgs_path, "w", encoding="utf-8") as f:
        f.write(detail.qgisproject)

    # Avoid a "save changes?" prompt before loading the new project.
    QgsProject.instance().setDirty(False)

    _step("Loading project into QGIS...")
    iface.addProject(qgs_path)

    QgsProject.instance().setTitle(styled_map.name)
    QgsProject.instance().setCustomVariables({"kumoy_map_id": styled_map.id})
    QgsProject.instance().setDirty(False)
    _ok(f"Map opened, kumoy_map_id set to {styled_map.id}")


# ─── Phase 4 : Add local memory layers ─────────────────────────────────────
def phase_4_add_local_layers():
    _phase(4, "Add local layers")

    # Insertion order matters: addMapLayer inserts at the TOP of the tree.
    # So to get final order (top → bottom): points, lines, polygons, OSM
    # we add in the reverse order: OSM first (bottom), then polygons, lines, points.

    # 1. OpenStreetMap XYZ basemap (bottom of the stack)
    osm_uri = (
        "type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0"
    )
    osm = QgsRasterLayer(osm_uri, BASEMAP_LAYER_NAME, "wms")
    if not osm.isValid():
        raise RuntimeError("OpenStreetMap XYZ layer is not valid")
    QgsProject.instance().addMapLayer(osm)
    _ok(f"Added '{BASEMAP_LAYER_NAME}' (XYZ basemap)")

    # 2. Polygons
    polygons = QgsVectorLayer(
        "Polygon?crs=EPSG:4326&field=id:integer",
        POLYGONS_LAYER_NAME,
        "memory",
    )
    provider = polygons.dataProvider()
    triangle_feat = QgsFeature()
    triangle_feat.setGeometry(
        QgsGeometry.fromPolygonXY([[QgsPointXY(x, y) for x, y in POLYGON_RING]])
    )
    triangle_feat.setAttributes([1])
    provider.addFeature(triangle_feat)
    polygons.updateExtents()
    QgsProject.instance().addMapLayer(polygons)
    _ok(f"Added '{POLYGONS_LAYER_NAME}' ({polygons.featureCount()} features)")

    # 3. Lines
    lines = QgsVectorLayer(
        "LineString?crs=EPSG:4326&field=id:integer&field=name:string(64)",
        LINES_LAYER_NAME,
        "memory",
    )
    provider = lines.dataProvider()
    for i, ((x1, y1), (x2, y2)) in enumerate(LINE_COORDS):
        feat = QgsFeature()
        feat.setGeometry(
            QgsGeometry.fromPolylineXY([QgsPointXY(x1, y1), QgsPointXY(x2, y2)])
        )
        feat.setAttributes([i, f"line_{i}"])
        provider.addFeature(feat)
    lines.updateExtents()
    QgsProject.instance().addMapLayer(lines)
    _ok(f"Added '{LINES_LAYER_NAME}' ({lines.featureCount()} features)")

    # 4. Points (top of the stack — drawn last, visible on top)
    points = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=id:integer&field=name:string(64)",
        POINTS_LAYER_NAME,
        "memory",
    )
    provider = points.dataProvider()
    for i, (x, y) in enumerate(POINT_COORDS):
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feat.setAttributes([i, f"point_{i}"])
        provider.addFeature(feat)
    points.updateExtents()
    QgsProject.instance().addMapLayer(points)
    _ok(f"Added '{POINTS_LAYER_NAME}' ({points.featureCount()} features)")


# ─── Phase 5 : Save & auto-upload (monkey-patched dialogs) ─────────────────
def _save_project_with_patched_dialogs():
    """Fire the real ``projectSaved`` hook chain with modal dialogs answered.

    Used by both the first save and the sprite re-save. Warnings/criticals the
    plugin tries to show are recorded instead of displayed — they are modal, so
    an unnoticed one would hang the run. A critical means the save failed, so
    it is re-raised.
    """
    original_question = QMessageBox.question
    original_warning = QMessageBox.warning
    original_critical = QMessageBox.critical
    original_exec_dialog = convert_local_module.exec_dialog
    messages = []

    def _patched_question(*args, **kwargs):
        # `handle_project_saved` opens a QMessageBox.question to confirm
        # overwrite. Always say Yes during E2E.
        return Q_MESSAGEBOX_STD_BUTTON.Yes

    def _make_recorder(level):
        def _patched(parent=None, title="", text="", *args, **kwargs):
            messages.append((level, title, text))
            print(f"  ⚠ {level} dialog suppressed: {title} — {text}")
            return Q_MESSAGEBOX_STD_BUTTON.Ok

        return _patched

    def _patched_exec_dialog(dialog):
        # `convert_local_layers` opens a LayerSelectDialog. We delegate to
        # the dialog's own `_select_all()` method so we respect:
        #   - the vector quota (max_vectors - current_vectors),
        #   - disabled checkboxes (layers with unsaved edits).
        # Then we accept it.
        if isinstance(dialog, LayerSelectDialog):
            dialog._select_all()
            selected_count = len(dialog.selected_layers)
            _step(f"Auto-selected {selected_count} layer(s) in LayerSelectDialog")
            return QDIALOG_CODE.Accepted
        # Any other modal dialog is unexpected — fail-fast.
        print(f"  ⚠ Unexpected dialog during E2E save: {type(dialog).__name__}")
        return QDIALOG_CODE.Rejected

    try:
        QMessageBox.question = staticmethod(_patched_question)
        QMessageBox.warning = staticmethod(_make_recorder("warning"))
        QMessageBox.critical = staticmethod(_make_recorder("critical"))
        convert_local_module.exec_dialog = _patched_exec_dialog
        _step("Monkey-patched QMessageBox + exec_dialog")

        _step("Triggering QgsProject.write() → projectSaved → handle_project_saved")
        ok = QgsProject.instance().write()
        if not ok:
            raise RuntimeError("QgsProject.write() returned False")

        _ok("Save flow completed (upload triggered by handler)")
    finally:
        QMessageBox.question = original_question
        QMessageBox.warning = original_warning
        QMessageBox.critical = original_critical
        convert_local_module.exec_dialog = original_exec_dialog
        _step("Reverted dialog patches")

    criticals = [m for m in messages if m[0] == "critical"]
    if criticals:
        raise RuntimeError(
            "The save flow reported an error: "
            + "; ".join(f"{title}: {text}" for _, title, text in criticals)
        )
    return messages


def phase_5_save():
    _phase(5, "Save & auto-upload")
    _save_project_with_patched_dialogs()


# ─── Phase 6 : Verifications ───────────────────────────────────────────────
def phase_6_verify(project, styled_map):
    _phase(6, "Verifications (API direct)")

    _step("Checking vectors via API...")
    vectors = api.vector.get_vectors(project.id)
    print(f"    Found {len(vectors)} vector(s):")
    for v in vectors:
        print(f"      - {v.name} (id={v.id})")
    if len(vectors) < len(EXPECTED_VECTORS):
        raise RuntimeError(
            f"Expected ≥{len(EXPECTED_VECTORS)} vectors uploaded "
            f"(points + lines + polygons), got {len(vectors)}"
        )
    _ok("Vector count check passed")

    _step("Checking styled map content via API...")
    detail = api.styledmap.get_styled_map(styled_map.id)
    if not detail.qgisproject:
        raise RuntimeError("Styled map qgisproject is empty after save")
    # The Kumoy provider is referenced as `provider="kumoy"` (or similar)
    # in the .qgs XML after convert_to_kumoy replaces local layers.
    if "kumoy" not in detail.qgisproject.lower():
        raise RuntimeError(
            "Styled map qgisproject doesn't reference any Kumoy layer — "
            "convert_to_kumoy may have silently failed."
        )
    # The OSM XYZ basemap is NOT converted (it's a raster, not a vector) —
    # it should be preserved as-is in the saved .qgs.
    if "openstreetmap" not in detail.qgisproject.lower():
        raise RuntimeError(
            "Styled map qgisproject doesn't reference the OSM basemap — "
            "non-vector layers may have been dropped during save."
        )
    _ok(
        f"Styled map qgisproject is non-empty ({len(detail.qgisproject)} chars), "
        "references Kumoy layers AND preserves OSM basemap"
    )


# ─── Vector provider helpers ───────────────────────────────────────────────
def _vector_uri(vector) -> str:
    """Build the same URI the browser panel hands to the provider."""
    return (
        f"project_id={vector.projectId};vector_id={vector.id};"
        f"vector_name={vector.name};vector_type={vector.type};"
    )


def _open_kumoy_vector_layer(vector) -> QgsVectorLayer:
    layer = QgsVectorLayer(
        _vector_uri(vector), vector.name, constants.DATA_PROVIDER_KEY
    )
    if not layer.isValid():
        raise RuntimeError(
            f"Kumoy layer {vector.name!r} is invalid: {_vector_uri(vector)}"
        )
    return layer


def _server_features(vector_id):
    """Features straight from the API — the source of truth for verifications."""
    return api.qgis_vector.get_features(vector_id)


def _server_point(feature):
    geometry = QgsGeometry()
    geometry.fromWkb(feature["kumoy_wkb"])
    point = geometry.asPoint()
    return (round(point.x(), 5), round(point.y(), 5))


def _rounded(x, y):
    return (round(x, 5), round(y, 5))


def _commit(layer, what):
    if not layer.commitChanges():
        raise RuntimeError(f"commitChanges() failed for {what}: {layer.commitErrors()}")


def _kumoy_id_by_name(layer, name):
    for feature in layer.getFeatures():
        if feature["name"] == name:
            return int(feature["kumoy_id"])
    raise RuntimeError(f"No feature named {name!r} in layer {layer.name()!r}")


def _column_names(vector_id):
    return [column.get("name") for column in api.vector.get_vector(vector_id).columns]


# ─── Phase 7 : Read back through the vector provider ───────────────────────
def phase_7_provider_readback(project, state):
    _phase(7, "Read back through the Kumoy vector provider")

    vectors = {v.name: v for v in api.vector.get_vectors(project.id)}
    missing = [name for name in EXPECTED_VECTORS if name not in vectors]
    if missing:
        raise RuntimeError(
            f"Uploaded vectors not found on the server: {missing} "
            f"(server has {sorted(vectors)})"
        )
    state["vector_ids"] = [vectors[name].id for name in EXPECTED_VECTORS]
    state["points_vector_id"] = vectors[POINTS_LAYER_NAME].id

    for name, (geometry_type, expected_count) in EXPECTED_VECTORS.items():
        vector = vectors[name]
        if vector.type != geometry_type:
            raise RuntimeError(
                f"{name}: expected geometry type {geometry_type}, got {vector.type}"
            )

        layer = _open_kumoy_vector_layer(vector)
        try:
            if layer.featureCount() != expected_count:
                raise RuntimeError(
                    f"{name}: provider reports {layer.featureCount()} features, "
                    f"expected {expected_count}"
                )
            # featureCount() is served from metadata; iterating goes through
            # KumoyFeatureIterator, so check both agree.
            features = list(layer.getFeatures())
            if len(features) != expected_count:
                raise RuntimeError(
                    f"{name}: iterator yielded {len(features)} features, "
                    f"expected {expected_count}"
                )
            without_geometry = [f for f in features if not f.hasGeometry()]
            if without_geometry:
                raise RuntimeError(
                    f"{name}: {len(without_geometry)} feature(s) came back "
                    "without geometry"
                )
            if "kumoy_id" not in layer.fields().names():
                raise RuntimeError(
                    f"{name}: 'kumoy_id' missing from provider fields "
                    f"({layer.fields().names()})"
                )
            _ok(f"{name}: {expected_count} features, fields {layer.fields().names()}")
        finally:
            # Release the GPKG handle before the next sync touches the cache.
            del layer

    layer = _open_kumoy_vector_layer(vectors[POINTS_LAYER_NAME])
    try:
        got_points = sorted(
            _rounded(f.geometry().asPoint().x(), f.geometry().asPoint().y())
            for f in layer.getFeatures()
        )
        want_points = sorted(_rounded(x, y) for x, y in POINT_COORDS)
        if got_points != want_points:
            raise RuntimeError(
                f"Point geometries did not roundtrip: got {got_points}, "
                f"expected {want_points}"
            )
        _ok("Point geometries roundtripped exactly")

        got_names = sorted(f["name"] for f in layer.getFeatures())
        want_names = sorted(f"point_{i}" for i in range(len(POINT_COORDS)))
        if got_names != want_names:
            raise RuntimeError(
                f"Point attributes did not roundtrip: got {got_names}, "
                f"expected {want_names}"
            )
        _ok("Point attributes roundtripped exactly")

        # A bbox request goes down a different iterator path than a full scan.
        rect = QgsRectangle(139.69, 35.69, 139.73, 35.73)
        expected_in_rect = sum(
            1 for x, y in POINT_COORDS if rect.contains(QgsPointXY(x, y))
        )
        in_rect = len(list(layer.getFeatures(QgsFeatureRequest().setFilterRect(rect))))
        if in_rect != expected_in_rect:
            raise RuntimeError(
                f"Bbox-filtered request returned {in_rect} features, "
                f"expected {expected_in_rect}"
            )
        _ok(f"Bbox-filtered request returned {in_rect} features")

        if not layer.setSubsetString("\"name\" = 'point_1'"):
            raise RuntimeError("setSubsetString() was rejected by the provider")
        if layer.featureCount() != 1:
            raise RuntimeError(
                f"Subset string should leave 1 feature, got {layer.featureCount()}"
            )
        layer.setSubsetString("")
        _ok("Subset string filtered down to 1 feature and reset cleanly")
    finally:
        del layer

    for vector_id in state["vector_ids"]:
        cached = cache_vector_module.get_layer(vector_id)
        if cached is None:
            raise RuntimeError(f"No usable local cache (GPKG) for vector {vector_id}")
        del cached  # don't hold the GPKG open (Windows locks it)
    _ok("Local GPKG cache present and readable for every vector")


# ─── Phase 8 : Edit features through the provider ──────────────────────────
def phase_8_edit_roundtrip(state):
    _phase(8, "Edit features through the provider")

    vector = api.vector.get_vector(state["points_vector_id"])
    base_count = len(POINT_COORDS)

    layer = _open_kumoy_vector_layer(vector)
    try:
        # 1. Add a feature.
        layer.startEditing()
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(*ADDED_POINT)))
        feature.setAttribute("name", ADDED_POINT_NAME)
        if not layer.addFeature(feature):
            raise RuntimeError("addFeature() was refused by the layer")
        _commit(layer, "add feature")

        server_names = [
            f["properties"].get("name") for f in _server_features(vector.id)
        ]
        if ADDED_POINT_NAME not in server_names:
            raise RuntimeError(
                f"Added feature is not on the server (names: {server_names})"
            )
        count = api.vector.get_vector(vector.id).count
        if count != base_count + 1:
            raise RuntimeError(f"Server count is {count}, expected {base_count + 1}")
        _ok(f"Added a feature — server count is now {count}")

        # 2. Change an attribute.
        target_id = _kumoy_id_by_name(layer, "point_0")
        layer.startEditing()
        if not layer.changeAttributeValue(
            target_id, layer.fields().indexOf("name"), RENAMED_POINT_NAME
        ):
            raise RuntimeError("changeAttributeValue() was refused by the layer")
        _commit(layer, "change attribute")

        server_names = [
            f["properties"].get("name") for f in _server_features(vector.id)
        ]
        if RENAMED_POINT_NAME not in server_names or "point_0" in server_names:
            raise RuntimeError(
                f"Attribute change did not reach the server (names: {server_names})"
            )
        _ok(f"Changed an attribute — server now reports {RENAMED_POINT_NAME!r}")

        # 3. Change a geometry.
        layer.startEditing()
        if not layer.changeGeometry(
            target_id, QgsGeometry.fromPointXY(QgsPointXY(*MOVED_POINT))
        ):
            raise RuntimeError("changeGeometry() was refused by the layer")
        _commit(layer, "change geometry")

        moved = [
            _server_point(f)
            for f in _server_features(vector.id)
            if f["properties"].get("name") == RENAMED_POINT_NAME
        ]
        if moved != [_rounded(*MOVED_POINT)]:
            raise RuntimeError(
                f"Geometry change did not reach the server: got {moved}, "
                f"expected {[_rounded(*MOVED_POINT)]}"
            )
        _ok(f"Moved a feature — server geometry is now {moved[0]}")

        # 4. Add an attribute. This changes the column set, so the local cache
        #    has to be recreated rather than diff-synced.
        layer.startEditing()
        # Same length the Fields dialog pins for Varchar: the provider declares
        # minLen == maxLen == MAX_CHARACTERS_STRING_FIELD in its native types,
        # and QGIS refuses the commit if the requested field doesn't match the
        # one the provider reports afterwards.
        if not layer.addAttribute(
            QgsField(
                EXTRA_FIELD_NAME,
                QVariant.String,
                "",
                constants.MAX_CHARACTERS_STRING_FIELD,
            )
        ):
            raise RuntimeError("addAttribute() was refused by the layer")
        _commit(layer, "add attribute")

        columns = _column_names(vector.id)
        if EXTRA_FIELD_NAME not in columns:
            raise RuntimeError(f"New column is not on the server (columns: {columns})")
        if EXTRA_FIELD_NAME not in layer.fields().names():
            raise RuntimeError(
                f"New column is missing from the provider fields after reload "
                f"({layer.fields().names()})"
            )
        _ok(f"Added column {EXTRA_FIELD_NAME!r} — server columns: {columns}")

        # 5. Delete the attribute again.
        layer.startEditing()
        if not layer.deleteAttribute(layer.fields().indexOf(EXTRA_FIELD_NAME)):
            raise RuntimeError("deleteAttribute() was refused by the layer")
        _commit(layer, "delete attribute")

        columns = _column_names(vector.id)
        if EXTRA_FIELD_NAME in columns:
            raise RuntimeError(f"Column was not deleted server-side ({columns})")
        _ok(f"Deleted column {EXTRA_FIELD_NAME!r}")

        # 6. Delete the feature added in step 1.
        added_id = _kumoy_id_by_name(layer, ADDED_POINT_NAME)
        layer.startEditing()
        if not layer.deleteFeature(added_id):
            raise RuntimeError("deleteFeature() was refused by the layer")
        _commit(layer, "delete feature")

        count = api.vector.get_vector(vector.id).count
        if count != base_count:
            raise RuntimeError(f"Server count is {count}, expected {base_count}")
        _ok(f"Deleted the added feature — server count is back to {count}")
    finally:
        del layer

    # Re-open from scratch: the provider surface must agree with the server
    # after all that editing, including through a fresh cache sync.
    layer = _open_kumoy_vector_layer(api.vector.get_vector(vector.id))
    try:
        if layer.featureCount() != base_count:
            raise RuntimeError(
                f"Re-opened layer reports {layer.featureCount()} features, "
                f"expected {base_count}"
            )
        names = sorted(f["name"] for f in layer.getFeatures())
        if RENAMED_POINT_NAME not in names or ADDED_POINT_NAME in names:
            raise RuntimeError(f"Re-opened layer has unexpected attributes: {names}")
        _ok("Re-opened layer matches the server after every edit")
    finally:
        del layer


# ─── Phase 9 : Sprite generation & re-save ─────────────────────────────────
def _project_kumoy_point_layer():
    for layer in QgsProject.instance().mapLayers().values():
        if not isinstance(layer, QgsVectorLayer):
            continue
        if layer.providerType() != constants.DATA_PROVIDER_KEY:
            continue
        if layer.geometryType() == Qgis.GeometryType.Point:
            return layer
    raise RuntimeError(
        "No Kumoy point layer in the current project — the save-time conversion "
        "should have produced one."
    )


def phase_9_sprite_resave(styled_map):
    _phase(9, "Sprite generation & re-save")

    before = api.styledmap.get_styled_map(styled_map.id).assetsHash
    _step(f"assetsHash before: {before}")

    layer = _project_kumoy_point_layer()
    # Sprites are generated from point symbols of Kumoy layers only, so a
    # distinctive marker here must change the hash.
    symbol = QgsMarkerSymbol.createSimple(
        {"name": "star", "color": "255,0,0", "size": "6"}
    )
    layer.setRenderer(QgsSingleSymbolRenderer(symbol))
    layer.triggerRepaint()
    _ok(f"Applied a star marker to '{layer.name()}'")

    _save_project_with_patched_dialogs()

    after = api.styledmap.get_styled_map(styled_map.id).assetsHash
    _step(f"assetsHash after : {after}")
    if not after:
        raise RuntimeError("assetsHash is empty — sprites were not uploaded")
    if after == before:
        raise RuntimeError(
            "assetsHash did not change after a symbol change — sprite "
            "regeneration or upload was skipped"
        )
    _ok("Sprites were regenerated and uploaded")


# ─── Phase 10 : Reopen the saved map ───────────────────────────────────────
def phase_10_reopen(styled_map):
    _phase(10, "Reopen the saved map")

    detail = api.styledmap.get_styled_map(styled_map.id)
    qgs_path = cache_map_module.get_filepath(detail.id)
    with open(qgs_path, "w", encoding="utf-8") as f:
        f.write(detail.qgisproject)

    QgsProject.instance().clear()
    QgsProject.instance().setDirty(False)
    _step("Cleared QGIS and re-downloaded the saved project file")

    iface.addProject(qgs_path)
    project = QgsProject.instance()

    invalid = [
        layer.name() for layer in project.mapLayers().values() if not layer.isValid()
    ]
    if invalid:
        raise RuntimeError(f"Layers failed to resolve after reopening: {invalid}")

    kumoy_layers = [
        layer
        for layer in project.mapLayers().values()
        if layer.providerType() == constants.DATA_PROVIDER_KEY
    ]
    if len(kumoy_layers) != len(EXPECTED_VECTORS):
        raise RuntimeError(
            f"Expected {len(EXPECTED_VECTORS)} Kumoy layers after reopening, "
            f"got {len(kumoy_layers)} "
            f"({[layer.name() for layer in kumoy_layers]})"
        )
    for layer in kumoy_layers:
        if layer.featureCount() <= 0:
            raise RuntimeError(f"Reopened Kumoy layer {layer.name()!r} has no features")
    _ok(f"{len(kumoy_layers)} Kumoy layers resolved with features")

    basemaps = [
        layer
        for layer in project.mapLayers().values()
        if layer.name() == BASEMAP_LAYER_NAME
    ]
    if not basemaps:
        raise RuntimeError(f"'{BASEMAP_LAYER_NAME}' is missing after reopening")
    _ok(f"'{BASEMAP_LAYER_NAME}' survived the roundtrip")

    map_id = project.customVariables().get("kumoy_map_id")
    if map_id != styled_map.id:
        raise RuntimeError(
            f"kumoy_map_id did not survive the roundtrip: got {map_id!r}, "
            f"expected {styled_map.id!r}"
        )
    _ok("kumoy_map_id survived the roundtrip")


# ─── Phase 11 : Raster upload & read back ──────────────────────────────────
def _write_test_geotiff(path):
    """Write a small single-band GeoTIFF with predictable pixel values."""
    import numpy
    from osgeo import gdal, osr

    driver = gdal.GetDriverByName("GTiff")
    dataset = driver.Create(path, RASTER_SIZE, RASTER_SIZE, 1, gdal.GDT_Byte)
    dataset.SetGeoTransform(
        [
            RASTER_ORIGIN[0],
            RASTER_PIXEL_SIZE,
            0,
            RASTER_ORIGIN[1],
            0,
            -RASTER_PIXEL_SIZE,
        ]
    )
    srs = osr.SpatialReference()
    srs.ImportFromEPSG(4326)
    dataset.SetProjection(srs.ExportToWkt())
    values = numpy.fromfunction(
        lambda row, col: (col + row) % 256, (RASTER_SIZE, RASTER_SIZE)
    ).astype(numpy.uint8)
    dataset.GetRasterBand(1).WriteArray(values)
    dataset.FlushCache()
    del dataset


def _raster_probe():
    """Return (x, y, expected pixel value) at the centre of the probe pixel."""
    col, row = RASTER_PROBE_COL_ROW
    x = RASTER_ORIGIN[0] + (col + 0.5) * RASTER_PIXEL_SIZE
    y = RASTER_ORIGIN[1] - (row + 0.5) * RASTER_PIXEL_SIZE
    return x, y, (col + row) % 256


def _raster_uri(raster) -> str:
    return (
        f"project_id={raster.projectId};raster_id={raster.id};"
        f"raster_name={raster.name};"
    )


def _open_kumoy_raster_layer(raster) -> QgsRasterLayer:
    layer = QgsRasterLayer(
        _raster_uri(raster), raster.name, constants.RASTER_DATA_PROVIDER_KEY
    )
    if not layer.isValid():
        raise RuntimeError(
            f"Kumoy raster layer {raster.name!r} is invalid: {_raster_uri(raster)}"
        )
    return layer


def phase_11_raster(project, state):
    _phase(11, "Raster upload & read back")

    tmp = tempfile.NamedTemporaryFile(suffix=".tif", delete=False)
    tif_path = tmp.name
    tmp.close()
    try:
        _write_test_geotiff(tif_path)
        _ok(f"Wrote a {RASTER_SIZE}x{RASTER_SIZE} test GeoTIFF: {tif_path}")

        # The destination is an enum whose options are built from every project
        # the user can reach, so ask the algorithm itself for the index.
        algorithm = raster_algorithm_module.UploadRasterAlgorithm()
        algorithm.initAlgorithm()
        if project.id not in algorithm.project_ids:
            raise RuntimeError(
                "The E2E project is not listed by the upload algorithm — "
                "the destination dropdown would not offer it either."
            )
        project_index = algorithm.project_ids.index(project.id)

        _step("Running kumoy:uploadraster (COG conversion + presigned upload)...")
        result = processing.run(
            "kumoy:uploadraster",
            {
                algorithm.INPUT_LAYER: tif_path,
                algorithm.KUMOY_PROJECT: project_index,
                algorithm.RASTER_NAME: RASTER_LAYER_NAME,
            },
        )
        raster_id = result.get("RASTER_ID")
        if not raster_id:
            raise RuntimeError(
                f"Upload algorithm returned no RASTER_ID (result: {result}) — "
                "it was cancelled or failed."
            )
        state["raster_ids"].append(raster_id)
        state["raster_id"] = raster_id
        _ok(f"Raster uploaded: id={raster_id}")
    finally:
        if os.path.exists(tif_path):
            try:
                os.unlink(tif_path)
            except OSError as e:
                print(f"  ⚠ Could not remove temp file {tif_path}: {e}")

    listed = api.raster.get_rasters(project.id)
    if not any(r.id == raster_id for r in listed):
        raise RuntimeError(
            f"Uploaded raster not listed in the project "
            f"(got {[(r.id, r.name) for r in listed]})"
        )
    raster = api.raster.get_raster(raster_id)
    if raster.name != RASTER_LAYER_NAME:
        raise RuntimeError(
            f"Uploaded raster is named {raster.name!r}, expected {RASTER_LAYER_NAME!r}"
        )
    if not api.raster.get_download_url(raster.id).startswith("http"):
        raise RuntimeError("get_download_url() did not return an absolute URL")
    _ok("Raster is listed in the project and has a download URL")

    if not cache_raster_module.is_cached(raster.id):
        raise RuntimeError(
            "The uploaded COG was not stored in the local cache — "
            "adding the layer would re-download it needlessly."
        )
    _ok("Uploaded COG was stored in the local cache")

    x, y, expected_value = _raster_probe()
    layer = _open_kumoy_raster_layer(raster)
    try:
        if (layer.width(), layer.height()) != (RASTER_SIZE, RASTER_SIZE):
            raise RuntimeError(
                f"Raster is {layer.width()}x{layer.height()}, "
                f"expected {RASTER_SIZE}x{RASTER_SIZE}"
            )
        if layer.bandCount() != 1:
            raise RuntimeError(f"Raster has {layer.bandCount()} bands, expected 1")
        value, ok = layer.dataProvider().sample(QgsPointXY(x, y), 1)
        if not ok or int(value) != expected_value:
            raise RuntimeError(
                f"Pixel at ({x}, {y}) is {value} (ok={ok}), expected {expected_value}"
            )
        _ok(f"Read back {layer.width()}x{layer.height()}, pixel value {int(value)}")
    finally:
        del layer

    # Drop the cache to exercise the download path the browser uses on a
    # machine that never uploaded this raster.
    if not cache_raster_module.clear(raster.id):
        raise RuntimeError("Could not clear the raster cache")
    if cache_raster_module.is_cached(raster.id):
        raise RuntimeError("Raster cache still present after clear()")
    _step("Cleared the raster cache — re-opening must download the COG")

    layer = _open_kumoy_raster_layer(raster)
    try:
        value, ok = layer.dataProvider().sample(QgsPointXY(x, y), 1)
        if not ok or int(value) != expected_value:
            raise RuntimeError(
                f"After re-download, pixel at ({x}, {y}) is {value} (ok={ok}), "
                f"expected {expected_value}"
            )
        if not cache_raster_module.is_cached(raster.id):
            raise RuntimeError("Re-download did not repopulate the cache")
        _ok("Re-downloaded the COG and read the same pixel value")
    finally:
        del layer


# ─── Phase 12 : Metadata, renames and deletions ────────────────────────────
def phase_12_metadata(config, project, styled_map, timestamp, state):
    _phase(12, "Metadata, renames and deletions")

    organization = api.organization.get_organization(state["organization_id"])
    usage = organization.usage
    plan = organization.planSettings
    _step(
        f"Usage: projects={usage.projects} vectors={usage.vectors} "
        f"rasters={usage.rasters} styledMaps={usage.styledMaps}"
    )
    _step(
        f"Plan : maxProjects={plan.maxProjects} maxVectors={plan.maxVectors} "
        f"maxRasters={plan.maxRasters} maxStyledMaps={plan.maxStyledMaps}"
    )
    expected_usage = {
        "projects": 1,
        "vectors": len(EXPECTED_VECTORS),
        "rasters": 1,
        "styledMaps": 1,
    }
    for field_name, minimum in expected_usage.items():
        actual = getattr(usage, field_name)
        if actual < minimum:
            raise RuntimeError(
                f"usage.{field_name} is {actual}, but this run created "
                f"at least {minimum}"
            )
    over_quota = [
        f"{field_name}={getattr(usage, field_name)} > {getattr(plan, limit)}"
        for field_name, limit in [
            ("projects", "maxProjects"),
            ("vectors", "maxVectors"),
            ("rasters", "maxRasters"),
            ("styledMaps", "maxStyledMaps"),
        ]
        if getattr(usage, field_name) > getattr(plan, limit)
    ]
    if over_quota:
        raise RuntimeError(f"Usage exceeds the plan limits: {over_quota}")
    _ok("Usage reflects this run and stays within the plan limits")

    # /myteams is the listing the plugin itself uses (the project selection
    # dialog). The org-wide /teams listing is not reachable for a plain team
    # admin and no plugin code calls it, so it is deliberately not checked.
    my_teams = api.team.get_organization_myteams(state["organization_id"])
    my_team_ids = [t.id for t in my_teams]
    if config["team_id"] not in my_team_ids:
        raise RuntimeError(
            f"Team {config['team_id']} missing from my teams (got {my_team_ids})"
        )
    _ok(f"Team is listed in my teams ({len(my_teams)} team(s) in the org)")

    project_ids = [
        p.id for p in api.project.get_projects_by_organization(state["organization_id"])
    ]
    if project.id not in project_ids:
        raise RuntimeError("The E2E project is missing from the organization listing")
    if (
        api.project.get_project(project.id).team.organization.id
        != (state["organization_id"])
    ):
        raise RuntimeError("Project detail points at a different organization")
    _ok("Project is listed under the organization and resolves back to it")

    params = api.public.get_params()
    _ok(f"Public params fetched: {params}")

    # Renames. Names are capped server-side, so keep them within the limits.
    renamed_project = f"__E2E_REN__{timestamp}"[: constants.MAX_CHARACTERS_PROJECT_NAME]
    api.project.update_project(project.id, renamed_project, "renamed by E2E")
    if api.project.get_project(project.id).name != renamed_project:
        raise RuntimeError("Project rename did not stick")
    _ok(f"Renamed project to {renamed_project!r}")

    vector_id = state["points_vector_id"]
    renamed_vector = "e2e_points_renamed"[: constants.MAX_CHARACTERS_VECTOR_NAME]
    api.vector.update_vector(
        vector_id,
        api.vector.UpdateVectorOptions(name=renamed_vector, attribution="E2E"),
    )
    updated_vector = api.vector.get_vector(vector_id)
    if updated_vector.name != renamed_vector or updated_vector.attribution != "E2E":
        raise RuntimeError("Vector rename / attribution did not stick")
    _ok(f"Renamed vector to {renamed_vector!r}")

    raster_id = state["raster_id"]
    renamed_raster = "e2e_raster_renamed"[: constants.MAX_CHARACTERS_RASTER_NAME]
    api.raster.update_raster(
        raster_id,
        api.raster.UpdateRasterOptions(name=renamed_raster, attribution="E2E"),
    )
    updated_raster = api.raster.get_raster(raster_id)
    if updated_raster.name != renamed_raster or updated_raster.attribution != "E2E":
        raise RuntimeError("Raster rename / attribution did not stick")
    _ok(f"Renamed raster to {renamed_raster!r}")

    renamed_map = f"__E2E_REN__{timestamp}"[: constants.MAX_CHARACTERS_STYLEDMAP_NAME]
    api.styledmap.update_styled_map(
        styled_map.id,
        api.styledmap.UpdateStyledMapOptions(
            name=renamed_map,
            description="renamed by E2E",
            attribution="E2E",
        ),
    )
    updated_map = api.styledmap.get_styled_map(styled_map.id)
    if updated_map.name != renamed_map or updated_map.attribution != "E2E":
        raise RuntimeError("Styled map rename did not stick")
    if not updated_map.qgisproject:
        raise RuntimeError(
            "Renaming the styled map wiped its qgisproject — a metadata-only "
            "update must not touch the project payload."
        )
    _ok(f"Renamed styled map to {renamed_map!r} without losing its qgisproject")

    # Deletions. The rest is left to the cascade delete in the cleanup phase.
    api.raster.delete_raster(raster_id)
    cache_raster_module.clear(raster_id)
    state["raster_ids"].remove(raster_id)
    state["raster_id"] = None
    if any(r.id == raster_id for r in api.raster.get_rasters(project.id)):
        raise RuntimeError("Deleted raster is still listed in the project")
    _ok("Deleted the raster and it disappeared from the listing")

    polygons_vector = next(
        (
            v
            for v in api.vector.get_vectors(project.id)
            if v.name == POLYGONS_LAYER_NAME
        ),
        None,
    )
    if polygons_vector is None:
        raise RuntimeError(f"{POLYGONS_LAYER_NAME} vanished before the delete test")
    api.vector.delete_vector(polygons_vector.id)
    cache_vector_module.clear(polygons_vector.id)
    state["vector_ids"].remove(polygons_vector.id)
    remaining = api.vector.get_vectors(project.id)
    if any(v.id == polygons_vector.id for v in remaining):
        raise RuntimeError("Deleted vector is still listed in the project")
    if len(remaining) != len(EXPECTED_VECTORS) - 1:
        raise RuntimeError(
            f"Expected {len(EXPECTED_VECTORS) - 1} vectors after the delete, "
            f"got {len(remaining)}"
        )
    _ok("Deleted a vector and it disappeared from the listing")

    usage_after = api.organization.get_organization(state["organization_id"]).usage
    _step(
        f"Usage after deletions: vectors={usage_after.vectors} "
        f"rasters={usage_after.rasters}"
    )


# ─── Phase 13 : Cleanup ────────────────────────────────────────────────────
def phase_13_cleanup(state):
    _phase(13, "Cleanup")

    project = state["project"]
    session_logged_in = state["session_logged_in"]
    qgis_project_touched = state["qgis_project_touched"]

    if not project and not session_logged_in and not qgis_project_touched:
        # Nothing destructive happened — likely the user cancelled before
        # any phase mutated state. Don't touch their QGIS / session.
        _step("Nothing to clean (cancelled before any destructive operation).")
        return

    if project is not None:
        try:
            api.project.delete_project(project.id)
            _ok(f"Deleted project {project.id} (cascade)")
        except Exception as e:
            print(f"  ⚠ Failed to delete project {project.id}: {e}")
            print(
                "    You may need to delete it manually "
                "(look for the __E2E_TEST__ / __E2E_REN__ prefix in your org)."
            )

    # Local caches outlive the server-side resources, so clear them too.
    # Best-effort: a leftover GPKG/COG only wastes disk.
    for vector_id in state["vector_ids"]:
        if not cache_vector_module.clear(vector_id):
            print(f"  ⚠ Could not clear the local cache for vector {vector_id}")
    for raster_id in state["raster_ids"]:
        if not cache_raster_module.clear(raster_id):
            print(f"  ⚠ Could not clear the local cache for raster {raster_id}")
    if state["vector_ids"] or state["raster_ids"]:
        _ok(
            f"Cleared local caches ({len(state['vector_ids'])} vector(s), "
            f"{len(state['raster_ids'])} raster(s))"
        )

    if qgis_project_touched:
        # Best-effort: cleanup is non-fatal. Log and continue.
        try:
            QgsProject.instance().clear()
            _ok("Cleared QGIS project")
        except Exception as e:
            print(f"  ⚠ Failed to clear QGIS project: {e}")

    if session_logged_in:
        settings_manager.store_setting("session_token", "")
        _ok("Cleared QGIS session token (logout)")


# ─── Main ──────────────────────────────────────────────────────────────────
def _run():
    print()
    print("═" * 64)
    print("  KUMOY QGIS PLUGIN — E2E TEST")
    print("═" * 64)

    timestamp = datetime.now().strftime("%Y-%m-%d_%Hh%Mm%Ss")
    print(f"  Run ID: {timestamp}")

    state = {
        "project": None,
        "organization_id": None,
        "session_logged_in": False,
        "qgis_project_touched": False,
        # Created resources whose local caches have to be cleaned up.
        "vector_ids": [],
        "raster_ids": [],
        "points_vector_id": None,
        "raster_id": None,
    }
    failed = False
    try:
        config = _gather_config()
        _handle_unsaved_current_project()
        server_url = phase_0_preflight(config)
        phase_1_login(config, server_url, state)
        project, styled_map = phase_2_setup(config, timestamp, state)
        phase_3_open_map(styled_map)
        phase_4_add_local_layers()
        phase_5_save()
        phase_6_verify(project, styled_map)
        phase_7_provider_readback(project, state)
        phase_8_edit_roundtrip(state)
        phase_9_sprite_resave(styled_map)
        phase_10_reopen(styled_map)
        phase_11_raster(project, state)
        phase_12_metadata(config, project, styled_map, timestamp, state)
    except E2EUserError as e:
        failed = True
        print()
        print("═" * 64)
        print(f"  ⚠ Aborted: {e}")
        print("═" * 64)
    except Exception as e:
        failed = True
        print()
        print("═" * 64)
        print(f"  ❌ E2E TEST FAILED: {type(e).__name__}: {e}")
        print("═" * 64)
    finally:
        try:
            phase_13_cleanup(state)
        except Exception as e:
            print(f"⚠ Cleanup error: {e}")

    if not failed:
        print()
        print("═" * 64)
        print("  ✅ E2E TEST PASSED")
        print("═" * 64)


_run()
