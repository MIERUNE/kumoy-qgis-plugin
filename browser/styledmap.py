import os
import tempfile
from typing import Dict, cast

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsMapLayer,
    QgsMessageLog,
    QgsProject,
    QgsRasterLayer,
    QgsVectorLayer,
)
from qgis.utils import iface

from ..imgs import IMGS_PATH
from ..qgishub import api
from ..qgishub.api.project_styledmap import (
    AddStyledMapOptions,
    QgishubStyledMap,
    UpdateStyledMapOptions,
)
from ..qgishub.constants import LOG_CATEGORY
from ..settings_manager import SettingsManager
from .utils import ErrorItem


class StyledMapItem(QgsDataItem):
    """スタイルマップアイテム（ブラウザ用）"""

    def __init__(self, parent, path: str, styled_map: QgishubStyledMap):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=styled_map.name,
            path=path,
        )

        self.styled_map = styled_map

        # アイコン設定
        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon_style.svg")))

        self.populate()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("StyledMapItem", message)

    def actions(self, parent):
        actions = []

        # スタイルマップ適用アクション
        apply_action = QAction(self.tr("Load to QGIS"), parent)
        apply_action.triggered.connect(self.apply_style)
        actions.append(apply_action)

        # スタイルマップ上書き保存アクション
        save_action = QAction(self.tr("Save"), parent)
        save_action.triggered.connect(self.apply_qgisproject_to_styledmap)
        actions.append(save_action)

        # スタイルマップ編集アクション
        edit_action = QAction(self.tr("Edit Metadata"), parent)
        edit_action.triggered.connect(self.update_metadata_styled_map)
        actions.append(edit_action)

        # スタイルマップ削除アクション
        delete_action = QAction(self.tr("Delete"), parent)
        delete_action.triggered.connect(self.delete_styled_map)
        actions.append(delete_action)

        return actions

    def apply_style(self):
        """スタイルをQGISレイヤーに適用する"""
        try:
            # XML文字列をQGISプロジェクトにロード
            success = load_project_from_xml(self.styled_map.qgisproject)
            if success:
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("Map '{}' has been loaded successfully.").format(
                        self.styled_map.name
                    ),
                )
            else:
                QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Failed to load map '{}'.").format(self.styled_map.name),
                )
        except Exception as e:
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Error loading map: {}").format(str(e))
            )

    def handleDoubleClick(self):
        """ダブルクリック時にスタイルを適用する"""
        self.apply_style()
        return True

    def update_metadata_styled_map(self):
        """Mapを編集する"""
        try:
            # ダイアログ作成
            dialog = QDialog()
            dialog.setWindowTitle(self.tr("Edit Map"))

            # レイアウト作成
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # フィールド作成（タイトルのみ編集可）
            name_field = QLineEdit(self.styled_map.name)
            is_public_field = QCheckBox(self.tr("Make Public"))
            is_public_field.setChecked(self.styled_map.isPublic)

            # フォームにフィールドを追加
            form_layout.addRow(self.tr("Name:"), name_field)
            form_layout.addRow(self.tr("Public:"), is_public_field)

            # ボタン作成
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)

            # ダイアログにレイアウトを追加
            layout.addLayout(form_layout)
            layout.addWidget(button_box)
            dialog.setLayout(layout)

            # ダイアログ表示
            result = dialog.exec_()

            if result:
                # 値を取得（タイトルと公開設定のみ）
                new_name = name_field.text()
                new_is_public = is_public_field.isChecked()

                if new_name:
                    # スタイルマップ上書き保存
                    updated_styled_map = api.project_styledmap.update_styled_map(
                        self.styled_map.id,
                        UpdateStyledMapOptions(
                            name=new_name,
                            isPublic=new_is_public,
                        ),
                    )

                    if updated_styled_map:
                        self.styled_map = updated_styled_map
                        self.setName(updated_styled_map.name)
                        self.refresh()
                        iface.messageBar().pushSuccess(
                            self.tr("Success"),
                            self.tr("Map '{}' has been updated successfully.").format(
                                new_name
                            ),
                        )
                    else:
                        QMessageBox.critical(
                            None, self.tr("Error"), self.tr("Failed to update the map.")
                        )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating map: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Error updating map: {}").format(str(e))
            )

    def apply_qgisproject_to_styledmap(self):
        # QGISプロジェクト情報はバックグラウンドで取得
        new_qgisproject = get_qgisproject_str()

        # スタイルマップ上書き保存
        updated_styled_map = api.project_styledmap.update_styled_map(
            self.styled_map.id,
            UpdateStyledMapOptions(
                qgisproject=new_qgisproject,
            ),
        )

        if updated_styled_map:
            self.styled_map = updated_styled_map
            self.setName(updated_styled_map.name)
            self.refresh()
            QMessageBox.information(
                None,
                self.tr("Success"),
                self.tr("Map '{}' has been saved successfully.").format(
                    self.styled_map.name
                ),
            )
        else:
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Failed to save the map.")
            )

    def delete_styled_map(self):
        """スタイルマップを削除する"""
        try:
            # 削除確認
            confirm = QMessageBox.question(
                None,
                self.tr("Delete Map"),
                self.tr("Are you sure you want to delete map '{}'?").format(
                    self.styled_map.name
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if confirm == QMessageBox.Yes:
                # スタイルマップ削除
                success = api.project_styledmap.delete_styled_map(self.styled_map.id)

                if success:
                    # 親アイテムを上書き保存して最新のリストを表示
                    self.parent().refresh()
                    iface.messageBar().pushSuccess(
                        self.tr("Success"),
                        self.tr("Map '{}' has been deleted successfully.").format(
                            self.styled_map.name
                        ),
                    )
                else:
                    QMessageBox.critical(
                        None, self.tr("Error"), self.tr("Failed to delete the map.")
                    )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error deleting map: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Error deleting map: {}").format(str(e))
            )


class StyledMapRoot(QgsDataItem):
    """スタイルマップルートアイテム（ブラウザ用）"""

    def __init__(self, parent, name, path):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent,
            name,
            path,
        )
        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon_style.svg")))
        self.populate()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("StyledMapRoot", message)

    def actions(self, parent):
        actions = []

        # スタイルマップ追加アクション
        add_action = QAction(self.tr("Save QGIS Map as New Map"), parent)
        add_action.triggered.connect(self.add_styled_map)
        actions.append(add_action)

        # 再読み込みアクション
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def add_styled_map(self):
        """新しいスタイルマップを追加する"""
        try:
            # ダイアログ作成
            dialog = QDialog()
            dialog.setWindowTitle(self.tr("Add Map"))

            # レイアウト作成
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # フィールド作成（タイトルのみ編集可）
            name_field = QLineEdit()
            is_public_field = QCheckBox(self.tr("Make Public"))

            # フォームにフィールドを追加
            form_layout.addRow(self.tr("Name:"), name_field)
            form_layout.addRow(self.tr("Public:"), is_public_field)

            # ボタン作成
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)

            # ダイアログにレイアウトを追加
            layout.addLayout(form_layout)
            layout.addWidget(button_box)
            dialog.setLayout(layout)

            # ダイアログ表示
            result = dialog.exec_()

            if result:
                # 値を取得（タイトルと公開設定のみ）
                name = name_field.text()

                if name:
                    # Show MapLibre compatibility dialog before saving
                    if not show_maplibre_compatibility_dialog():
                        return  # User cancelled after seeing compatibility info

                    # QGISプロジェクト情報はバックグラウンドで取得
                    qgisproject = get_qgisproject_str()

                    settings = SettingsManager()
                    project_id = settings.get_setting("selected_project_id")

                    if not project_id:
                        QMessageBox.critical(
                            None, self.tr("Error"), self.tr("No project selected.")
                        )
                        return

                    # スタイルマップ作成
                    new_styled_map = api.project_styledmap.add_styled_map(
                        project_id,
                        AddStyledMapOptions(
                            name=name,
                            qgisproject=qgisproject,
                        ),
                    )

                    if new_styled_map:
                        # 上書き保存して新しいスタイルマップを表示
                        self.refresh()
                        QMessageBox.information(
                            None,
                            self.tr("Success"),
                            self.tr("Map '{}' has been created successfully.").format(
                                name
                            ),
                        )
                    else:
                        # エラーメッセージを表示
                        QMessageBox.critical(
                            None, self.tr("Error"), self.tr("Failed to create the map.")
                        )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error adding map: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def createChildren(self):
        """子アイテムを作成する"""
        try:
            settings = SettingsManager()
            project_id = settings.get_setting("selected_project_id")

            if not project_id:
                return [ErrorItem(self, self.tr("No project selected"))]

            # プロジェクトのスタイルマップを取得
            styled_maps = api.project_styledmap.get_styled_maps(project_id)

            if not styled_maps:
                return [ErrorItem(self, self.tr("No maps available."))]

            children = []
            for styled_map in styled_maps:
                path = f"{self.path()}/{styled_map.id}"
                child = StyledMapItem(self, path, styled_map)
                children.append(child)

            return children

        except Exception as e:
            return [ErrorItem(self, self.tr("Error: {}").format(str(e)))]


def get_qgisproject_str() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".qgs", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp_path = tmp.name

    try:
        project = QgsProject.instance()
        project.write(tmp_path)
        with open(tmp_path, "r", encoding="utf-8") as f:
            return f.read()
    finally:
        _delete_tempfile(tmp_path)


def load_project_from_xml(xml_string: str) -> bool:
    with tempfile.NamedTemporaryFile(
        suffix=".qgs", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(xml_string)
        tmp_path = tmp.name

    try:
        project = QgsProject.instance()
        res = project.read(tmp_path)
        return res
    finally:
        _delete_tempfile(tmp_path)


def _delete_tempfile(tmp_path: str):
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
        QgsMessageLog.logMessage(
            f"Temporary file {tmp_path} removed.", LOG_CATEGORY, Qgis.Info
        )
    else:
        QgsMessageLog.logMessage(
            f"Temporary file {tmp_path} does not exist.", LOG_CATEGORY, Qgis.Warning
        )


def analyze_layer_maplibre_compatibility():
    """Analyze current QGIS project layers for MapLibre compatibility"""
    project = QgsProject.instance()
    layers: Dict[str, QgsMapLayer] = project.mapLayers()

    compatible_layers = []
    incompatible_layers = []

    for layer in layers.values():
        layer_name = layer.name()
        provider_type = layer.dataProvider().name()

        # Check if layer is compatible with MapLibre based on provider type
        is_compatible = False

        if isinstance(layer, QgsVectorLayer):
            if provider_type == "qgishub":
                is_compatible = True
        if isinstance(layer, QgsRasterLayer):
            if provider_type == "wms":
                source = layer.dataProvider().dataSourceUri()
                if "type=xyz" in source.lower():
                    is_compatible = True
        else:
            is_compatible = False

        if is_compatible:
            compatible_layers.append(f"✓ {layer_name} ({provider_type})")
        else:
            incompatible_layers.append(f"✗ {layer_name} ({provider_type})")

    return compatible_layers, incompatible_layers


def show_maplibre_compatibility_dialog():
    """Show dialog with MapLibre compatibility information"""
    compatible_layers, incompatible_layers = analyze_layer_maplibre_compatibility()

    if not compatible_layers and not incompatible_layers:
        QMessageBox.information(
            None,
            QCoreApplication.translate("StyledMapRoot", "Layer Compatibility"),
            QCoreApplication.translate(
                "StyledMapRoot", "No layers found in the current project."
            ),
        )
        return True

    # Create message text
    message_parts = []

    if compatible_layers:
        message_parts.append(
            QCoreApplication.translate("StyledMapRoot", "MapLibre Compatible Layers:")
        )
        message_parts.extend(compatible_layers)
        message_parts.append("")

    if incompatible_layers:
        message_parts.append(
            QCoreApplication.translate("StyledMapRoot", "MapLibre Incompatible Layers:")
        )
        message_parts.extend(incompatible_layers)
        message_parts.append("")

    message_parts.append(
        QCoreApplication.translate(
            "StyledMapRoot",
            "Note: Only qgishub vector layers and XYZ raster layers are supported in MapLibre.",
        )
    )

    # Show dialog
    msg_box = QMessageBox()
    msg_box.setWindowTitle(
        QCoreApplication.translate("StyledMapRoot", "MapLibre Compatibility Check")
    )
    msg_box.setText(
        QCoreApplication.translate(
            "StyledMapRoot", "Layer compatibility analysis for MapLibre:"
        )
    )
    msg_box.setDetailedText("\n".join(message_parts))
    msg_box.setStandardButtons(QMessageBox.Ok | QMessageBox.Cancel)
    msg_box.setDefaultButton(QMessageBox.Ok)

    result = msg_box.exec_()
    return result == QMessageBox.Ok
