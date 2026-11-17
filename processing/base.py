import dataclasses
import json
import time
from typing import Any, Dict, List, Optional, Tuple

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsMessageLog,
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputVariant,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
)
from qgis.PyQt.QtCore import QThread
from qgis.utils import iface

from .. import i18n
from ..kumoy import api, constants, session, settings_manager
from ..kumoy.api.error import UnauthorizedError, format_api_error
from ..kumoy.api.models import OrganizationDetail, is_editor
from ..kumoy.tasks import Canceled, run_task
from ..ui.error_handler import (
    describe_error,
    handle_api_error,
    refresh_kumoy_browser,
    run_on_main_thread,
)


def to_output(obj: Any) -> Any:
    """Convert API dataclasses to plain dicts/lists.

    processing.run() passes results through QVariantMap, which cannot carry
    Python dataclasses.
    """
    if dataclasses.is_dataclass(obj):
        return dataclasses.asdict(obj)
    if isinstance(obj, list):
        return [to_output(item) for item in obj]
    return obj


def without_project(item: Dict[str, Any]) -> Dict[str, Any]:
    # Items listed in a project would otherwise each repeat the whole project
    return {k: v for k, v in item.items() if k != "project"}


def server_url() -> str:
    # Shown in login errors so users on a custom server see which one is meant
    return api.client.server_url()


def raise_if_not_logged_in() -> None:
    # Checked first: logging out also clears the selected project and the
    # upload destinations, which would otherwise surface as misleading errors
    if not session.is_logged_in():
        raise QgsProcessingException(
            i18n.tr(
                "You are not logged in to Kumoy ({}). Log in from the Kumoy item "
                "in the Browser panel."
            ).format(server_url())
        )


def group_name(group_id: str) -> str:
    groups = {
        "organization": i18n.tr("Organizations and projects"),
        "vector": i18n.tr("Vectors"),
        "raster": i18n.tr("Rasters"),
        "map": i18n.tr("Maps"),
    }
    return groups[group_id]


def is_gui_run(context: QgsProcessingContext) -> bool:
    """Whether GUI side effects (browser refresh, session-expired dialog) apply.

    True for the toolbox and processing.run() in the QGIS console, whose
    contexts belong to the open project. False in qgis_process and for layer
    conversion, which passes a context without project because it holds
    Browser items that a refresh would destroy.
    """
    return iface is not None and context.project() is not None


def _is_main_thread() -> bool:
    app = QgsApplication.instance()
    return app is not None and QThread.currentThread() == app.thread()


