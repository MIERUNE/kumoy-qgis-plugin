from typing import Optional

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsMapLayer,
    QgsMessageLog,
    QgsProcessingAlgRunnerTask,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
)
from qgis.PyQt.QtCore import QEventLoop
from qgis.PyQt.QtWidgets import QMessageBox, QProgressDialog
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...pyqt_version import (
    QT_APPLICATION_MODAL,
    exec_event_loop,
)
from ..error_handler import refresh_kumoy_browser


def on_convert_raster_to_kumoy_clicked(layer: QgsRasterLayer, project_id: str) -> None:
    if not layer or not layer.isValid():
        QMessageBox.warning(
            None,
            i18n.tr("Invalid Layer"),
            i18n.tr("The selected layer is no longer valid or has been removed."),
        )
        return

    if not project_id:
        QMessageBox.warning(
            None,
            i18n.tr("No Project Selected"),
            i18n.tr("Please select a Kumoy project before converting a layer."),
        )
        return

    layer_name = layer.name()
    success, error = convert_raster_to_kumoy(layer, project_id)

    if success:
        # ブラウザ更新はこの（レイヤーパネル起点の）経路でのみ行う。
        # Map保存フローは呼び出し元がブラウザアイテムを保持したまま変換を走らせる
        # ため、変換内でツリーを再構築すると保持中のアイテムが破棄されてしまう。
        refresh_kumoy_browser()
        iface.messageBar().pushMessage(
            constants.PLUGIN_NAME,
            i18n.tr("Layer '{}' converted to Kumoy successfully.").format(layer_name),
            level=Qgis.Success,
            duration=5,
        )
    elif error is not None:
        QMessageBox.warning(
            None,
            i18n.tr("Conversion Failed"),
            i18n.tr("Failed to convert layer '{}' to Kumoy:\n{}").format(
                layer_name, error
            ),
        )


def convert_raster_to_kumoy(
    layer: QgsRasterLayer, project_id: str
) -> tuple[bool, Optional[str]]:
    """Convert a raster layer to a Kumoy raster (COG upload).

    Returns:
        tuple: (success, error_message)。ユーザーが中断した場合は (False, None)
        （呼び出し側はエラー表示しない）。
    """

    if not layer or not layer.isValid():
        return (False, i18n.tr("The layer is no longer valid or has been removed."))

    try:
        project_index = _resolve_project_index(project_id)
        if project_index is None:
            raise Exception(i18n.tr("Project not found in organization list"))

        raster_name = layer.name()[: constants.MAX_CHARACTERS_VECTOR_NAME]

        result = _run_upload(layer, project_index, raster_name)
        if result is None:
            return (False, None)  # ユーザーキャンセル

        if "RASTER_ID" not in result:
            raise Exception(i18n.tr("Upload failed - unable to get raster id"))

        _replace_with_kumoy_layer(layer, result["RASTER_ID"])
        return (True, None)

    except Exception as e:
        error_msg = format_api_error(e)
        QgsMessageLog.logMessage(
            f"Error converting raster layer: {error_msg}",
            constants.LOG_CATEGORY,
            Qgis.Critical,
        )
        return (False, error_msg)


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
    layer: QgsRasterLayer, project_index: int, raster_name: str
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

    progress = QProgressDialog(
        i18n.tr("Uploading layer '{}'...").format(raster_name),
        i18n.tr("Cancel"),
        0,
        100,
        iface.mainWindow(),
    )
    progress.setWindowTitle(i18n.tr("Kumoy Upload"))
    progress.setWindowModality(QT_APPLICATION_MODAL)
    progress.setMinimumDuration(0)
    progress.setValue(0)

    # 進捗はワーカースレッドから queued signal で届く。
    feedback.progressChanged.connect(lambda p: progress.setValue(int(p)))
    progress.canceled.connect(feedback.cancel)

    outcome: dict = {}
    loop = QEventLoop()

    def on_executed(successful: bool, results: dict) -> None:
        outcome["ok"] = successful
        outcome["results"] = results
        loop.quit()

    task = QgsProcessingAlgRunnerTask(alg, params, context, feedback)
    task.executed.connect(on_executed)
    QgsApplication.taskManager().addTask(task)

    progress.show()
    exec_event_loop(loop)

    # QProgressDialog.close() は canceled() を発火する。ここで feedback.cancel を
    # 呼ばせると、成功した実行を後追いでキャンセル扱いにしてしまうため、閉じる前に
    # 接続を切る（実行中のユーザーキャンセルは既に feedback に反映済み）。
    progress.canceled.disconnect(feedback.cancel)
    progress.close()

    if feedback.isCanceled():
        return None

    if not outcome.get("ok"):
        raise Exception(feedback.last_error() or i18n.tr("Upload failed"))

    return outcome.get("results") or {}


def _resolve_project_index(project_id: str) -> Optional[int]:
    """uploadraster の PROJECT enum インデックスを求める。

    アルゴリズムは組織→プロジェクトの列挙順で選択肢を作るので、ここでも同じ
    順序で走査してインデックスを合わせる。
    """
    idx = 0
    for org in api.organization.get_organizations():
        # UploadRasterAlgorithm.initAlgorithm と同じフィルタでないと
        # インデックスがずれる（削除予約中の組織はプロジェクトAPIが404を返す）
        if org.scheduledDeletionAt:
            continue
        for proj in api.project.get_projects_by_organization(org.id):
            if proj.id == project_id:
                return idx
            idx += 1
    return None


def _replace_with_kumoy_layer(local_layer: QgsRasterLayer, raster_id: str) -> None:
    """アップロード済みラスタの Kumoy レイヤーを作り、元レイヤーと置き換える。"""
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

    _copy_layer_style(local_layer, kumoy_layer)

    # 元レイヤーを凡例の同じ位置で置き換える。
    root = QgsProject.instance().layerTreeRoot()
    original_layer_node = root.findLayer(local_layer.id())

    if original_layer_node:
        parent_node = original_layer_node.parent()
        index = parent_node.children().index(original_layer_node)

        QgsProject.instance().addMapLayer(kumoy_layer, False)
        parent_node.insertLayer(index, kumoy_layer)
        parent_node.removeChildNode(original_layer_node)
        QgsProject.instance().removeMapLayer(local_layer.id())
    else:
        QgsProject.instance().addMapLayer(kumoy_layer)
        QgsProject.instance().removeMapLayer(local_layer.id())

    iface.layerTreeView().setCurrentLayer(kumoy_layer)


def _copy_layer_style(
    source_layer: QgsRasterLayer, target_layer: QgsRasterLayer
) -> None:
    """Copy style from source layer to target layer"""
    doc = QDomDocument()
    elem = doc.createElement("qgis")
    doc.appendChild(elem)
    context = QgsReadWriteContext()

    source_layer.writeStyle(elem, doc, "", context, QgsMapLayer.AllStyleCategories)
    target_layer.readStyle(elem, "", context, QgsMapLayer.AllStyleCategories)
    target_layer.triggerRepaint()
