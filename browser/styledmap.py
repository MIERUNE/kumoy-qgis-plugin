import os
import tempfile
import webbrowser
from typing import Literal

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
from ..settings_manager import get_settings, store_setting
from ..strato import api, constants
from .utils import ErrorItem


class StyledMapItem(QgsDataItem):
    """スタイルマップアイテム（ブラウザ用）"""

    def __init__(
        self,
        parent,
        path: str,
        styled_map: api.project_styledmap.StratoStyledMap,
        role: Literal["ADMIN", "OWNER", "MEMBER"],
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=styled_map.name,
            path=path,
        )

        self.styled_map = styled_map
        self.role = role

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

        if self.role in ["ADMIN", "OWNER"]:
            # スタイルマップ上書き保存アクション
            save_action = QAction(self.tr("Overwrite with current state"), parent)
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

        if self.styled_map.isPublic:
            # 公開マップの場合、公開ページを開くアクション
            open_public_action = QAction(self.tr("Open Public Page"), parent)
            open_public_action.triggered.connect(self.open_public_page)
            actions.append(open_public_action)

        return actions

    def open_public_page(self):
        """公開ページをブラウザで開く"""
        url = (
            f"{api.config.get_api_config().SERVER_URL}/public/map/{self.styled_map.id}"
        )
        webbrowser.open(url)

    def apply_style(self):
        """スタイルをQGISレイヤーに適用する"""

        # QGISプロジェクトに変更がある場合、適用前に確認ダイアログを表示
        if QgsProject.instance().isDirty():
            confirm = QMessageBox.question(
                None,
                self.tr("Load Map"),
                self.tr(
                    "Are you sure you want to load the map '{}'? This will replace your current project."
                ).format(self.styled_map.name),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if confirm != QMessageBox.Yes:
                return

        try:
            styled_map_detail = api.project_styledmap.get_styled_map(self.styled_map.id)
        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error loading map: {}").format(str(e)),
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error loading map: {}").format(str(e)),
            )
            return

        # XML文字列をQGISプロジェクトにロード
        load_project_from_xml(styled_map_detail.qgisproject)

        QgsProject.instance().setTitle(self.styled_map.name)
        QgsProject.instance().setDirty(False)

    def handleDoubleClick(self):
        """ダブルクリック時にスタイルを適用する"""
        self.apply_style()
        return True

    def update_metadata_styled_map(self):
        """Mapを編集する"""
        # ダイアログ作成
        dialog = QDialog()
        dialog.setWindowTitle(self.tr("Edit Map"))

        # レイアウト作成
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # フィールド作成（タイトルのみ編集可）
        name_field = QLineEdit(self.styled_map.name)
        name_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_NAME)
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
        if not result:
            return

        # 値を取得（タイトルと公開設定のみ）
        new_name = name_field.text()
        new_is_public = is_public_field.isChecked()

        if new_name == "":
            return

        try:
            # スタイルマップ上書き保存
            updated_styled_map = api.project_styledmap.update_styled_map(
                self.styled_map.id,
                api.project_styledmap.UpdateStyledMapOptions(
                    name=new_name,
                    isPublic=new_is_public,
                ),
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error updating map: {}").format(str(e)),
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error updating map: {}").format(str(e)),
            )
            return

        # Itemを更新
        self.styled_map = updated_styled_map
        self.setName(updated_styled_map.name)
        self.refresh()

        iface.messageBar().pushSuccess(
            self.tr("Success"),
            self.tr("Map '{}' has been updated successfully.").format(new_name),
        )

    def apply_qgisproject_to_styledmap(self):
        # 確認ダイアログ
        confirm = QMessageBox.question(
            None,
            self.tr("Save Map"),
            self.tr(
                "Are you sure you want to overwrite the map '{}' with the current project state?"
            ).format(self.styled_map.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        try:
            new_qgisproject = get_qgisproject_str()

            # スタイルマップ上書き保存
            updated_styled_map = api.project_styledmap.update_styled_map(
                self.styled_map.id,
                api.project_styledmap.UpdateStyledMapOptions(
                    qgisproject=new_qgisproject,
                ),
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error saving map: {}").format(str(e)),
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Error saving map: {}").format(str(e))
            )
            return

        # Itemを更新
        self.styled_map = updated_styled_map
        self.setName(updated_styled_map.name)
        self.refresh()

        iface.messageBar().pushSuccess(
            self.tr("Success"),
            self.tr("Map '{}' has been saved successfully.").format(
                self.styled_map.name
            ),
        )

    def delete_styled_map(self):
        """スタイルマップを削除する"""
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
            try:
                api.project_styledmap.delete_styled_map(self.styled_map.id)

                # 親アイテムを上書き保存して最新のリストを表示
                self.parent().refresh()
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("Map '{}' has been deleted successfully.").format(
                        self.styled_map.name
                    ),
                )

            except Exception as e:
                QgsMessageLog.logMessage(
                    self.tr("Error deleting map: {}").format(str(e)),
                    constants.LOG_CATEGORY,
                    Qgis.Critical,
                )
                QMessageBox.critical(
                    None, self.tr("Error"), self.tr("Failed to delete the map.")
                )


class StyledMapRoot(QgsDataItem):
    """スタイルマップルートアイテム（ブラウザ用）"""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        organization: api.organization.OrganizationDetail,
        project: api.project.ProjectDetail,
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent,
            name,
            path,
        )
        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon_style.svg")))
        self.populate()

        self.organization = organization
        self.project = project

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("StyledMapRoot", message)

    def actions(self, parent):
        actions = []

        # Map新規作成
        new_action = QAction(self.tr("Upload current map"), parent)
        new_action.triggered.connect(self.add_styled_map)
        actions.append(new_action)

        return actions

    def add_styled_map(
        self,
    ):
        """新しいスタイルマップを追加する"""

        try:
            # Check plan limits before creating styled map
            plan_limit = api.plan.get_plan_limits(self.organization.subscriptionPlan)
            current_styled_maps = api.project_styledmap.get_styled_maps(self.project.id)
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

            qgisproject = get_qgisproject_str()

            # ダイアログ作成
            dialog = QDialog()
            dialog.setWindowTitle(self.tr("Add Map"))

            # レイアウト作成
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # フィールド作成（タイトルのみ編集可）
            name_field = QLineEdit()
            name_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_NAME)
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

            # スタイルマップ作成
            new_styled_map = api.project_styledmap.add_styled_map(
                self.project.id,
                api.project_styledmap.AddStyledMapOptions(
                    name=name,
                    qgisproject=qgisproject,
                ),
            )

            # 保存完了後のUI更新
            QgsProject.instance().setTitle(new_styled_map.name)
            QgsProject.instance().setDirty(False)
            self.refresh()
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("Map '{}' has been created successfully.").format(name),
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error adding map: {str(e)}", constants.LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(
                None, self.tr("Error"), self.tr("Error adding map: {}").format(str(e))
            )

    def createChildren(self):
        """子アイテムを作成する"""
        try:
            project_id = get_settings().selected_project_id

            if not project_id:
                return [ErrorItem(self, self.tr("No project selected"))]

            # プロジェクトのスタイルマップを取得
            styled_maps = api.project_styledmap.get_styled_maps(project_id)

            if not styled_maps:
                return [ErrorItem(self, self.tr("No maps available."))]

            children = []
            for styled_map in styled_maps:
                path = f"{self.path()}/{styled_map.id}"
                child = StyledMapItem(self, path, styled_map, self.project.role)
                children.append(child)

            return children

        except Exception as e:
            return [ErrorItem(self, self.tr("Error: {}").format(str(e)))]


