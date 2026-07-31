"""ローカルレイヤーをKumoyレイヤーに変換する入口とオーケストレーション。

2つの起点がある:

- ``convert_local_layers`` — Map保存フロー。選択ダイアログを出し、選ばれたレイヤーを
  1つの進捗ダイアログで順にアップロードする
- ``on_convert_layer_clicked`` — レイヤーパネルのコンテキストメニュー。1枚だけ変換する

ベクター/ラスターで違うのは「アップロードしてKumoyレイヤーを作る」ところだけなので、
そこだけを ``_upload_vector`` / ``_upload_raster`` に委譲し、ガード・スタイルコピー・
レイヤーツリーの差し替え・エラー処理はここで一度だけ書く。
"""

from dataclasses import dataclass, field
from typing import Optional

from qgis.core import (
    Qgis,
    QgsMapLayer,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsReadWriteContext,
    QgsVectorLayer,
)
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.PyQt.QtXml import QDomDocument
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ..dialog_layer_select import LayerQuota, LayerSelectDialog
from ..error_handler import handle_api_error, refresh_kumoy_browser
from ..utils import get_local_layers
from ...pyqt_version import QDIALOG_CODE, exec_dialog
from . import _upload_raster, _upload_vector
from .upload_progress import UploadProgressDialog, upload_progress


@dataclass
class ConversionResult:
    """ローカルレイヤー変換フローの結果。"""

    cancelled: bool = False
    """選択ダイアログでキャンセルされた（＝Map保存自体を中止すべき）"""

    errors: list[tuple[str, str]] = field(default_factory=list)
    """(レイヤー名, エラー内容) の失敗一覧"""

    converted: bool = False
    """1つ以上のレイヤーが変換された"""

    skipped: list[str] = field(default_factory=list)
    """アップロード中断でKumoyに送らなかったレイヤー名。

    途中でキャンセルしても、そこまでに変換済みのレイヤーは既にプロジェクトへ
    反映されているので保存自体は続行する。残りは未変換のまま保存される。
    """


def convert_local_layers(project_id: str) -> ConversionResult:
    """Prompt the user to select and convert local layers (vector and raster).

    A single dialog lists both layer types in layer panel order. Each type
    has a plan-based count quota capping how many can be selected.

    選択後のアップロードは1つの進捗ダイアログ（`UploadProgressDialog`）を全レイヤーで
    共有し、キャンセル1回で残り全部を中断できる（Issue #538）。

    ここではブラウザパネルをリフレッシュしない。呼び出し元（保存フロー）が
    ブラウザアイテム(self等)を保持したまま実行されるため、途中でツリーを
    再構築するとそのアイテムが破棄されてしまう。converted が True なら
    呼び出し元がフローの最後にリフレッシュすること。
    """
    local_layers = get_local_layers()
    if not local_layers:
        return ConversionResult()

    try:
        project = api.project.get_project(project_id)
        org_detail = api.organization.get_organization(project.team.organization.id)
        plan_limits = api.plan.get_plan_limits(
            org_detail.subscriptionPlan, org_detail.storageUnits
        )
    except Exception as e:
        handle_api_error(
            e, parent=None, log_prefix=i18n.tr("Failed to check layer limits")
        )
        return ConversionResult(cancelled=True)

    dialog = LayerSelectDialog(
        local_layers,
        vector_quota=LayerQuota(
            max_layers=plan_limits.maxVectors,
            current=org_detail.usage.vectors,
        ),
        raster_quota=LayerQuota(
            max_layers=plan_limits.maxRasters,
            current=org_detail.usage.rasters,
        ),
    )
    if exec_dialog(dialog) != QDIALOG_CODE.Accepted:
        return ConversionResult(cancelled=True)

    selected_layers = dialog.selected_layers
    if not selected_layers:
        return ConversionResult()

    result = ConversionResult()

    with upload_progress(len(selected_layers)) as progress:
        for index, layer in enumerate(selected_layers):
            if progress.is_canceled():
                # 残りは丸ごとスキップ。ここまでの変換結果は保存フローに残す。
                result.skipped.extend(
                    remaining.name() for remaining in selected_layers[index:]
                )
                break

            progress.begin_layer(layer.name(), index)
            success, error = convert_layer_to_kumoy(layer, project_id, progress)

            if success:
                result.converted = True
            elif error is not None:
                result.errors.append((layer.name(), error))
            else:
                # error is None は個別アップロードのユーザー中断。失敗ではなくスキップ。
                result.skipped.append(layer.name())

    iface.mapCanvas().refresh()

    return result


