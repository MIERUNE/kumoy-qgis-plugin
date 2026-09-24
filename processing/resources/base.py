import dataclasses
import html
import json
from typing import Any, Dict, Optional

from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProcessingOutputHtml,
    QgsProcessingOutputVariant,
    QgsProcessingParameterDefinition,
    QgsProcessingParameterString,
    QgsProcessingUtils,
)

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...kumoy.settings_manager import get_settings


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


def group_name(group_id: str) -> str:
    groups = {
        "organization": i18n.tr("Organizations and projects"),
        "vector": i18n.tr("Vectors"),
        "raster": i18n.tr("Rasters"),
        "map": i18n.tr("Maps"),
    }
    return groups[group_id]


class KumoyApiAlgorithm(QgsProcessingAlgorithm):
    """Base class for algorithms that call the Kumoy API.

    Resources are addressed by ID instead of enum indexes, and nothing talks to
    the network, QMessageBox or iface outside processAlgorithm(). This keeps
    them usable from processing.run() in scripts, any thread, or without GUI.

    Kumoy treats a project as the data boundary: like the Browser panel, only
    vectors, rasters and maps of the selected project are accessible.
    """

    GROUP_ID: str = ""
    HTML: str = "HTML"

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

    def selected_project_id(self) -> str:
        project_id = get_settings().selected_project_id
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
        # The dialog closes on success by default, taking its log with it;
        # HTML outputs stay in the Results Viewer panel
        self.addOutput(QgsProcessingOutputHtml(self.HTML, i18n.tr("Result")))

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

    def report(
        self, context: QgsProcessingContext, feedback: QgsProcessingFeedback, value: Any
    ) -> Dict[str, str]:
        """Show the result in the log and the Results Viewer; returns the HTML output."""
        text = json.dumps(value, ensure_ascii=False, indent=2)
        feedback.pushInfo(text)

        path = QgsProcessingUtils.generateTempFilename(f"{self.name()}.html", context)
        with open(path, "w", encoding="utf-8") as f:
            f.write(
                '<html><head><meta charset="utf-8"></head><body>'
                f"<h3>{html.escape(self.displayName())}</h3>"
                f"<pre>{html.escape(text)}</pre></body></html>"
            )
        return {self.HTML: path}

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
        try:
            return self.run_api(parameters, context, feedback)
        except QgsProcessingException:
            raise
        # The server answers 403 as well as 401 with UnauthorizedError
        except api.error.UnauthorizedError as e:
            raise QgsProcessingException(
                i18n.tr(
                    "Kumoy rejected the request. You may not be logged in, your "
                    "session may have expired, or you may not have permission "
                    "for this operation. Details: {}"
                ).format(format_api_error(e))
            ) from None
        except api.error.QuotaExceededError as e:
            raise QgsProcessingException(
                i18n.tr(
                    "Your organization has reached the limit of its plan. Details: {}"
                ).format(format_api_error(e))
            ) from None
        except Exception as e:
            raise QgsProcessingException(format_api_error(e)) from None
