"""Map保存フロー用: ローカルレイヤー（ベクター・ラスタ）を一括でKumoyに変換する。

ベクターとラスタで別々に出していた選択ダイアログを、混在リストの単一
ダイアログに統合するエントリポイント。個々の変換処理はレイヤー種別ごとの
モジュール（convert_vector / convert_raster）に委譲する。
"""

from dataclasses import dataclass, field

from qgis.core import QgsVectorLayer
from qgis.utils import iface

from ... import i18n
from ...kumoy import api
from ...pyqt_version import QDIALOG_CODE, exec_dialog
from ..dialog_layer_select import LayerQuota, LayerSelectDialog
from ..error_handler import handle_api_error
from ..utils import get_local_layers
from .convert_raster import convert_raster_to_kumoy
from .convert_vector import convert_to_kumoy
from .upload_progress import upload_progress


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

            if isinstance(layer, QgsVectorLayer):
                success, error = convert_to_kumoy(layer, project_id, progress)
            else:
                success, error = convert_raster_to_kumoy(layer, project_id, progress)

            if success:
                result.converted = True
            elif error is not None:
                result.errors.append((layer.name(), error))
            else:
                # error is None は個別アップロードのユーザー中断。失敗ではなくスキップ。
                result.skipped.append(layer.name())

    iface.mapCanvas().refresh()

    return result
