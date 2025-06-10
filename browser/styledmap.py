import os
import tempfile

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)
from qgis.core import Qgis, QgsDataItem, QgsMessageLog, QgsProject
from qgis.utils import iface

from ..imgs import IMGS_PATH
from ..qgishub import api
from ..qgishub.api.project_styledmap import (
    AddStyledMapOptions,
    QgishubStyledMap,
    UpdateStyledMapOptions,
)
from ..qgishub.constants import LOG_CATEGORY
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

    def actions(self, parent):
        actions = []

        # スタイルマップ適用アクション
        apply_action = QAction("QGISに読み込む", parent)
        apply_action.triggered.connect(self.apply_style)
        actions.append(apply_action)

        # スタイルマップ上書き保存アクション
        save_action = QAction("上書き保存", parent)
        save_action.triggered.connect(self.apply_qgisproject_to_styledmap)
        actions.append(save_action)

        # スタイルマップ編集アクション
        edit_action = QAction("メタデータ編集", parent)
        edit_action.triggered.connect(self.update_metadata_styled_map)
        actions.append(edit_action)

        # スタイルマップ削除アクション
        delete_action = QAction("削除", parent)
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
                    "Success",
                    f"Map '{self.styled_map.name}' has been loaded successfully.",
                )
            else:
                QMessageBox.critical(
                    None, "Error", f"Failed to load map '{self.styled_map.name}'."
                )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"スタイル適用エラー: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(None, "Error", f"Error loading map: {str(e)}")

    def handleDoubleClick(self):
        """ダブルクリック時にスタイルを適用する"""
        self.apply_style()
        return True

    def update_metadata_styled_map(self):
        """Mapを編集する"""
        try:
            # ダイアログ作成
            dialog = QDialog()
            dialog.setWindowTitle("Map編集")

            # レイアウト作成
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # フィールド作成（タイトルのみ編集可）
            name_field = QLineEdit(self.styled_map.name)
            is_public_field = QCheckBox("公開する")
            is_public_field.setChecked(self.styled_map.isPublic)

            # フォームにフィールドを追加
            form_layout.addRow("名前:", name_field)
            form_layout.addRow("公開:", is_public_field)

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
                            "Success",
                            f"Map '{new_name}' has been updated successfully.",
                        )
                    else:
                        QgsMessageLog.logMessage(
                            "Mapの上書き保存に失敗しました", LOG_CATEGORY, Qgis.Critical
                        )
                        QMessageBox.critical(None, "Error", "Failed to update the map.")

        except Exception as e:
            QgsMessageLog.logMessage(
                f"スタイルマップ編集エラー: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(None, "Error", f"Error updating map: {str(e)}")

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
            iface.messageBar().pushSuccess(
                "Success",
                f"Map '{self.styled_map.name}' has been saved successfully.",
            )
        else:
            QgsMessageLog.logMessage(
                "Mapの上書き保存に失敗しました", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(None, "Error", "Failed to save the map.")

    def delete_styled_map(self):
        """スタイルマップを削除する"""
        try:
            # 削除確認
            confirm = QMessageBox.question(
                None,
                "Map削除",
                f"Map '{self.styled_map.name}' を削除してもよろしいですか？",
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
                        "Success",
                        f"Map '{self.styled_map.name}' has been deleted successfully.",
                    )
                else:
                    QgsMessageLog.logMessage(
                        "Mapの削除に失敗しました", LOG_CATEGORY, Qgis.Critical
                    )
                    QMessageBox.critical(None, "Error", "Failed to delete the map.")

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Map削除エラー: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )
            QMessageBox.critical(None, "Error", f"Error deleting map: {str(e)}")


class StyledMapRoot(QgsDataItem):
    """スタイルマップルートアイテム（ブラウザ用）"""

    def __init__(self, parent, name, path, project_id):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent,
            name,
            path,
        )
        self.project_id = project_id
        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon_style.svg")))
        self.populate()

    def actions(self, parent):
        actions = []

        # スタイルマップ追加アクション
        add_action = QAction("QGISの地図を新規Mapに保存", parent)
        add_action.triggered.connect(self.add_styled_map)
        actions.append(add_action)

        # 再読み込みアクション
        refresh_action = QAction("再読み込み", parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def add_styled_map(self):
        """新しいスタイルマップを追加する"""
        try:
            # ダイアログ作成
            dialog = QDialog()
            dialog.setWindowTitle("Map追加")

            # レイアウト作成
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # フィールド作成（タイトルのみ編集可）
            name_field = QLineEdit()
            is_public_field = QCheckBox("公開する")

            # フォームにフィールドを追加
            form_layout.addRow("名前:", name_field)
            form_layout.addRow("公開:", is_public_field)

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
                # QGISプロジェクト情報はバックグラウンドで取得
                qgisproject = get_qgisproject_str()

                if name:
                    # スタイルマップ作成
                    new_styled_map = api.project_styledmap.add_styled_map(
                        self.project_id,
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
                            "Success",
                            f"Map '{name}' has been created successfully.",
                        )
                    else:
                        # エラーメッセージを表示
                        QMessageBox.critical(None, "Error", "Failed to create the map.")

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Map追加エラー: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def createChildren(self):
        """子アイテムを作成する"""
        try:
            # プロジェクトのスタイルマップを取得
            styled_maps = api.project_styledmap.get_styled_maps(self.project_id)

            if not styled_maps:
                return [ErrorItem(self, "Mapsがありません。")]

            children = []
            for styled_map in styled_maps:
                path = f"{self.path()}/{styled_map.id}"
                child = StyledMapItem(self, path, styled_map)
                children.append(child)

            return children

        except Exception as e:
            return [ErrorItem(self, f"エラー: {str(e)}")]


def get_qgisproject_str() -> str:
    project = QgsProject.instance()
    with tempfile.NamedTemporaryFile(suffix=".qgs", mode="w", encoding="utf-8") as tmp:
        project.write(tmp.name)
        with open(tmp.name, "r", encoding="utf-8") as f:
            return f.read()


def load_project_from_xml(xml_string: str) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".qgs", mode="w", encoding="utf-8") as tmp:
        tmp.write(xml_string)
        tmp_path = tmp.name
        # QGISプロジェクトを読み込む
        project = QgsProject.instance()
        res = project.read(tmp_path)
        return res
