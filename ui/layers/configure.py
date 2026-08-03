"""Kumoy レイヤーのフォーム設定。

Browser からの追加とアップロード直後の2経路で同じレイヤーを組み立てるため、
設定は1箇所にまとめる。
"""

from qgis.core import (
    QgsEditorWidgetSetup,
    QgsProperty,
    QgsPropertyCollection,
    QgsVectorLayer,
)
from qgis.gui import QgsExternalResourceWidget, QgsFileWidget, QgsWidgetWrapper

from ...kumoy import api, external_storage


def _attachment_widget_setup(
    vector_id: str, vector_column_id: str
) -> QgsEditorWidgetSetup:
    """attachment カラム用の External Resource ウィジェット設定を組み立てる。

    QGIS 標準のウィジェットに全面的に乗るための設定で、要点は3つ:

    - ``StorageType`` に "kumoy" を指定し、値の解決とアップロードを
      ``KumoyExternalStorage`` に委ねる（ローカルファイルパスを属性値にしない）
    - ``StorageUrl`` は**データ定義プロパティ（式）**として渡す。config へ生文字列を
      入れると QGIS が文字列リテラルとして quote してしまい式が評価されないため、
      ``PropertyCollection`` 経由でなければ kumoy_id を埋め込めない
    - ``DefaultRoot`` に vector_id、``RelativeStorage`` に RelativeDefaultPath を
      指定すると、``doFetch`` へ ``{vectorId}/{属性値}`` の形で渡ってくる。属性値だけ
      では vector_id が分からないので、この組み合わせが解決の鍵になる
    """
    collection = QgsPropertyCollection()
    collection.setProperty(
        QgsWidgetWrapper.Property.StorageUrl,
        QgsProperty.fromExpression(
            external_storage.build_storage_url_expression(vector_id, vector_column_id),
            True,
        ),
    )

    return QgsEditorWidgetSetup(
        "ExternalResource",
        {
            "StorageType": external_storage.STORAGE_TYPE,
            "StorageMode": QgsFileWidget.StorageMode.GetFile,
            "DefaultRoot": vector_id,
            "RelativeStorage": QgsFileWidget.RelativeStorage.RelativeDefaultPath,
            "DocumentViewer": QgsExternalResourceWidget.DocumentViewerContent.Image,
            "DocumentViewerHeight": 0,
            "DocumentViewerWidth": 0,
            "UseLink": False,
            "FullUrl": False,
            "PropertyCollection": collection.toVariant(
                QgsWidgetWrapper.propertyDefinitions()
            ),
        },
    )


def configure_kumoy_layer(
    layer: QgsVectorLayer, vector: api.vector.KumoyVectorDetail
) -> None:
    """Kumoy レイヤーの編集フォームを設定する。

    - kumoy_id はサーバが採番するのでフォームから編集させない
    - attachment カラムには External Resource ウィジェットを自動設定し、
      QGIS 標準のフォーム・画像プレビューがそのまま動く状態にする
    """
    config = layer.editFormConfig()

    field_idx = layer.fields().indexOf("kumoy_id")
    if field_idx >= 0:
        config.setReadOnly(field_idx, True)

    layer.setEditFormConfig(config)

    for column in vector.columns:
        if column.get("type") != "attachment":
            continue
        idx = layer.fields().indexOf(column["name"])
        if idx < 0:
            continue
        layer.setEditorWidgetSetup(
            idx, _attachment_widget_setup(vector.id, column["id"])
        )
