"""Vector half of converting a local layer into a Kumoy layer (convert.py).

Runs `kumoy:uploadvector` by id in a background task (ui/ does not import
processing/). Same shape as `_upload_raster.upload`, so convert.py drives
both alike.
"""

from typing import Callable, List, Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsVectorLayer,
)

from ... import i18n
from ...kumoy import constants, vector_layer
from ...kumoy.api.models import Vector

_ALGORITHM_ID = "kumoy:uploadvector"

_GEOMETRY_TYPES = {
    Qgis.GeometryType.Point: "POINT",
    Qgis.GeometryType.Line: "LINESTRING",
    Qgis.GeometryType.Polygon: "POLYGON",
}

# QgsTaskManager does not keep Python wrappers (or their feedback/context)
# alive; hold them until the task reports back
_running: List[object] = []


class _RecordingFeedback(QgsProcessingFeedback):
    """Keeps reportError() messages: a background run fails with just False."""

    def __init__(self) -> None:
        super().__init__()
        self.errors: List[str] = []

    def reportError(self, error: str, fatalError: bool = False) -> None:
        self.errors.append(error)
        super().reportError(error, fatalError)


def upload(
    layer: QgsVectorLayer,
    project_id: str,
    vector_name: str,
    on_progress: Optional[Callable[[float], None]] = None,
    on_done: Optional[Callable[[Optional[QgsVectorLayer]], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> QgsProcessingAlgRunnerTask:
    """Upload `layer` as a new vector of `project_id` in a background task.

    Returns at once with the task; `task.cancel()` cancels. Callbacks run on
    the main thread: on_progress(0-100); on_done(kumoy_layer) with the new
    Kumoy layer (not added to the project) or None when canceled;
    on_error(exception). Raises RuntimeError when the tool is not registered.
    """
    alg = QgsApplication.processingRegistry().createAlgorithmById(_ALGORITHM_ID)
    if alg is None:
        raise RuntimeError(i18n.tr("Upload algorithm is not available"))

    name = vector_name or layer.name()[: constants.MAX_CHARACTERS_VECTOR_NAME]
    geometry_type = _GEOMETRY_TYPES.get(layer.geometryType(), "")
    params = {"INPUT": layer, "PROJECT_ID": project_id, "VECTOR_NAME": name}
    # Without project: the tool then leaves the Browser alone, which callers
    # holding Browser items rely on (processing.base.is_gui_run)
    context = QgsProcessingContext()
    feedback = _RecordingFeedback()
    if on_progress is not None:
        # Emitted in the worker thread, delivered queued on the main thread
        feedback.progressChanged.connect(on_progress)
    task = QgsProcessingAlgRunnerTask(alg, params, context, feedback)
    keep = (task, context, feedback)

    def executed(ok: bool, results: dict) -> None:
        _running.remove(keep)
        if feedback.isCanceled():
            if on_done is not None:
                on_done(None)
            return
        try:
            vector_id = results.get("VECTOR_ID") if ok else None
            if not vector_id:
                raise RuntimeError(
                    feedback.errors[-1] if feedback.errors else i18n.tr("Upload failed")
                )
            # Built locally: fetching the vector would be a blocking request
            vector = Vector(
                id=vector_id, name=name, type=geometry_type, projectId=project_id
            )
            kumoy_layer = vector_layer.create_vector_layer(vector)
        except Exception as e:
            if on_error is not None:
                on_error(e)
            return
        if on_done is not None:
            on_done(kumoy_layer)

    task.executed.connect(executed)
    _running.append(keep)
    QgsApplication.taskManager().addTask(task)
    return task
