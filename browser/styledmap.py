import os
import tempfile

from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsMessageLog,
    QgsProject,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
from qgis.utils import iface

from ..imgs import IMGS_PATH
from ..settings_manager import SettingsManager
from ..strato import api
from ..strato.api.project_styledmap import (
    AddStyledMapOptions,
    StratoStyledMap,
    UpdateStyledMapOptions,
)
from ..strato.constants import LOG_CATEGORY
from ..ui.dialog_maplibre_compatibility import MapLibreCompatibilityDialog
from .utils import ErrorItem


class StyledMapItem(QgsDataItem):
    """スタイルマップアイテム（ブラウザ用）"""

    def __init__(self, parent, path: str, styled_map: StratoStyledMap):
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
        # Show MapLibre compatibility dialog before saving
        compatibility_dialog = MapLibreCompatibilityDialog()
        result = compatibility_dialog.exec_()

        if not result:
            return

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
            iface.messageBar().pushSuccess(
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
        settings = SettingsManager()
        organization_id = settings.get_setting("selected_organization_id")
        organization = api.organization.get_organization(organization_id)
        project_id = settings.get_setting("selected_project_id")

        # Check plan limits before creating styled map
        plan_limit = api.plan.get_plan_limits(organization.plan)
        if not plan_limit:
            return

        current_styled_maps = api.project_styledmap.get_styled_maps(project_id)
        current_styled_map_count = len(current_styled_maps) + 1
        if current_styled_map_count > plan_limit.maxStyledMaps:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Cannot create new map. Your plan allows up to {} maps, "
                    "but you have reached the limit."
                ).format(plan_limit.maxStyledMaps),
            )
            return

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

        if not result:
            return

        # 値を取得（タイトルと公開設定のみ）
        name = name_field.text()

        if not name:
            return

        # Show MapLibre compatibility dialog before saving
        compatibility_dialog = MapLibreCompatibilityDialog()
        result = compatibility_dialog.exec_()

        if not result:
            return  # User cancelled after seeing compatibility info

        # QGISプロジェクト情報はバックグラウンドで取得
        qgisproject = get_qgisproject_str()

        # スタイルマップ作成
        new_styled_map = api.project_styledmap.add_styled_map(
            project_id,
            AddStyledMapOptions(
                name=name,
                qgisproject=qgisproject,
            ),
        )

        if not new_styled_map:
            # エラーメッセージを表示
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Failed to create the map.")
            )
            return

        # 上書き保存して新しいスタイルマップを表示
        self.refresh()
        iface.messageBar().pushSuccess(
            self.tr("Success"),
            self.tr("Map '{}' has been created successfully.").format(name),
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
        delete_tempfile(tmp_path)


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
        delete_tempfile(tmp_path)


def delete_tempfile(tmp_path: str):
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
        QgsMessageLog.logMessage(
            f"Temporary file {tmp_path} removed.", LOG_CATEGORY, Qgis.Info
        )
    else:
        QgsMessageLog.logMessage(
            f"Temporary file {tmp_path} does not exist.", LOG_CATEGORY, Qgis.Warning
        )