def on_convert_layer_clicked(layer: QgsMapLayer, project_id: str) -> None:
    """レイヤーパネルのコンテキストメニューから1枚だけ変換する。"""
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
    with upload_progress(1) as progress:
        progress.begin_layer(layer_name, 0)
        success, error = convert_layer_to_kumoy(layer, project_id, progress)

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
        # error is None ならユーザーが自分でキャンセルしたのでエラー表示しない
        QMessageBox.warning(
            None,
            i18n.tr("Conversion Failed"),
            i18n.tr("Failed to convert layer '{}' to Kumoy:\n{}").format(
                layer_name, error
            ),
        )


def convert_layer_to_kumoy(
    layer: QgsMapLayer,
    project_id: str,
    progress: UploadProgressDialog,
) -> tuple[bool, Optional[str]]:
    """ローカルレイヤー1枚をKumoyへアップロードし、Kumoyレイヤーに置き換える。

    Args:
        progress: 呼び出し側が ``upload_progress()`` で用意した進捗ダイアログ。
            対象レイヤーの ``begin_layer()`` は呼び出し側が済ませておくこと。

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

        # trim name if too long
        name = layer.name()[: constants.MAX_CHARACTERS_VECTOR_NAME]

        if isinstance(layer, QgsVectorLayer):
            kumoy_layer = _upload_vector.upload(layer, project_index, name, progress)
        else:
            kumoy_layer = _upload_raster.upload(layer, project_index, name, progress)

        if kumoy_layer is None:
            return (False, None)  # ユーザーキャンセル

        _copy_layer_style(layer, kumoy_layer)
        _replace_layer_in_tree(layer, kumoy_layer)
        return (True, None)

    except Exception as e:
        error_msg = format_api_error(e)
        QgsMessageLog.logMessage(
            f"Error converting layer '{layer.name()}': {error_msg}",
            constants.LOG_CATEGORY,
            Qgis.Critical,
        )
        return (False, error_msg)


def _resolve_project_index(project_id: str) -> Optional[int]:
    """アップロードアルゴリズムの PROJECT enum インデックスを求める。

    アルゴリズムは組織→プロジェクトの列挙順で選択肢を作るので、ここでも同じ
    順序で走査してインデックスを合わせる。
    """
    idx = 0
    for org in api.organization.get_organizations():
        # UploadVectorAlgorithm/UploadRasterAlgorithm の initAlgorithm と同じ
        # フィルタでないとインデックスがずれる
        # （削除予約中の組織はプロジェクトAPIが404を返す）
        if org.scheduledDeletionAt:
            continue
        for proj in api.project.get_projects_by_organization(org.id):
            if proj.id == project_id:
                return idx
            idx += 1
    return None


def _copy_layer_style(source_layer: QgsMapLayer, target_layer: QgsMapLayer) -> None:
    """Copy style from source layer to target layer"""
    doc = QDomDocument()
    elem = doc.createElement("qgis")
    doc.appendChild(elem)
    context = QgsReadWriteContext()

    source_layer.writeStyle(elem, doc, "", context, QgsMapLayer.AllStyleCategories)
    target_layer.readStyle(elem, "", context, QgsMapLayer.AllStyleCategories)
    if isinstance(target_layer, QgsRasterLayer):
        _upload_raster.repair_nan_classification(source_layer, target_layer)
    target_layer.triggerRepaint()


def _replace_layer_in_tree(local_layer: QgsMapLayer, kumoy_layer: QgsMapLayer) -> None:
    """元レイヤーを凡例の同じ位置・同じ表示状態でKumoyレイヤーに差し替える。"""
    root = QgsProject.instance().layerTreeRoot()
    original_layer_node = root.findLayer(local_layer.id())

    if original_layer_node:
        was_checked = original_layer_node.itemVisibilityChecked()
        parent_node = original_layer_node.parent()
        index = parent_node.children().index(original_layer_node)

        QgsProject.instance().addMapLayer(kumoy_layer, False)
        new_layer_node = parent_node.insertLayer(index, kumoy_layer)
        new_layer_node.setItemVisibilityChecked(was_checked)
        parent_node.removeChildNode(original_layer_node)
        QgsProject.instance().removeMapLayer(local_layer.id())
    else:
        # Fallback: add to root if original node not found
        QgsProject.instance().addMapLayer(kumoy_layer)
        QgsProject.instance().removeMapLayer(local_layer.id())

    iface.layerTreeView().setCurrentLayer(kumoy_layer)
