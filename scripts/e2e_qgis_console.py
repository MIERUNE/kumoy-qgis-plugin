"""E2E test script for the Kumoy QGIS plugin.

This script exercises the full happy-path user workflow against a real Kumoy
server, from the QGIS Python console. It complements the pytest-qgis tests
in ``tests/`` (which run headless against mocks) by validating the real
plumbing end-to-end: auth flow, provider, Processing, save hook, API roundtrips.

How to run
----------
1. Open QGIS with the Kumoy plugin loaded.
2. Save any unsaved QGIS work — the script will replace the current project.
3. From the QGIS Python console::

       exec(open("/abs/path/to/kumoy-qgis-plugin/scripts/e2e_qgis_console.py").read())

   A configuration dialog opens on each run. Fields are persisted to QSettings,
   so they're pre-filled on subsequent runs.

What the script does
--------------------
0. Pre-flight: ask for config via dialog, validate, clear the current session.
1. Login: AuthManager device flow. Token is persisted via settings_manager.
   Post-login, ``api.user.get_me().email`` is checked against the email
   entered in the dialog to prevent running against the wrong account.
   No server resource is created if this check fails.
2. Server setup (via API direct, as setup): list orgs/teams, create a project
   and an empty styled map, both named ``__E2E_TEST__<timestamp>``.
3. Open map in QGIS: reproduce ``apply_style`` from ``ui/browser/styledmap.py``
   — write the project file to the local cache, ``iface.addProject``,
   set ``kumoy_map_id`` custom variable.
4. Add a couple of local in-memory layers (points + polygon).
5. Save: monkey-patch the modal dialogs that ``handle_project_saved`` /
   ``convert_local_layers`` would normally open, then call ``QgsProject.write()``
   to fire ``projectSaved``. The full hook chain runs: vectors are converted
   and uploaded via ``convert_to_kumoy``, then ``update_styled_map`` pushes
   the resulting .qgs back to the server.
6. Verify via API direct: vector count > 0, styled map qgisproject contains
   references to Kumoy layers.
7. Cleanup: delete the project (cascade), logout.

Cleanup robustness
------------------
Phase 7 is in a ``finally`` block so it runs even if a previous phase failed.
Leftovers can be identified by the ``__E2E_TEST__`` prefix and removed manually
if necessary.

Design notes
------------
- Vectors and styled maps are created via plugin entry points where it makes
  sense (Processing algo + save hook), via API direct otherwise (project create,
  empty styled map create). See ``CLAUDE.md`` / GitHub issue #391 for context.
- Monkey-patching dialogs is intrusive but pragmatic: a future refactor that
  extracts the non-UI logic of ``handle_project_saved`` would make it
  unnecessary. That refactor is out of scope for this script.
- This script is meant to be run interactively by a developer. It is NOT
  automated in CI: the OAuth flow requires a real human in a real browser.
"""

import importlib
import os
import sys
import tempfile
from datetime import datetime