def get_qgisproject_str() -> str:
    with tempfile.NamedTemporaryFile(
        suffix=".qgs", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp_path = tmp.name

    project = QgsProject.instance()
    project.write(tmp_path)

    with open(tmp_path, "r", encoding="utf-8") as f:
        qgs_str = f.read()

    # 文字数制限チェック
    LENGTH_LIMIT = 3000000  # 300万文字
    actual_length = len(qgs_str)
    if actual_length > LENGTH_LIMIT:
        err = f"Project file size is too large. Limit is {LENGTH_LIMIT} bytes. your: {actual_length} bytes"
        QgsMessageLog.logMessage(
            err,
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )
        raise Exception(err)

    delete_tempfile(tmp_path)
    return qgs_str


def load_project_from_xml(xml_string: str) -> bool:
    with tempfile.NamedTemporaryFile(
        suffix=".qgs", mode="w", encoding="utf-8", delete=False
    ) as tmp:
        tmp.write(xml_string)
        tmp_path = tmp.name

        project = QgsProject.instance()
        res = project.read(tmp_path)
        return res

    project = QgsProject.instance()
    res = project.read(tmp_path)
    delete_tempfile(tmp_path)
    return res


def delete_tempfile(tmp_path: str):
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
        QgsMessageLog.logMessage(
            f"Temporary file {tmp_path} removed.", constants.LOG_CATEGORY, Qgis.Info
        )
    else:
        QgsMessageLog.logMessage(
            f"Temporary file {tmp_path} does not exist.",
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )
