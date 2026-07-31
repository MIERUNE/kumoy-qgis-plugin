"""ベクターレイヤー1枚をKumoyへアップロードし、Kumoyレイヤーを作るところまで。

ガード・スタイルコピー・レイヤーツリーの差し替えといった種別に依存しない部分は
``convert.py`` が持つ。ここにはベクター固有のものだけを置く:

- ``kumoy:uploadvector`` をメインスレッドで同期実行する（ラスタはワーカースレッド
  実行。実行モデルが違う理由は ``_upload_raster._run_upload`` の docstring 参照）
- Kumoyベクターの URI 組み立てと ``kumoy_id`` の読み取り専用設定
"""

from typing import Optional

from qgis.core import (
    Qgis,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.utils import iface

import processing

from ... import i18n
from ...kumoy import api, constants
from .upload_progress import UploadProgressDialog


def upload(
    layer: QgsVectorLayer,
    project_index: int,
    vector_name: str,
    progress: UploadProgressDialog,
) -> Optional[QgsVectorLayer]:
    """``layer`` をKumoyへアップロードし、対応するKumoyベクターレイヤーを返す。

    Returns:
        新しいKumoyレイヤー。ユーザーが中断した場合は None。
    Raises:
        アップロードやレイヤー生成に失敗した場合は例外。
    """
    feedback = QgsProcessingFeedback()

    # processing.run はメインスレッドを塞ぐので、進捗更新のたびにイベントを
    # 回してダイアログの再描画とキャンセルボタンの押下を通す。
    def update_progress(value: float) -> None:
        progress.set_layer_progress(value)
        QCoreApplication.processEvents()

    feedback.progressChanged.connect(update_progress)
    progress.canceled.connect(feedback.cancel)
    if progress.is_canceled():
        # 前のレイヤーの処理中に押されたキャンセルを取りこぼさない
        feedback.cancel()

    try:
        result = processing.run(
            "kumoy:uploadvector",
            {
                "INPUT": layer,
                "PROJECT": project_index,
                "VECTOR_NAME": vector_name,
                "SELECTED_FIELDS": [],
            },
            context=QgsProcessingContext(),
            feedback=feedback,
        )

        if feedback.isCanceled():
            iface.messageBar().pushMessage(
                constants.PLUGIN_NAME,
                i18n.tr("Upload cancelled"),
                level=Qgis.Warning,
                duration=3,
            )
            return None

        if not result or "VECTOR_ID" not in result:
            raise Exception(i18n.tr("Upload failed - unable to get vector id"))
    finally:
        # ダイアログは次のレイヤーでも使うので、この feedback との接続だけ切る
        progress.canceled.disconnect(feedback.cancel)

    return _build_kumoy_layer(result["VECTOR_ID"])


def _build_kumoy_layer(vector_id: str) -> QgsVectorLayer:
    vector = api.vector.get_vector(vector_id)
    vector_uri = (
        f"project_id={vector.projectId};"
        f"vector_id={vector.id};"
        f"vector_name={vector.name};"
        f"vector_type={vector.type};"
    )

    kumoy_layer = QgsVectorLayer(vector_uri, vector.name, constants.DATA_PROVIDER_KEY)
    if not kumoy_layer.isValid():
        error_msg = (
            kumoy_layer.error().message() if kumoy_layer.error() else "Unknown error"
        )
        raise Exception(i18n.tr("Failed to create Kumoy layer: {}").format(error_msg))

    # kumoy_id はサーバ採番なので編集させない
    field_idx = kumoy_layer.fields().indexOf("kumoy_id")
    if field_idx >= 0:
        config = kumoy_layer.editFormConfig()
        config.setReadOnly(field_idx, True)
        kumoy_layer.setEditFormConfig(config)

    return kumoy_layer
