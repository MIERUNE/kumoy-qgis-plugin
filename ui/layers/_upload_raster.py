"""ラスターレイヤー1枚をKumoyへアップロードし、Kumoyレイヤーを作るところまで。

ガード・スタイルコピー・レイヤーツリーの差し替えといった種別に依存しない部分は
``convert.py`` が持つ。ここにはラスター固有のものだけを置く:

- ``kumoy:uploadraster`` をワーカースレッドで実行する（理由は ``_run_upload``）
- Kumoyラスタの URI 組み立て
- スタイルXML往復で壊れる疑似カラー min/max の復元 (``repair_nan_classification``)
"""

import math
from typing import Optional

from qgis.core import (
    QgsApplication,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsRasterLayer,
    QgsSingleBandPseudoColorRenderer,
)
from qgis.PyQt.QtCore import QEventLoop

from ... import i18n
from ...kumoy import api, constants
from ...pyqt_version import exec_event_loop
from .upload_progress import UploadProgressDialog


def upload(
    layer: QgsRasterLayer,
    project_index: int,
    raster_name: str,
    progress: UploadProgressDialog,
) -> Optional[QgsRasterLayer]:
    """``layer`` をCOG化してKumoyへアップロードし、Kumoyラスタレイヤーを返す。

    Returns:
        新しいKumoyレイヤー。ユーザーが中断した場合は None。
    Raises:
        アップロードやレイヤー生成に失敗した場合は例外。
    """
    result = _run_upload(layer, project_index, raster_name, progress)
    if result is None:
        return None  # ユーザーキャンセル

    if "RASTER_ID" not in result:
        raise Exception(i18n.tr("Upload failed - unable to get raster id"))

    return _build_kumoy_layer(result["RASTER_ID"])


def repair_nan_classification(
    source_layer: QgsRasterLayer, target_layer: QgsRasterLayer
) -> None:
    """スタイルXML往復で失われた疑似カラーの min/max をシェーダー値から復元する。

    元レンダラーの classificationMin/Max が未設定(NaN)でも、シェーダー側の
    min/max が有効なら描画・凡例とも正常に見える。ところがスタイルを XML 経由で
    コピーすると、QgsSingleBandPseudoColorRenderer.create() が classificationMin/Max
    属性("nan")でシェーダーの有効な min/max まで上書きするため、変換後のレイヤー
    だけ凡例が「nan」表示になる（色分け項目は保持されるので描画は変わらない）。
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


class _RecordingFeedback(QgsProcessingFeedback):
    """アルゴリズムが reportError で出したメッセージを控えるフィードバック。

    バックグラウンド実行では例外が呼び出し側に伝播しないため、失敗時に具体的な
    原因（クォータ超過・CRS 未設定等）を拾えるようにエラー文字列を蓄える。
    """

    def __init__(self) -> None:
        super().__init__()
        self._errors: list[str] = []

    def reportError(self, error: str, fatalError: bool = False) -> None:
        self._errors.append(error)
        super().reportError(error, fatalError)

    def last_error(self) -> Optional[str]:
        return self._errors[-1] if self._errors else None


def _run_upload(
    layer: QgsRasterLayer,
    project_index: int,
    raster_name: str,
    progress: UploadProgressDialog,
) -> Optional[dict]:
    """``kumoy:uploadraster`` をバックグラウンドスレッドで実行し、完了まで待つ。

    presigned PUT は単一の長寿命 QNetworkReply を入れ子イベントループで待つ。
    これをメインスレッドで走らせると、進捗更新に伴う modal ダイアログの
    processEvents 再入が送信中の reply を破棄し "connection closed" になる。
    アルゴリズムをワーカースレッドで実行すれば、進捗は queued signal でメインに
    届くため再入が起きない。

    Returns:
        成功時は結果 dict、ユーザーキャンセル時は None。
    Raises:
        実行に失敗した場合は例外（可能ならアルゴリズムのエラーメッセージ付き）。
    """
    alg = QgsApplication.processingRegistry().createAlgorithmById("kumoy:uploadraster")
    if alg is None:
        raise Exception(i18n.tr("Upload algorithm is not available"))

    context = QgsProcessingContext()
    feedback = _RecordingFeedback()
    params = {
        "INPUT": layer,
        "PROJECT": project_index,
        "RASTER_NAME": raster_name,
    }

    # 進捗はワーカースレッドから queued signal で届く。
    feedback.progressChanged.connect(progress.set_layer_progress)
    progress.canceled.connect(feedback.cancel)
    if progress.is_canceled():
        # 前のレイヤーの処理中に押されたキャンセルを取りこぼさない
        feedback.cancel()

    outcome: dict = {}
    loop = QEventLoop()

    def on_executed(successful: bool, results: dict) -> None:
        outcome["ok"] = successful
        outcome["results"] = results
        loop.quit()

    task = QgsProcessingAlgRunnerTask(alg, params, context, feedback)
    task.executed.connect(on_executed)
    QgsApplication.taskManager().addTask(task)

    try:
        exec_event_loop(loop)
    finally:
        # ダイアログは次のレイヤーでも使うので、この feedback との接続だけ切る。
        # 実行中のユーザーキャンセルは既に feedback に反映済み。
        progress.canceled.disconnect(feedback.cancel)
        feedback.progressChanged.disconnect(progress.set_layer_progress)

    if feedback.isCanceled():
        return None

    if not outcome.get("ok"):
        raise Exception(feedback.last_error() or i18n.tr("Upload failed"))

    return outcome.get("results") or {}


def _build_kumoy_layer(raster_id: str) -> QgsRasterLayer:
    raster = api.raster.get_raster(raster_id)
    raster_uri = (
        f"project_id={raster.projectId};"
        f"raster_id={raster.id};"
        f"raster_name={raster.name};"
    )

    kumoy_layer = QgsRasterLayer(
        raster_uri, raster.name, constants.RASTER_DATA_PROVIDER_KEY
    )
    if not kumoy_layer.isValid():
        error_msg = (
            kumoy_layer.error().message() if kumoy_layer.error() else "Unknown error"
        )
        raise Exception(i18n.tr("Failed to create Kumoy layer: {}").format(error_msg))

    return kumoy_layer