from qgis.core import (
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QEventLoop, QSettings, QUrl
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
settings_manager = _imp("kumoy.settings_manager")
auth_module = _imp("kumoy.auth_manager")
cache_map_module = _imp("kumoy.local_cache.map")
pyqt_version_module = _imp("pyqt_version")
convert_vector_module = _imp("ui.layers.convert_vector")
dialog_layer_select_module = _imp("ui.dialog_layer_select")

LayerSelectDialog = dialog_layer_select_module.LayerSelectDialog
QDIALOG_CODE = pyqt_version_module.QDIALOG_CODE
Q_MESSAGEBOX_STD_BUTTON = pyqt_version_module.Q_MESSAGEBOX_STD_BUTTON


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

    Returns a dict with keys: email, org, team, custom_server.
    Raises E2EUserError if the user cancels.
    """
    settings = QSettings()
    settings.beginGroup(_E2E_SETTINGS_GROUP)
    defaults = {
        "email": settings.value("email", "", type=str),
        "org": settings.value("org", "", type=str),
        "team": settings.value("team", "", type=str),
        "custom_server": settings.value("custom_server", "", type=str),
    }
    settings.endGroup()

    dialog = QDialog(iface.mainWindow() if iface else None)
    dialog.setWindowTitle("Kumoy E2E test configuration")
    dialog.setMinimumWidth(500)

    layout = QVBoxLayout(dialog)
    intro = QLabel(
        "⚠️ The test will create and delete resources in the account/"
        "organization/team specified below."
    )
    intro.setWordWrap(True)
    layout.addWidget(intro)

    form = QFormLayout()
    email_field = QLineEdit(defaults["email"])
    email_field.setPlaceholderText("you@example.com")
    org_field = QLineEdit(defaults["org"])
    org_field.setPlaceholderText("Organization name")
    team_field = QLineEdit(defaults["team"])
    team_field.setPlaceholderText("Team name")
    custom_server_field = QLineEdit(defaults["custom_server"])
    custom_server_field.setPlaceholderText("Leave empty to use the default server")

    form.addRow("User email*", email_field)
    form.addRow("Organization*", org_field)
    form.addRow("Team name*", team_field)
    form.addRow("Custom server URL", custom_server_field)
    layout.addLayout(form)

    buttons = QDialogButtonBox(
        QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
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
        "org": org_field.text().strip(),
        "team": team_field.text().strip(),
        "custom_server": custom_server_field.text().strip(),
    }

    # Persist for next run, even if validation later fails. Otherwise users
    # would re-type everything when they fix a typo.
    settings.beginGroup(_E2E_SETTINGS_GROUP)
    for k, v in config.items():
        settings.setValue(k, v)
    settings.endGroup()

    return config


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
    if not config["org"]:
        raise E2EUserError("Organization name is required.")
    if not config["team"]:
        raise E2EUserError("Team name is required.")

    # Custom server is auto-detected from the URL field: filled = use it,
    # empty = use the plugin's default.
    if config["custom_server"]:
        settings_manager.store_setting("use_custom_server", "true")
        settings_manager.store_setting("custom_server_url", config["custom_server"])
    else:
        settings_manager.store_setting("use_custom_server", "false")

    server_url = api.config.get_api_config().SERVER_URL
    _step(f"Server URL    : {server_url}")
    _step(f"Expected email: {config['email']}")
    _step(f"Organization  : {config['org']}")
    _step(f"Team          : {config['team']}")

    # Wipe the current QGIS-side session so we exercise the real login.
    # If the wrong account is used during login, phase 1 will refuse to
    # continue (via the email check) — no resources are created in that case.
    settings_manager.store_setting("session_token", "")
    _ok("Cleared QGIS session token")

    return server_url


# ─── Phase 1 : Login ───────────────────────────────────────────────────────
def phase_1_login(config, server_url):
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
    # Qt5 → exec_, Qt6 → exec
    (loop.exec if hasattr(loop, "exec") else loop.exec_)()

    if not result["success"]:
        raise RuntimeError(f"Login failed: {result['error']}")

    settings_manager.store_setting("session_token", auth.get_access_token())
    _ok("Token persisted to QSettings")

    # Identity check — refuses to continue if the wrong account was used.
    me = api.user.get_me()
    _ok(f"Authenticated as: {me.email} (id={me.id})")
    if me.email != config["email"]:
        raise E2EUserError(
            f"Wrong account! Got {me.email!r}, expected {config['email']!r}. "
            "Aborting before touching any resource."
        )
    return me


# ─── Phase 2 : Server setup ────────────────────────────────────────────────
def phase_2_setup(config, timestamp):
    _phase(2, "Server setup")

    orgs = api.organization.get_organizations()
    if not orgs:
        raise E2EUserError("No organizations available for this account")
    org = next((o for o in orgs if o.name == config["org"]), None)
    if org is None:
        available = ", ".join(repr(o.name) for o in orgs)
        raise E2EUserError(
            f"Organization {config['org']!r} not found for this account. "
            f"Available: {available}"
        )
    _ok(f"Using organization: {org.name} (id={org.id}, role={org.role})")

    teams = api.team.get_organization_myteams(org.id)
    if not teams:
        raise E2EUserError(f"No teams available in organization {org.name}")
    team = next((t for t in teams if t.name == config["team"]), None)
    if team is None:
        available = ", ".join(f"{t.name!r} [{t.role}]" for t in teams)
        raise E2EUserError(
            f"Team {config['team']!r} not found in organization {org.name!r}. "
            f"Available: {available}"
        )
    _ok(f"Using team: {team.name} (id={team.id}, role={team.role})")
    if team.role == "MEMBER":
        # MEMBER role typically can't create projects on Kumoy. Warn upfront
        # so the user can pick a different team if they have a choice.
        print(
            f"  ⚠ Your role in team {team.name!r} is MEMBER — project creation "
            "will likely fail. Pick a team where you are OWNER or ADMIN."
        )

    project_name = f"__E2E_TEST__{timestamp}"
    _step(f"Creating project: {project_name}")
    project = api.project.create_project(
        team.id, project_name, "Created by scripts/e2e_qgis_console.py"
    )
    _ok(f"Project created: id={project.id}")

    # We need a valid (empty) QGIS project XML to bootstrap the styled map.
    # Easiest way: clear, write to a temp file, read it back.
    QgsProject.instance().clear()
    tmp = tempfile.NamedTemporaryFile(suffix=".qgs", delete=False)
    tmp_path = tmp.name
    tmp.close()
    try:
        QgsProject.instance().write(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            empty_qgs = f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

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
    osm = QgsRasterLayer(osm_uri, "OpenStreetMap", "wms")
    if not osm.isValid():
        raise RuntimeError("OpenStreetMap XYZ layer is not valid")
    QgsProject.instance().addMapLayer(osm)
    _ok("Added 'OpenStreetMap' (XYZ basemap)")

    # 2. Polygons
    polygons = QgsVectorLayer(
        "Polygon?crs=EPSG:4326&field=id:integer",
        "e2e_polygons",
        "memory",
    )
    provider = polygons.dataProvider()
    triangle_feat = QgsFeature()
    triangle_feat.setGeometry(
        QgsGeometry.fromPolygonXY(
            [
                [
                    QgsPointXY(139.70, 35.65),
                    QgsPointXY(139.80, 35.65),
                    QgsPointXY(139.75, 35.75),
                    QgsPointXY(139.70, 35.65),
                ]
            ]
        )
    )
    triangle_feat.setAttributes([1])
    provider.addFeature(triangle_feat)
    polygons.updateExtents()
    QgsProject.instance().addMapLayer(polygons)
    _ok(f"Added 'e2e_polygons' ({polygons.featureCount()} features)")

    # 3. Lines
    lines = QgsVectorLayer(
        "LineString?crs=EPSG:4326&field=id:integer&field=name:string(64)",
        "e2e_lines",
        "memory",
    )
    provider = lines.dataProvider()
    line_coords = [
        ((139.70, 35.70), (139.80, 35.70)),
        ((139.75, 35.65), (139.75, 35.75)),
    ]
    for i, ((x1, y1), (x2, y2)) in enumerate(line_coords):
        feat = QgsFeature()
        feat.setGeometry(
            QgsGeometry.fromPolylineXY([QgsPointXY(x1, y1), QgsPointXY(x2, y2)])
        )
        feat.setAttributes([i, f"line_{i}"])
        provider.addFeature(feat)
    lines.updateExtents()
    QgsProject.instance().addMapLayer(lines)
    _ok(f"Added 'e2e_lines' ({lines.featureCount()} features)")

    # 4. Points (top of the stack — drawn last, visible on top)
    points = QgsVectorLayer(
        "Point?crs=EPSG:4326&field=id:integer&field=name:string(64)",
        "e2e_points",
        "memory",
    )
    provider = points.dataProvider()
    coords = [
        (139.70, 35.70),
        (139.80, 35.65),
        (139.75, 35.68),
        (139.72, 35.72),
        (139.78, 35.69),
    ]
    for i, (x, y) in enumerate(coords):
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(x, y)))
        feat.setAttributes([i, f"point_{i}"])
        provider.addFeature(feat)
    points.updateExtents()
    QgsProject.instance().addMapLayer(points)
    _ok(f"Added 'e2e_points' ({points.featureCount()} features)")


# ─── Phase 5 : Save & auto-upload (monkey-patched dialogs) ─────────────────
def phase_5_save():
    _phase(5, "Save & auto-upload")

    original_question = QMessageBox.question
    original_exec_dialog = convert_vector_module.exec_dialog

    def _patched_question(*args, **kwargs):
        # `handle_project_saved` opens a QMessageBox.question to confirm
        # overwrite. Always say Yes during E2E.
        return Q_MESSAGEBOX_STD_BUTTON.Yes

    def _patched_exec_dialog(dialog):
        # `convert_local_layers` opens a LayerSelectDialog. We auto-check
        # every available layer and accept.
        if isinstance(dialog, LayerSelectDialog):
            for cb in dialog._checkboxes:
                cb.setChecked(True)
            _step(
                f"Auto-selected {len(dialog._checkboxes)} layer(s) in LayerSelectDialog"
            )
            return QDIALOG_CODE.Accepted
        # Any other modal dialog is unexpected — fail-fast.
        print(f"  ⚠ Unexpected dialog during E2E save: {type(dialog).__name__}")
        return QDIALOG_CODE.Rejected

    try:
        QMessageBox.question = staticmethod(_patched_question)
        convert_vector_module.exec_dialog = _patched_exec_dialog
        _step("Monkey-patched QMessageBox.question + exec_dialog")

        _step("Triggering QgsProject.write() → projectSaved → handle_project_saved")
        ok = QgsProject.instance().write()
        if not ok:
            raise RuntimeError("QgsProject.write() returned False")

        _ok("Save flow completed (upload triggered by handler)")
    finally:
        QMessageBox.question = original_question
        convert_vector_module.exec_dialog = original_exec_dialog
        _step("Reverted dialog patches")


# ─── Phase 6 : Verifications ───────────────────────────────────────────────
def phase_6_verify(project, styled_map):
    _phase(6, "Verifications (API direct)")

    _step("Checking vectors via API...")
    vectors = api.vector.get_vectors(project.id)
    print(f"    Found {len(vectors)} vector(s):")
    for v in vectors:
        print(f"      - {v.name} (id={v.id})")
    if len(vectors) < 3:
        raise RuntimeError(
            f"Expected ≥3 vectors uploaded (points + lines + polygons), "
            f"got {len(vectors)}"
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


# ─── Phase 7 : Cleanup ─────────────────────────────────────────────────────
def phase_7_cleanup(project):
    _phase(7, "Cleanup")

    if project is None:
        _step("No project to delete (setup didn't complete)")
    else:
        try:
            api.project.delete_project(project.id)
            _ok(f"Deleted project {project.id} (cascade)")
        except Exception as e:
            print(f"  ⚠ Failed to delete project {project.id}: {e}")
            print(
                "    You may need to delete it manually "
                "(look for __E2E_TEST__ prefix in your org)."
            )

    try:
        QgsProject.instance().clear()
        _ok("Cleared QGIS project")
    except Exception:
        pass

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

    project = None
    failed = False
    try:
        config = _gather_config()
        server_url = phase_0_preflight(config)
        phase_1_login(config, server_url)
        project, styled_map = phase_2_setup(config, timestamp)
        phase_3_open_map(styled_map)
        phase_4_add_local_layers()
        phase_5_save()
        phase_6_verify(project, styled_map)
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
            phase_7_cleanup(project)
        except Exception as e:
            print(f"⚠ Cleanup error: {e}")

    if not failed:
        print()
        print("═" * 64)
        print("  ✅ E2E TEST PASSED")
        print("═" * 64)


_run()