class KumoyApiAlgorithm(QgsProcessingAlgorithm):
    """Base class for algorithms that call the Kumoy API.

    Resources are addressed by ID instead of enum indexes, and nothing talks to
    the network, QMessageBox or iface outside processAlgorithm(). This keeps
    them usable from processing.run() in scripts or without GUI. Algorithms
    with REQUIRES_MAIN_THREAD must still be called from the main thread.

    Existing resources are addressed by ID regardless of the project selected
    in the Browser panel; the server decides what the user may access. Adding
    to the map is the exception, as a map must not mix layers across projects.
    """

    GROUP_ID: str = ""
    # Set when processAlgorithm() does work that crashes QGIS off the main
    # thread, such as creating Kumoy layers or building a QgsProject
    REQUIRES_MAIN_THREAD: bool = False
    # Set when the tool creates, renames or deletes items shown in the Browser
    CHANGES_RESOURCES: bool = False

    def __init__(self) -> None:
        super().__init__()
        self._max_lengths: Dict[str, int] = {}

    def createInstance(self) -> "KumoyApiAlgorithm":
        return type(self)()

    def group(self) -> str:
        return group_name(self.GROUP_ID)

    def groupId(self) -> str:
        return self.GROUP_ID

    def helpUrl(self) -> str:
        return constants.DOCUMENTATION_URL

    def flags(self) -> Qgis.ProcessingAlgorithmFlags:
        flags = super().flags()
        if self.REQUIRES_MAIN_THREAD:
            # The toolbox would otherwise run it in a background thread
            flags |= Qgis.ProcessingAlgorithmFlag.NoThreading
        return flags

    def main_thread_help(self) -> str:
        # NoThreading only covers the toolbox; processing.run() runs the
        # algorithm in the caller's thread, so script authors must know
        if not self.REQUIRES_MAIN_THREAD:
            return ""
        return i18n.tr(
            "\n\nThis tool must run on the main thread, so QGIS does not respond "
            "until it finishes. When calling it with processing.run() from your "
            "own Processing script or a QgsTask, run the caller on the main "
            "thread as well (for a Processing script, add "
            "Qgis.ProcessingAlgorithmFlag.NoThreading to its flags()). "
            "Otherwise QGIS may crash."
        )

    def selected_project_id(self) -> str:
        project_id = settings_manager.selected_project_id()
        if not project_id:
            raise QgsProcessingException(
                i18n.tr(
                    "No Kumoy project is selected. Select a project from the "
                    "Kumoy item in the Browser panel."
                )
            )
        return project_id

    def ensure_in_selected_project(self, project_id: str) -> None:
        if project_id != self.selected_project_id():
            raise QgsProcessingException(
                i18n.tr(
                    "This item does not belong to the selected Kumoy project. "
                    "Switch to its project from the Kumoy item in the Browser panel."
                )
            )

    def add_id_parameter(self, name: str, description: str) -> None:
        self.addParameter(QgsProcessingParameterString(name, description))

    def add_text_parameter(
        self, name: str, description: str, max_length: int, optional: bool = True
    ) -> None:
        # The API rejects longer values; show the limit before users run into it
        self._max_lengths[name] = max_length
        self.addParameter(
            QgsProcessingParameterString(
                name,
                i18n.tr("{} (max {} characters)").format(description, max_length),
                optional=optional,
            )
        )

    def add_output(self, name: str, description: str) -> None:
        self.addOutput(QgsProcessingOutputVariant(name, description))

    def parameter_as_id(
        self, parameters: Dict[str, Any], name: str, context: QgsProcessingContext
    ) -> str:
        value = self.parameterAsString(parameters, name, context).strip()
        if not value:
            raise QgsProcessingException(
                i18n.tr("'{}' is required.").format(
                    self.parameterDefinition(name).description()
                )
            )
        return value

    def parameter_as_text(
        self,
        parameters: Dict[str, Any],
        name: str,
        context: QgsProcessingContext,
    ) -> Optional[str]:
        """Return None for an empty value, meaning "keep the current value"."""
        value = self.parameterAsString(parameters, name, context)
        definition = self.parameterDefinition(name)
        if not value:
            if not definition.flags() & QgsProcessingParameterDefinition.FlagOptional:
                raise QgsProcessingException(
                    i18n.tr("'{}' is required.").format(definition.description())
                )
            return None
        if len(value) > self._max_lengths[name]:
            raise QgsProcessingException(
                i18n.tr("'{}' is too long: {} characters entered.").format(
                    definition.description(), len(value)
                )
            )
        return value

    def log_result(self, feedback: QgsProcessingFeedback, value: Any) -> None:
        feedback.pushInfo(json.dumps(value, ensure_ascii=False, indent=2))

    def run_api(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def processAlgorithm(
        self,
        parameters: Dict[str, Any],
        context: QgsProcessingContext,
        feedback: QgsProcessingFeedback,
    ) -> Dict[str, Any]:
        raise_if_not_logged_in()
        try:
            result = self.run_api(parameters, context, feedback)
        except QgsProcessingException:
            raise
        except Canceled:
            # Processing reports cancellation itself; an empty result is no error
            return {}
        except UnauthorizedError as e:
            if is_gui_run(context):
                # Same as anywhere else in the GUI: end the session, offer login
                handle_api_error(e)
            raise QgsProcessingException(
                i18n.tr(
                    "Your Kumoy session ({}) has expired or was signed out. Log in "
                    "again from the Kumoy item in the Browser panel. Details: {}"
                ).format(server_url(), format_api_error(e))
            ) from None
        except Exception as e:
            # 403/429/network errors get an explanation of what to do
            raise QgsProcessingException(describe_error(e)) from None
        if self.CHANGES_RESOURCES and is_gui_run(context):
            run_on_main_thread(refresh_kumoy_browser)
        return result


# --- Destination projects of the upload tools --------------------------------
#
# initAlgorithm() runs at QGIS startup and whenever a dialog opens, so it must
# not call the network. The project list comes from this cache, which is
# refreshed in the background.

# [(project ID, "Organization / Project")], projects the user may write to
_project_choices: List[Tuple[str, str]] = []
_refreshing = False
_last_refresh = 0.0
# Dialogs open in quick succession (and scripts loop); one fetch serves them
_REFRESH_INTERVAL_SECONDS = 10.0


def project_choices() -> List[Tuple[str, str]]:
    return list(_project_choices)


def forget_project_choices() -> None:
    _project_choices.clear()


def refresh_project_choices() -> None:
    """Reload the upload destinations in the background. Main thread only.

    Clears the list when logged out. Call after login so the first upload
    dialog already lists the projects.
    """
    global _refreshing, _last_refresh
    if not session.is_logged_in():
        _project_choices.clear()
        return
    if _refreshing or time.monotonic() - _last_refresh < _REFRESH_INTERVAL_SECONDS:
        return
    _refreshing = True

    def fetch(_task) -> List[Tuple[str, str]]:
        choices = []
        for org in api.organization.get_organizations():
            # Organizations awaiting deletion answer 404 for their projects
            if org.scheduledDeletionAt:
                continue
            # Only team Editors may upload; listing other projects would just
            # fail later with a permission error
            writable = {
                team.id
                for team in api.organization.get_my_teams(org.id)
                if is_editor(team.role)
            }
            for project in api.organization.get_projects(org.id):
                if project.teamId in writable:
                    choices.append((project.id, f"{org.name} / {project.name}"))
        return choices

    def done(choices: List[Tuple[str, str]]) -> None:
        global _refreshing, _last_refresh
        _refreshing = False
        _last_refresh = time.monotonic()
        # Logged out while loading: keep it empty
        _project_choices[:] = choices if session.is_logged_in() else []

    def failed(e: Exception) -> None:
        global _refreshing
        _refreshing = False
        # Background work: the user meets the error when they act
        QgsMessageLog.logMessage(
            f"Could not load the Kumoy projects for the upload tools: "
            f"{format_api_error(e)}",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )

    run_task(i18n.tr("Loading Kumoy projects"), fetch, done, failed)


class KumoyUploadAlgorithm(KumoyApiAlgorithm):
    """Shared parameters and checks of the vector and raster upload tools."""

    INPUT_LAYER = "INPUT"
    KUMOY_PROJECT = "PROJECT"
    KUMOY_PROJECT_ID = "PROJECT_ID"
    CHANGES_RESOURCES = True

    def __init__(self, prototype: bool = False) -> None:
        super().__init__()
        # The provider's registered instance. Every run is a create()d copy.
        self._prototype = prototype
        # The choices the PROJECT enum indexes refer to
        self._choices: Optional[List[Tuple[str, str]]] = None

    def createInstance(self) -> "KumoyUploadAlgorithm":
        alg = type(self)()
        if not self._prototype:
            # The toolbox runs a create()d copy of the dialog's instance: keep
            # the list the dialog showed, or a background refresh in between
            # could make the selected index point at another project
            alg._choices = self._choices
        return alg

    def add_project_parameters(self) -> None:
        # Scripts cannot know enum indexes in advance, so accept a stable ID too
        project_id_param = QgsProcessingParameterString(
            self.KUMOY_PROJECT_ID,
            i18n.tr("Destination project ID (overrides the destination project)"),
            optional=True,
        )
        project_id_param.setFlags(
            project_id_param.flags() | QgsProcessingParameterDefinition.FlagAdvanced
        )
        self.addParameter(project_id_param)

        choices = self._choices if self._choices is not None else project_choices()
        if not self._prototype:
            self._choices = choices
        if _is_main_thread():
            # Picks up projects created since the last refresh for the next
            # dialog; this one keeps the list it was built with
            refresh_project_choices()

        ids = [project_id for project_id, _ in choices]
        selected = settings_manager.selected_project_id()
        self.addParameter(
            QgsProcessingParameterEnum(
                self.KUMOY_PROJECT,
                i18n.tr("Destination project"),
                options=[label for _, label in choices],
                allowMultiple=False,
                # An empty required enum would reject runs that pass PROJECT_ID
                optional=not choices,
                defaultValue=(ids.index(selected) if selected in ids else 0)
                if choices
                else None,
            )
        )

    def _resolve_project_id(
        self, parameters: Dict[str, Any], context: QgsProcessingContext
    ) -> str:
        project_id = self.parameterAsString(
            parameters, self.KUMOY_PROJECT_ID, context
        ).strip()
        if project_id:
            return project_id

        choices = self._choices or []
        index = self.parameterAsEnum(parameters, self.KUMOY_PROJECT, context)
        if not choices:
            raise QgsProcessingException(
                i18n.tr(
                    "No destination project is available. The project list is "
                    "loaded in the background after you log in: close this tool "
                    "and open it again, or enter the destination project ID."
                )
            )
        if index < 0 or index >= len(choices):
            raise QgsProcessingException(
                i18n.tr("Invalid destination project selection.")
            )
        return choices[index][0]

    def check_destination(self, project_id: str, kind: str) -> OrganizationDetail:
        """Fail before the slow part when the server would reject the upload.

        `kind` is "vector" or "raster". The server enforces all of this as
        well; checking first saves the user the conversion or a cleanup.
        """
        project = api.project.get_project(project_id)
        if not is_editor(project.role):
            raise QgsProcessingException(
                i18n.tr(
                    "You cannot upload to this project: uploading requires the "
                    "Editor role in the project's team."
                )
            )
        organization = api.organization.get_organization(project.team.organizationId)
        usage, plan = organization.usage, organization.planSettings
        # Organization-wide caps, not per project
        if kind == "vector" and usage.vectors >= plan.maxVectors:
            raise QgsProcessingException(
                i18n.tr(
                    "Cannot upload vector: your organization has reached your "
                    "plan's limit of {} vectors. Delete an existing vector or "
                    "upgrade your plan to add more."
                ).format(plan.maxVectors)
            )
        if kind == "raster" and usage.rasters >= plan.maxRasters:
            raise QgsProcessingException(
                i18n.tr(
                    "Cannot upload raster: your organization has reached your "
                    "plan's limit of {} rasters. Delete an existing raster or "
                    "upgrade your plan to add more."
                ).format(plan.maxRasters)
            )
        if usage.usedStorageUnits >= organization.availableStorageUnits:
            raise QgsProcessingException(
                i18n.tr(
                    "Cannot upload: your organization has used all of its storage. "
                    "Delete data or add storage to your plan."
                )
            )
        return organization

    def parameter_as_name(
        self,
        parameters: Dict[str, Any],
        name: str,
        context: QgsProcessingContext,
        layer_name: str,
        max_length: int,
    ) -> str:
        """The name to create the item with: the layer name when left empty."""
        value = self.parameterAsString(parameters, name, context).strip()
        if not value:
            return layer_name[:max_length]
        if len(value) > max_length:
            raise QgsProcessingException(
                i18n.tr("'{}' is too long: {} characters entered.").format(
                    self.parameterDefinition(name).description(), len(value)
                )
            )
        return value
