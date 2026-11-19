"""Raster half of converting a local layer into a Kumoy layer (convert.py).

The upload pipeline (COG conversion, create_raster, presigned PUT, storing the
COG into the local cache, server-side cleanup on failure) lives in the
`kumoy:uploadraster` algorithm; it is run by id so that ui/ does not import
processing/.
"""

import math
from typing import Callable, List, Optional

from qgis.core import (
    QgsApplication,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsRasterLayer,
    QgsSingleBandPseudoColorRenderer,
)

from ... import i18n
from ...kumoy import constants, raster_layer
from ...kumoy.api.models import Raster

_ALGORITHM_ID = "kumoy:uploadraster"

# QgsTaskManager does not keep Python wrappers (or their feedback/context)
# alive; hold them until the task reports back
_running: List[object] = []


class _RecordingFeedback(QgsProcessingFeedback):
    """Keeps the algorithm's reportError() messages.

    A background run reports failure only as `executed(False)`; the message
    explaining it (quota, missing CRS, ...) arrives here.
    """

    def __init__(self) -> None:
        super().__init__()
        self.errors: List[str] = []

    def reportError(self, error: str, fatalError: bool = False) -> None:
        self.errors.append(error)
        super().reportError(error, fatalError)


def upload(
    layer: QgsRasterLayer,
    project_id: str,
    raster_name: str,
    on_progress: Optional[Callable[[float], None]] = None,
    on_done: Optional[Callable[[Optional[QgsRasterLayer]], None]] = None,
    on_error: Optional[Callable[[Exception], None]] = None,
) -> QgsProcessingAlgRunnerTask:
    """Upload `layer` as a new raster of `project_id` in a background task.

    Returns at once with the task; `task.cancel()` cancels (it also shows in
    the task manager). Callbacks run on the main thread:
    - on_progress(percent 0-100)
    - on_done(kumoy_layer): the new Kumoy layer (not added to the project;
      its COG is already cached), or None when canceled. Cancel is silent.
    - on_error(exception): failure, with the algorithm's message.
    Raises RuntimeError when the algorithm is not registered.
    """
    alg = QgsApplication.processingRegistry().createAlgorithmById(_ALGORITHM_ID)
    if alg is None:
        raise RuntimeError(i18n.tr("Upload algorithm is not available"))

    name = raster_name or layer.name()[: constants.MAX_CHARACTERS_RASTER_NAME]
    params = {"INPUT": layer, "PROJECT_ID": project_id, "RASTER_NAME": name}
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
            raster_id = results.get("RASTER_ID") if ok else None
            if not raster_id:
                raise RuntimeError(
                    feedback.errors[-1] if feedback.errors else i18n.tr("Upload failed")
                )
            # Built locally: fetching the raster would be a blocking request
            raster = Raster(id=raster_id, name=name, projectId=project_id)
            kumoy_layer = raster_layer.create_raster_layer(raster)
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


def repair_nan_classification(
    source_layer: QgsRasterLayer, target_layer: QgsRasterLayer
) -> None:
    """Restore pseudocolor min/max lost in the style XML round-trip.

    A renderer can have NaN classificationMin/Max yet render and show its
    legend fine through the shader's valid min/max. Copying the style via XML
    makes QgsSingleBandPseudoColorRenderer.create() overwrite the shader's
    min/max with those "nan" attributes, so only the converted layer's legend
    says "nan" (the color classes, and so the rendering, survive).
    """
    renderer = target_layer.renderer()
    source_renderer = source_layer.renderer()
    if not isinstance(renderer, QgsSingleBandPseudoColorRenderer) or not isinstance(
        source_renderer, QgsSingleBandPseudoColorRenderer
    ):
        return

    source_shader = source_renderer.shader()
    shader_fn = source_shader.rasterShaderFunction() if source_shader else None
    if shader_fn is None:
        return

    if math.isnan(renderer.classificationMin()) and not math.isnan(
        shader_fn.minimumValue()
    ):
        renderer.setClassificationMin(shader_fn.minimumValue())
    if math.isnan(renderer.classificationMax()) and not math.isnan(
        shader_fn.maximumValue()
    ):
        renderer.setClassificationMax(shader_fn.maximumValue())
