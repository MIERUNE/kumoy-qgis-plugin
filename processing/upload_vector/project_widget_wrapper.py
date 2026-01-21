from typing import Any, Dict, List, Optional, Tuple

from processing.gui.wrappers import WidgetWrapper
from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QComboBox
from qgis.utils import iface

from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...kumoy.get_token import get_token
from ...settings_manager import get_settings


def _tr(string: str) -> str:
    return QCoreApplication.translate("ProjectWidgetWrapper", string)


def _get_project_options() -> Tuple[List[str], Dict[str, str]]:
    """Get project options for the combo box.

    Returns:
        Tuple of (project_ids, id_to_display_name_map)
    """
    project_ids: List[str] = []
    id_to_name: Dict[str, str] = {}

    try:
        if get_token() is None:
            return project_ids, id_to_name

        organizations = api.organization.get_organizations()
        for org in organizations:
            projects = api.project.get_projects_by_organization(org.id)
            for project in projects:
                display_name = f"{org.name} / {project.name}"
                project_ids.append(project.id)
                id_to_name[project.id] = display_name

    except Exception as e:
        msg = _tr("Error fetching projects: {}").format(format_api_error(e))
        QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Critical)
        if iface:
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME, msg, level=Qgis.Critical, duration=10
            )

    return project_ids, id_to_name


class ProjectWidgetWrapper(WidgetWrapper):
    """Custom widget wrapper for project selection using project ID as value."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._combo: Optional[QComboBox] = None
        self._project_ids: List[str] = []

    def createWidget(self) -> Optional[QComboBox]:
        """Create the combo box widget."""
        self._combo = QComboBox()
        self._project_ids, id_to_name = _get_project_options()

        for project_id in self._project_ids:
            display_name = id_to_name.get(project_id, project_id)
            self._combo.addItem(display_name, project_id)

        # Set default value from settings
        selected_project_id = get_settings().selected_project_id
        if selected_project_id and selected_project_id in self._project_ids:
            index = self._project_ids.index(selected_project_id)
            self._combo.setCurrentIndex(index)

        return self._combo

    def setValue(self, value: Any) -> None:
        """Set the widget value from a project ID."""
        if self._combo is None:
            return

        if value is None or value == "":
            return

        project_id = str(value)
        for i in range(self._combo.count()):
            if self._combo.itemData(i) == project_id:
                self._combo.setCurrentIndex(i)
                return

        # If project ID not found, add it as an option to preserve the value
        self._combo.addItem(_tr("Unknown project: {}").format(project_id), project_id)
        self._combo.setCurrentIndex(self._combo.count() - 1)

    def value(self) -> Any:
        """Return the currently selected project ID."""
        if self._combo is None:
            return None

        return self._combo.currentData()
