"""Map保存フロー用: ローカルレイヤー（ベクター・ラスタ）を一括でKumoyに変換する。

ベクターとラスタで別々に出していた選択ダイアログを、混在リストの単一
ダイアログに統合するエントリポイント。個々の変換処理はレイヤー種別ごとの
モジュール（convert_vector / convert_raster）に委譲する。
"""

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


def convert_local_layers(
    project_id: str,
) -> tuple[bool, list[tuple[str, str]]]:
    """Prompt the user to select and convert local layers (vector and raster).

    A single dialog lists both layer types in layer panel order. Each type
    has a plan-based count quota capping how many can be selected.

    Returns:
        tuple: (cancelled, conversion_errors)
            cancelled: True if the user cancelled (map save should be aborted)
            conversion_errors: (layer_name, error) for failed conversions
    """
    local_layers = get_local_layers()
    if not local_layers:
        return (False, [])

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
        return (True, [])

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
        return (True, [])

    selected_layers = dialog.selected_layers
    if not selected_layers:
        return (False, [])

    conversion_errors = []
    for layer in selected_layers:
        if isinstance(layer, QgsVectorLayer):
            success, error = convert_to_kumoy(layer, project_id)
            if not success:
                conversion_errors.append((layer.name(), error))
        else:
            success, error = convert_raster_to_kumoy(layer, project_id)
            # error is None on user cancel of an individual upload —
            # skip, not a failure.
            if not success and error is not None:
                conversion_errors.append((layer.name(), error))

    iface.mapCanvas().refresh()

    return (False, conversion_errors)
