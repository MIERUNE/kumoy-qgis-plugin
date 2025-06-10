import os

from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLineEdit,
    QMessageBox,
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
            # XML文字列をQGISプロジェクトにロード（確認ダイアログなしで直接上書き）
            success = load_project_direct(self.styled_map.qgisproject)
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
                        QMessageBox.critical(None, "Error", "Failed to update the map.")

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating map: {str(e)}", LOG_CATEGORY, Qgis.Critical
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
            QMessageBox.information(
                None,
                "Success",
                f"Map '{self.styled_map.name}' has been saved successfully.",
            )
        else:
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
                    QMessageBox.critical(None, "Error", "Failed to delete the map.")

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error deleting map: {str(e)}", LOG_CATEGORY, Qgis.Critical
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
    """Get QGIS project as XML string after saving"""
    project = QgsProject.instance()

    # Check if project has a file path
    current_path = project.fileName()

    if not current_path:
        # Project is untitled, ask user to save it first
        reply = QMessageBox.question(
            None,
            "プロジェクトの保存",
            "現在のプロジェクトは保存されていません。新規保存しますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply == QMessageBox.Yes:
            # Ask user where to save
            file_path, _ = QFileDialog.getSaveFileName(
                None, "プロジェクトを保存", "", "QGIS Project Files (*.qgs *.qgz)"
            )

            if file_path:
                # Save project
                if project.write(file_path):
                    current_path = file_path
                else:
                    QMessageBox.critical(
                        None, "エラー", "プロジェクトの保存に失敗しました。"
                    )
                    return ""
            else:
                return ""
        else:
            return ""
    else:
        # Project already has a path, ask if user wants to overwrite
        reply = QMessageBox.question(
            None,
            "プロジェクトの上書き保存",
            f"{LOG_CATEGORY}と同期するため、現在のプロジェクト '{os.path.basename(current_path)}' を上書き保存して良いですか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply == QMessageBox.Yes:
            # Save project
            if not project.write():
                QMessageBox.critical(
                    None, "エラー", "プロジェクトの保存に失敗しました。"
                )
                return ""
        else:
            # User declined overwriting, offer to save as new file
            new_path = _offer_save_as_new_file("QGIS Project Files (*.qgs *.qgz)")
            if not new_path:
                return ""

            # Save project to new file
            if project.write(new_path):
                current_path = new_path
            else:
                QMessageBox.critical(
                    None, "エラー", "プロジェクトの保存に失敗しました。"
                )
                return ""

    # Read the saved project file and return its content
    try:
        with open(current_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error reading project file: {str(e)}", LOG_CATEGORY, Qgis.Critical
        )
        return ""


def load_project_from_xml(xml_string: str) -> bool:
    """Load QGIS project from XML string with user confirmation"""
    # Ask user what they want to do
    user_choice = _ask_user_load_choice()

    if user_choice == "cancel":
        return False
    elif user_choice == "save_as":
        return _save_project_as_new_file(xml_string)
    elif user_choice == "overwrite":
        return _overwrite_current_project(xml_string)

    return False


def _ask_user_load_choice() -> str:
    """Ask user how to handle project loading"""
    msgBox = QMessageBox()
    msgBox.setWindowTitle("プロジェクトの読み込み")
    msgBox.setText("スタイルマップを読み込みます。どのように処理しますか？")

    # Add buttons
    overwrite_btn = msgBox.addButton(
        "現在のプロジェクトを上書き", QMessageBox.AcceptRole
    )
    save_as_btn = msgBox.addButton("名前を付けて保存", QMessageBox.AcceptRole)
    cancel_btn = msgBox.addButton("キャンセル", QMessageBox.RejectRole)

    msgBox.exec_()

    if msgBox.clickedButton() == cancel_btn:
        return "cancel"
    elif msgBox.clickedButton() == overwrite_btn:
        return "overwrite"
    elif msgBox.clickedButton() == save_as_btn:
        return "save_as"

    return "cancel"


def _overwrite_current_project(xml_string: str) -> bool:
    """Overwrite current project with XML content"""
    # Confirm overwrite
    reply = QMessageBox.question(
        None,
        "確認",
        "現在のプロジェクトを上書きしてもよろしいですか？\n未保存の変更は失われます。",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )

    if reply != QMessageBox.Yes:
        return False

    project = QgsProject.instance()
    current_path = project.fileName()

    if not current_path:
        return _handle_no_project_file(xml_string)

    return _overwrite_existing_project_file(current_path, xml_string)


def _handle_no_project_file(xml_string: str) -> bool:
    """Handle case when current project has no file path"""
    reply = QMessageBox.question(
        None,
        "プロジェクトの保存",
        "現在のプロジェクトは保存されていません。\n新しいファイルとして保存しますか？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )

    if reply != QMessageBox.Yes:
        return False

    return _save_project_as_new_file(xml_string)


def _overwrite_existing_project_file(current_path: str, xml_string: str) -> bool:
    """Overwrite existing project file with XML content"""
    project = QgsProject.instance()

    # Backup current content
    backup_content = _read_file_safe(current_path)

    try:
        # Write new content
        with open(current_path, "w", encoding="utf-8") as f:
            f.write(xml_string)

        # Reload project
        success = project.read(current_path)

        if success:
            QMessageBox.information(None, "成功", "プロジェクトを読み込みました。")
            return True
        else:
            # Restore backup if failed
            if backup_content:
                _write_file_safe(current_path, backup_content)
            QMessageBox.critical(
                None, "エラー", "プロジェクトの読み込みに失敗しました。"
            )
            return False

    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error overwriting project: {str(e)}", LOG_CATEGORY, Qgis.Critical
        )
        QMessageBox.critical(
            None, "エラー", f"プロジェクトの上書きに失敗しました: {str(e)}"
        )
        return False


def _save_project_as_new_file(xml_string: str) -> bool:
    """Save project as a new file"""
    file_path, _ = QFileDialog.getSaveFileName(
        None, "プロジェクトを保存", "", "QGIS Project Files (*.qgs)"
    )

    if not file_path:
        return False

    return _save_and_load_project(xml_string, file_path)


def _read_file_safe(file_path: str) -> str:
    """Safely read file content, return None if failed"""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _write_file_safe(file_path: str, content: str) -> bool:
    """Safely write content to file"""
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception:
        return False


def _offer_save_as_new_file(file_filter: str) -> str:
    """Offer user to save as new file to protect existing project

    Returns:
        str: New file path if user accepted, empty string otherwise
    """
    reply = QMessageBox.question(
        None,
        "名前を付けて保存",
        "既存のプロジェクトを保護するため、新しいファイル名で保存しますか？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.Yes,
    )

    if reply != QMessageBox.Yes:
        return ""

    # Ask user where to save the new project
    file_path, _ = QFileDialog.getSaveFileName(
        None, "新しいプロジェクトを保存", "", file_filter
    )

    return file_path if file_path else ""


def _save_and_load_project(xml_string: str, file_path: str) -> bool:
    """Save XML content to file and load project

    Args:
        xml_string: XML content to save
        file_path: Path to save the file

    Returns:
        bool: True if save and load succeeded
    """
    try:
        # Write XML to file
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(xml_string)

        # Load project from saved file
        project = QgsProject.instance()
        success = project.read(file_path)

        if success:
            QMessageBox.information(
                None,
                "成功",
                f"プロジェクトを '{os.path.basename(file_path)}' として保存し、読み込みました。",
            )
        else:
            QMessageBox.critical(
                None, "エラー", "プロジェクトの読み込みに失敗しました。"
            )

        return success

    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error saving project: {str(e)}", LOG_CATEGORY, Qgis.Critical
        )
        QMessageBox.critical(
            None, "エラー", f"プロジェクトの保存に失敗しました: {str(e)}"
        )
        return False


def _validate_qgis_project_xml(xml_string: str) -> bool:
    """Validate if XML string is a valid QGIS project"""
    try:
        from xml.etree import ElementTree as ET

        # Parse XML
        root = ET.fromstring(xml_string)

        # Check if root element is 'qgis'
        if root.tag != "qgis":
            QgsMessageLog.logMessage(
                f"Invalid root element: {root.tag}, expected 'qgis'",
                LOG_CATEGORY,
                Qgis.Critical,
            )
            return False

        # Check if version attribute exists
        version = root.get("version")
        if not version:
            QgsMessageLog.logMessage(
                "No version attribute found in qgis element", LOG_CATEGORY, Qgis.Warning
            )
        else:
            QgsMessageLog.logMessage(
                f"QGIS project version: {version}", LOG_CATEGORY, Qgis.Info
            )

        # Check for essential project elements
        essential_elements = ["projectname", "title"]
        for element_name in essential_elements:
            elements = root.findall(f".//{element_name}")
            QgsMessageLog.logMessage(
                f"Found {len(elements)} {element_name} elements",
                LOG_CATEGORY,
                Qgis.Info,
            )

        return True

    except ET.ParseError as e:
        QgsMessageLog.logMessage(
            f"XML parse error: {str(e)}", LOG_CATEGORY, Qgis.Critical
        )
        return False
    except Exception as e:
        QgsMessageLog.logMessage(
            f"XML validation error: {str(e)}", LOG_CATEGORY, Qgis.Critical
        )
        return False


def load_project_direct(xml_string: str) -> bool:
    """Load QGIS project directly without user confirmation (for apply_style)"""
    project = QgsProject.instance()
    current_path = project.fileName()

    # Log XML content for debugging
    QgsMessageLog.logMessage(
        f"Loading project directly. XML length: {len(xml_string)} chars",
        LOG_CATEGORY,
        Qgis.Info,
    )
    QgsMessageLog.logMessage(
        f"XML content preview: {xml_string[:500]}...", LOG_CATEGORY, Qgis.Info
    )

    if not current_path:
        # No current project file, ask user to save first
        reply = QMessageBox.question(
            None,
            "プロジェクトの保存",
            "現在のプロジェクトは保存されていません。\n新しいファイルとして保存してからマップを読み込みますか？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )

        if reply != QMessageBox.Yes:
            return False

        file_path, _ = QFileDialog.getSaveFileName(
            None, "プロジェクトを保存", "", "QGIS Project Files (*.qgs)"
        )

        if not file_path:
            return False

        current_path = file_path
    else:
        # Project file exists, ask for confirmation before overwriting
        reply = QMessageBox.question(
            None,
            "プロジェクトの上書き確認",
            f"現在のプロジェクト '{os.path.basename(current_path)}' をスタイルマップで上書きしますか？\n\n警告: 現在のプロジェクトの内容は失われます。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,  # Default to No for safety
        )

        if reply != QMessageBox.Yes:
            # User declined overwriting, offer to save as new file
            new_path = _offer_save_as_new_file("QGIS Project Files (*.qgs)")
            if not new_path:
                return False

            current_path = new_path

    # Backup current content if file exists
    backup_content = (
        _read_file_safe(current_path) if os.path.exists(current_path) else None
    )

    try:
        # Write XML to project file
        with open(current_path, "w", encoding="utf-8") as f:
            f.write(xml_string)

        QgsMessageLog.logMessage(
            f"XML written to file: {current_path}", LOG_CATEGORY, Qgis.Info
        )

        # Validate XML before reading
        if not _validate_qgis_project_xml(xml_string):
            QgsMessageLog.logMessage(
                "XML validation failed - not a valid QGIS project",
                LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None, "エラー", "有効なQGISプロジェクトファイルではありません。"
            )
            return False

        # Check if file was written correctly
        written_content = _read_file_safe(current_path)
        if not written_content or len(written_content) != len(xml_string):
            QgsMessageLog.logMessage(
                f"File write verification failed. Expected: {len(xml_string)}, Got: {len(written_content) if written_content else 0}",
                LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(None, "エラー", "ファイルの書き込みに失敗しました。")
            return False

        # Clear current project first
        project.clear()

        # Reload project
        success = project.read(current_path)

        QgsMessageLog.logMessage(
            f"Project read result: {success}",
            LOG_CATEGORY,
            Qgis.Info if success else Qgis.Critical,
        )

        # If failed, try to get more detailed error information
        if not success:
            # Check if the file exists and is readable
            if not os.path.exists(current_path):
                QgsMessageLog.logMessage(
                    f"Project file does not exist: {current_path}",
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
            elif not os.access(current_path, os.R_OK):
                QgsMessageLog.logMessage(
                    f"Project file is not readable: {current_path}",
                    LOG_CATEGORY,
                    Qgis.Critical,
                )
            else:
                # Check file size
                file_size = os.path.getsize(current_path)
                QgsMessageLog.logMessage(
                    f"Project file exists but read failed. Size: {file_size} bytes",
                    LOG_CATEGORY,
                    Qgis.Critical,
                )

        if success:
            return True
        else:
            # Restore backup if failed and backup exists
            if backup_content and os.path.exists(current_path):
                _write_file_safe(current_path, backup_content)
            QMessageBox.critical(
                None, "エラー", "プロジェクトの読み込みに失敗しました。"
            )
            return False

    except Exception as e:
        QgsMessageLog.logMessage(
            f"Error in load_project_direct: {str(e)}", LOG_CATEGORY, Qgis.Critical
        )
        # Restore backup if failed and backup exists
        if backup_content and os.path.exists(current_path):
            _write_file_safe(current_path, backup_content)
        QMessageBox.critical(
            None, "エラー", f"プロジェクトの読み込みに失敗しました: {str(e)}"
        )
        return False
