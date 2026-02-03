import os
import webbrowser
from typing import Literal

from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
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

from ...kumoy import api, constants, local_cache
from ...kumoy.api.error import format_api_error
from ...kumoy.local_cache.map import write_qgsfile
from ...pyqt_version import (
    Q_MESSAGEBOX_STD_BUTTON,
    QT_DIALOG_BUTTON_CANCEL,
    QT_DIALOG_BUTTON_OK,
    exec_dialog,
)
from ...settings_manager import get_settings
from ...ui.layers.convert_vector import (
    get_local_vector_layers,
    check_vector_layers_modified,
    convert_multiple_layers_to_kumoy,
)
from ..icons import BROWSER_MAP_ICON
from .utils import ErrorItem


class StyledMapItem(QgsDataItem):
    def __init__(
        self,
        parent,
        path: str,
        styled_map: api.styledmap.KumoyStyledMap,
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
        self.setIcon(BROWSER_MAP_ICON)

        self.populate()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("StyledMapItem", message)

    def actions(self, parent):
        actions = []

        # スタイルマップ適用アクション
        apply_action = QAction(self.tr("Load into QGIS"), parent)
        apply_action.triggered.connect(self.apply_style)
        actions.append(apply_action)

        if self.styled_map.isPublic:
            # 公開マップの場合、公開ページを開くアクション
            open_public_action = QAction(self.tr("Open Public Page"), parent)
            open_public_action.triggered.connect(self.open_public_page)
            actions.append(open_public_action)

        # Clear map cache action
        clear_cache_action = QAction(self.tr("Clear Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_map_cache)
        actions.append(clear_cache_action)

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

        return actions

    def open_public_page(self):
        """公開ページをブラウザで開く"""
        url = (
            f"{api.config.get_api_config().SERVER_URL}/public/map/{self.styled_map.id}"
        )
        webbrowser.open(url)

    def apply_style(self):
        """KumoyサーバーからMapを取得してQGISに適用する"""

        # QGISプロジェクトに変更がある場合、適用前に確認ダイアログを表示
        if QgsProject.instance().isDirty():
            confirm = QMessageBox.question(
                None,
                self.tr("Load Map"),
                self.tr(
                    "Are you sure you want to load the map '{}'? This will replace your current project."
                ).format(self.styled_map.name),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )
            if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
                return

        try:
            styled_map_detail = api.styledmap.get_styled_map(self.styled_map.id)
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                self.tr("Error loading map: {}").format(error_text),
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error loading map: {}").format(error_text),
            )
            return

        # XML文字列をQGISプロジェクトにロード
        qgs_path = local_cache.map.get_filepath(styled_map_detail.id)
        with open(qgs_path, "w", encoding="utf-8") as f:
            f.write(styled_map_detail.qgisproject)
            iface.addProject(qgs_path)

        QgsProject.instance().setTitle(self.styled_map.name)
        # store map kumoy info to project instance
        QgsProject.instance().setCustomVariables(
            {
                "kumoy_map_id": self.styled_map.id,
            }
        )
        QgsProject.instance().setDirty(False)

    def handleDoubleClick(self):
        self.apply_style()
        return True

    def update_metadata_styled_map(self):
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
        attribution_field = QLineEdit(self.styled_map.attribution)
        attribution_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION)
        description_field = QLineEdit(self.styled_map.description)
        description_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION)

        # フォームにフィールドを追加
        form_layout.addRow(
            self.tr("Name:") + ' <span style="color: red;">*</span>', name_field
        )
        form_layout.addRow(self.tr("Public:"), is_public_field)
        form_layout.addRow(self.tr("Description:"), description_field)
        form_layout.addRow(self.tr("Attribution:"), attribution_field)

        # ボタン作成
        button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        # Disable OK if name is empty
        ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
        ok_button.setEnabled(bool(name_field.text().strip()))
        name_field.textChanged.connect(
            lambda text: ok_button.setEnabled(bool(text.strip()))
        )

        # ダイアログにレイアウトを追加
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        dialog.setLayout(layout)

        # ダイアログ表示
        result = exec_dialog(dialog)
        if not result:
            return

        # 値を取得（タイトルと公開設定のみ）
        new_name = name_field.text()
        new_is_public = is_public_field.isChecked()
        new_attribution = attribution_field.text()
        new_description = description_field.text()

        if new_name == "":
            return

        try:
            # スタイルマップ上書き保存
            updated_styled_map = api.styledmap.update_styled_map(
                self.styled_map.id,
                api.styledmap.UpdateStyledMapOptions(
                    name=new_name,
                    isPublic=new_is_public,
                    attribution=new_attribution,
                    description=new_description,
                ),
            )
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                self.tr("Error updating map: {}").format(error_text),
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error updating map: {}").format(error_text),
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
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )
        if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return

        # HACK: to ensure extents of all layers are calculated - Issue #311
        for layer in QgsProject.instance().mapLayers().values():
            layer.extent()

        try:
            new_qgisproject = write_qgsfile(self.styled_map.id)

            # Overwrite styled map
            updated_styled_map = api.styledmap.update_styled_map(
                self.styled_map.id,
                api.styledmap.UpdateStyledMapOptions(
                    qgisproject=new_qgisproject,
                ),
            )
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                self.tr("Error saving map: {}").format(error_text),
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error saving map: {}").format(error_text),
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
        # 削除確認
        confirm = QMessageBox.question(
            None,
            self.tr("Delete Map"),
            self.tr("Are you sure you want to delete map '{}'?").format(
                self.styled_map.name
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            # スタイルマップ削除
            try:
                api.styledmap.delete_styled_map(self.styled_map.id)

                # 親アイテムを上書き保存して最新のリストを表示
                self.parent().refresh()
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("Map '{}' has been deleted successfully.").format(
                        self.styled_map.name
                    ),
                )

            except Exception as e:
                error_text = format_api_error(e)
                QgsMessageLog.logMessage(
                    self.tr("Error deleting map: {}").format(error_text),
                    constants.LOG_CATEGORY,
                    Qgis.Critical,
                )
                QMessageBox.critical(
                    None, self.tr("Error"), self.tr("Failed to delete the map.")
                )

            # Remove cached qgs file
            map_path = local_cache.map.get_filepath(self.styled_map.id)
            if os.path.exists(map_path):
                local_cache.map.clear(self.styled_map.id)
                QgsMessageLog.logMessage(
                    f"Cached map file {map_path} removed.",
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )

    def clear_map_cache(self):
        # Show confirmation dialog
        confirm = QMessageBox.question(
            None,
            self.tr("Clear Map Cache Data"),
            self.tr(
                "This will clear the local cache for map '{}'.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(self.styled_map.name),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            # Clear cache for this specific map
            cache_cleared = local_cache.map.clear(self.styled_map.id)

            if cache_cleared:
                QgsMessageLog.logMessage(
                    self.tr("Cache cleared for map '{}'").format(self.styled_map.name),
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("Cache cleared successfully for map '{}'.").format(
                        self.styled_map.name
                    ),
                )
            else:
                iface.messageBar().pushMessage(
                    self.tr("Cache Clear Failed"),
                    self.tr("Cache could not be cleared for map '{}'. ").format(
                        self.styled_map.name
                    ),
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
        self.setIcon(BROWSER_MAP_ICON)
        self.populate()

        self.organization = organization
        self.project = project

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("StyledMapRoot", message)

    def actions(self, parent):
        actions = []

        if self.project.role not in ["ADMIN", "OWNER"]:
            return actions

        # 空のMapを作成する
        empty_map_action = QAction(self.tr("Create New Map"), parent)
        empty_map_action.triggered.connect(self.add_empty_map)
        actions.append(empty_map_action)

        # Upload current QGIS project as new Kumoy styled map
        new_action = QAction(self.tr("Save Current Project As..."), parent)
        new_action.triggered.connect(self.add_styled_map)
        actions.append(new_action)

        # Clear map cache data
        clear_all_cache_action = QAction(self.tr("Clear Map Cache Data"), parent)
        clear_all_cache_action.triggered.connect(self.clear_all_map_cache)
        actions.append(clear_all_cache_action)

        return actions

    def add_empty_map(self):
        if QgsProject.instance().isDirty():
            confirm = QMessageBox.question(
                None,
                self.tr("Create new Map"),
                self.tr(
                    "Creating an new map will clear your current project. Continue?"
                ),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )
            if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
                return

        self.add_styled_map(clear=True)

    def add_styled_map(self, clear=False):
        """Add a new map to kumoy server
        Options:
        clear - whether to clear current QGIS project"""

        # HACK: to ensure extents of all layers are calculated - Issue #311
        for layer in QgsProject.instance().mapLayers().values():
            layer.extent()

        # Find local layers in current QGIS project
        local_layers = get_local_vector_layers()

        # Check if any local layer has unsaved edits
        is_modified = check_vector_layers_modified(local_layers)
        if is_modified:
            QMessageBox.warning(
                None,
                self.tr("Cannot Add Map"),
                self.tr(
                    "Please save or discard your local layer edits before saving map."
                ),
            )
            return

        try:
            # Check plan limits before creating styled map
            plan_limit = api.plan.get_plan_limits(self.organization.subscriptionPlan)
            current_styled_maps = api.styledmap.get_styled_maps(self.project.id)
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
            name_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_NAME)
            attribution_field = QLineEdit()
            attribution_field.setMaxLength(
                constants.MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION
            )
            description_field = QLineEdit()
            description_field.setMaxLength(
                constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION
            )
            is_public_field = QCheckBox(self.tr("Make Public"))

            # フォームにフィールドを追加
            form_layout.addRow(
                self.tr("Name:") + ' <span style="color: red;">*</span>', name_field
            )
            form_layout.addRow(self.tr("Description:"), description_field)
            form_layout.addRow(self.tr("Attribution:"), attribution_field)
            form_layout.addRow(self.tr("Public:"), is_public_field)

            # ボタン作成
            button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)

            # Disable OK if name is empty
            ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
            ok_button.setEnabled(bool(name_field.text().strip()))
            name_field.textChanged.connect(
                lambda text: ok_button.setEnabled(bool(text.strip()))
            )

            # ダイアログにレイアウトを追加
            layout.addLayout(form_layout)
            layout.addWidget(button_box)
            dialog.setLayout(layout)

            # ダイアログ表示
            result = exec_dialog(dialog)

            if not result:
                return

            # 値を取得（タイトルと公開設定のみ）
            name = name_field.text()
            attribution = attribution_field.text()
            description = description_field.text()
            is_public = is_public_field.isChecked()

            if not name:
                return

            if clear:
                # 空のQGISプロジェクトを作成
                QgsProject.instance().clear()

            # Convert local layers to Kumoy layers
            if local_layers:
                convert_confirm = QMessageBox.question(
                    None,
                    self.tr("Convert Local Layers to Kumoy Layers"),
                    self.tr(
                        "There are {} local vector layers in the current project.\n"
                        "Do you want to convert them to Kumoy layers?"
                    ).format(len(local_layers)),
                    Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                    Q_MESSAGEBOX_STD_BUTTON.Yes,
                )
                if convert_confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
                    conversion_errors = convert_multiple_layers_to_kumoy(
                        local_layers, self.project.id
                    )

            qgisproject = write_qgsfile(self.project.id)

            # スタイルマップ作成
            new_styled_map = api.styledmap.add_styled_map(
                self.project.id,
                api.styledmap.AddStyledMapOptions(
                    name=name,
                    qgisproject=qgisproject,
                    attribution=attribution,
                    description=description,
                    isPublic=is_public,
                ),
            )

            # 保存完了後のUI更新
            QgsProject.instance().setCustomVariables(
                {"kumoy_map_id": new_styled_map.id}
            )
            QgsProject.instance().setTitle(new_styled_map.name)
            # reload browser panel
            self.parent().refresh()

            # Show success message with conversion errors summary if any
            if (
                local_layers
                and convert_confirm == Q_MESSAGEBOX_STD_BUTTON.Yes
                and conversion_errors
            ):
                error_details = "\n".join(
                    [
                        f"• {layer_name}\n{error}\n"
                        for layer_name, error in conversion_errors
                    ]
                )
                # Limit error details length
                msg_max_length = 1000
                if len(error_details) > msg_max_length:
                    error_details = error_details[:msg_max_length] + "..."

                QMessageBox.warning(
                    None,
                    self.tr("Map Created with Warnings"),
                    self.tr(
                        "Map '{}' has been created successfully.\n\n"
                        "Warning: {} layers could not be converted:\n\n{}"
                    ).format(name, len(conversion_errors), error_details),
                )
            else:
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("Map '{}' has been created successfully.").format(name),
                )
            QgsProject.instance().setDirty(False)
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error adding map: {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error adding map: {}").format(error_text),
            )

    def createChildren(self):
        project_id = get_settings().selected_project_id

        if not project_id:
            return [ErrorItem(self, self.tr("No project selected"))]

        # プロジェクトのスタイルマップを取得
        styled_maps = api.styledmap.get_styled_maps(project_id)

        if not styled_maps:
            return [ErrorItem(self, self.tr("No maps available."))]

        children = []
        for styled_map in styled_maps:
            path = f"{self.path()}/{styled_map.id}"
            child = StyledMapItem(self, path, styled_map, self.project.role)
            children.append(child)

        return children

    def clear_all_map_cache(self):
        # Show confirmation dialog
        confirm = QMessageBox.question(
            None,
            self.tr("Clear Map Cache"),
            self.tr(
                "This will clear all locally cached map files. "
                "Data will be re-downloaded next time you access maps.\n\n"
                "Continue?"
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )
        if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return

        cache_cleared = local_cache.map.clear_all()
        if cache_cleared:
            QgsMessageLog.logMessage(
                self.tr("All map cache files cleared successfully."),
                constants.LOG_CATEGORY,
                Qgis.Info,
            )
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("All map cache files have been cleared successfully."),
            )
        else:
            iface.messageBar().pushMessage(
                self.tr("Map Cache Clear Failed"),
                self.tr(
                    "Some map cache files could not be cleared. "
                    "Please try again after closing QGIS or ensure no files are locked."
                ),
            )
