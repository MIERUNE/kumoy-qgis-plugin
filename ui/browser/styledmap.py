import webbrowser
from typing import Literal

from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsMessageLog,
    QgsProject,
)
from qgis.PyQt.QtWidgets import (
    QAction,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
)
from qgis.utils import iface

from ... import i18n
from ...kumoy import api, constants, local_cache, settings_manager
from ...kumoy.api.error import UnauthorizedError, format_api_error
from ...kumoy.local_cache.map import (
    commit_to_cache,
    serialize_project,
)
from ...kumoy.settings_manager import get_settings
from ...kumoy.sprite import generate_sprite
from ...kumoy.sprite.uploader import upload_sprites
from ...pyqt_version import (
    Q_MESSAGEBOX_STD_BUTTON,
    Q_SIZE_POLICY,
    QT_DIALOG_BUTTON_CANCEL,
    QT_DIALOG_BUTTON_OK,
    QT_TEXTCURSOR_MOVE_OPERATION,
    exec_dialog,
)
from ...qgis_version import (
    restore_project_crs_if_invalid,
    restore_xyz_layer_datasources,
)
from ...ui.layers.convert import convert_local_layers
from ..error_handler import handle_api_error, refresh_kumoy_browser
from ..icons import BROWSER_MAP_ICON
from ..project_save_handler import show_map_save_result, warn_if_project_too_large
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

    def build_actions(self, parent: QMenu) -> list[QAction]:
        """Build context menu actions for this item (used by KumoyDataItemGuiProvider)."""
        actions = []

        # スタイルマップ適用アクション
        apply_action = QAction(i18n.tr("Load into QGIS"), parent)
        apply_action.triggered.connect(self.apply_style)
        actions.append(apply_action)

        if self.styled_map.isPublic:
            # 公開マップの場合、公開ページを開くアクション
            open_public_action = QAction(i18n.tr("Open Public Page"), parent)
            open_public_action.triggered.connect(self.open_public_page)
            actions.append(open_public_action)

        # Clear map cache action
        clear_cache_action = QAction(i18n.tr("Clear Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_map_cache)
        actions.append(clear_cache_action)

        if self.role in ["ADMIN", "OWNER"]:
            # スタイルマップ上書き保存アクション
            save_action = QAction(i18n.tr("Overwrite with current state"), parent)
            save_action.triggered.connect(self.apply_qgisproject_to_styledmap)
            actions.append(save_action)

            # スタイルマップ編集アクション
            edit_action = QAction(i18n.tr("Edit Metadata"), parent)
            edit_action.triggered.connect(self.update_metadata_styled_map)
            actions.append(edit_action)

            # スタイルマップ削除アクション
            delete_action = QAction(i18n.tr("Delete"), parent)
            delete_action.triggered.connect(self.delete_styled_map)
            actions.append(delete_action)

        return actions

    def open_public_page(self) -> None:
        """公開ページをブラウザで開く"""
        url = (
            f"{api.config.get_api_config().SERVER_URL}/public/map/{self.styled_map.id}"
        )
        webbrowser.open(url)

    def apply_style(self) -> None:
        """KumoyサーバーからMapを取得してQGISに適用する"""

        # QGISプロジェクトに変更がある場合、適用前に確認ダイアログを表示
        if QgsProject.instance().isDirty():
            confirm = QMessageBox.question(
                None,
                i18n.tr("Load Map"),
                i18n.tr(
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
            handle_api_error(e, parent=None, log_prefix=i18n.tr("Error loading map"))
            return

        # XML文字列をQGISプロジェクトにロード
        qgs_path = local_cache.map.get_filepath(styled_map_detail.id)

        with open(qgs_path, "w", encoding="utf-8") as f:
            f.write(styled_map_detail.qgisproject)
        iface.addProject(qgs_path)

        # Restore CRS if it became invalid after loading
        # (e.g. QGIS 4 project opened in QGIS 3)
        restore_project_crs_if_invalid(styled_map_detail.qgisproject)
        # Fix XYZ tile datasources whose URL was percent-encoded by QGIS 4
        restore_xyz_layer_datasources()

        QgsProject.instance().setTitle(self.styled_map.name)
        # store map kumoy info to project instance
        QgsProject.instance().setCustomVariables(
            {
                "kumoy_map_id": self.styled_map.id,
            }
        )
        QgsProject.instance().setDirty(False)

    def handleDoubleClick(self) -> bool:
        self.apply_style()
        return True

    def update_metadata_styled_map(self) -> None:
        # Create dialog
        dialog, name_field, description_field, attribution_field, is_public_field = (
            _create_styled_map_dialog(
                i18n.tr("Edit Map"),
                name=self.styled_map.name,
                description=self.styled_map.description,
                attribution=self.styled_map.attribution,
                is_public=self.styled_map.isPublic,
            )
        )

        # Show dialog
        if not exec_dialog(dialog):
            return

        # Get values
        new_name = name_field.text()
        new_description = description_field.toPlainText()
        new_attribution = attribution_field.text()
        new_is_public = is_public_field.isChecked()

        if not new_name:
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
            handle_api_error(e, parent=None, log_prefix=i18n.tr("Error updating map"))
            return

        # Itemを更新
        self.styled_map = updated_styled_map
        self.setName(updated_styled_map.name)
        self.refresh()

        QgsProject.instance().setTitle(updated_styled_map.name)
        QgsProject.instance().setDirty(False)

        iface.messageBar().pushSuccess(
            i18n.tr("Success"),
            i18n.tr("Map '{}' has been updated successfully.").format(new_name),
        )

    def apply_qgisproject_to_styledmap(self) -> None:
        # 確認ダイアログ
        confirm = QMessageBox.question(
            None,
            i18n.tr("Save Map"),
            i18n.tr(
                "Are you sure you want to overwrite the map '{}' with the current project state?"
            ).format(self.styled_map.name),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )
        if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
            return

        # Avoid saving a Kumoy map to a wrong project
        custom_vars = QgsProject.instance().customVariables()
        existing_map_id = custom_vars.get("kumoy_map_id")

        if existing_map_id:
            # Validate that existing map belongs to current project
            styled_map_detail = api.styledmap.get_styled_map(existing_map_id)

            if self.styled_map.projectId != styled_map_detail.projectId:
                QMessageBox.critical(
                    None,
                    i18n.tr("Wrong Project"),
                    i18n.tr(
                        "Please switch to the correct Kumoy project to create a map."
                    ),
                )
                return

        # HACK: to ensure extents of all layers are calculated - Issue #311
        for layer in QgsProject.instance().mapLayers().values():
            layer.extent()

        # Pre-flight size check before any upload: serialize to a throwaway temp
        # file and validate, without touching the cache. The .qgs size barely
        # changes after conversion (only datasource strings are swapped), so
        # failing here avoids converting/uploading layers for a project that
        # would be rejected anyway.
        if warn_if_project_too_large(serialize_project()):
            return

        # Convert local layers to Kumoy layers if any
        conversion = convert_local_layers(self.styled_map.projectId)
        if conversion.cancelled:
            return

        new_qgisproject = serialize_project()
        if warn_if_project_too_large(new_qgisproject):
            return

        try:
            # Generate sprites and upload if changed
            sprite_data = generate_sprite(QgsProject.instance())
            new_assets_hash = sprite_data.assets_hash if sprite_data else None

            update_options = api.styledmap.UpdateStyledMapOptions(
                qgisproject=new_qgisproject,
            )
            if new_assets_hash != self.styled_map.assetsHash:
                if sprite_data is not None:
                    upload_sprites(self.styled_map.id, sprite_data)
                update_options.assetsHash = new_assets_hash

            updated_styled_map = api.styledmap.update_styled_map(
                self.styled_map.id,
                update_options,
            )

            # Persist to cache only after a successful server save.
            commit_to_cache(self.styled_map.id, new_qgisproject)
        except Exception as e:
            handle_api_error(e, parent=None, log_prefix=i18n.tr("Error saving map"))
            return

        # Itemを更新
        self.styled_map = updated_styled_map
        self.setName(updated_styled_map.name)
        self.refresh()

        QgsProject.instance().setTitle(updated_styled_map.name)
        QgsProject.instance().setDirty(False)

        # Show result message with conversion errors summary if any
        show_map_save_result(
            updated_styled_map.name,
            conversion.errors,
            conversion.skipped,
        )

        # 変換で新しいKumoyレイヤーができた場合はツリー全体を更新する。
        # 再構築で self ごとアイテムが破棄されるため、self を参照し終えた
        # フローの最後に置くこと。
        if conversion.converted:
            refresh_kumoy_browser()

    def process_delete_map(self) -> None:
        api.styledmap.delete_styled_map(self.styled_map.id)

        # Close the map if it's currently loaded in QGIS
        custom_vars = QgsProject.instance().customVariables()
        if custom_vars.get("kumoy_map_id") == self.styled_map.id:
            QgsProject.instance().clear()

        local_cache.map.clear(self.styled_map.id)

    def delete_styled_map(self) -> None:
        confirm = QMessageBox.question(
            None,
            i18n.tr("Delete Map"),
            i18n.tr("Are you sure you want to delete map '{}'?").format(
                self.styled_map.name
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            try:
                self.process_delete_map()
                self.parent().refresh()
                iface.messageBar().pushSuccess(
                    i18n.tr("Success"),
                    i18n.tr("Map '{}' has been deleted successfully.").format(
                        self.styled_map.name
                    ),
                )
            except Exception as e:
                handle_api_error(
                    e, parent=None, log_prefix=i18n.tr("Error deleting map")
                )

    def process_map_cache_clear(self) -> bool:
        cleared = local_cache.map.clear(self.styled_map.id)
        return cleared

    def clear_map_cache(self) -> None:
        confirm = QMessageBox.question(
            None,
            i18n.tr("Clear Map Cache Data"),
            i18n.tr(
                "This will clear the local cache for map '{}'.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(self.styled_map.name),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            if self.process_map_cache_clear():
                iface.messageBar().pushSuccess(
                    i18n.tr("Success"),
                    i18n.tr("Cache cleared successfully for map '{}'.").format(
                        self.styled_map.name
                    ),
                )
            else:
                iface.messageBar().pushMessage(
                    i18n.tr("Cache Clear Failed"),
                    i18n.tr("Cache could not be cleared for map '{}'. ").format(
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

    def actions(self, parent: QMenu) -> list[QAction]:
        actions = []

        if self.project.role in ["ADMIN", "OWNER"]:
            # 空のMapを作成する
            empty_map_action = QAction(i18n.tr("Create New Map"), parent)
            empty_map_action.triggered.connect(self.add_empty_map)
            actions.append(empty_map_action)

            # Upload current QGIS project as new Kumoy styled map
            new_action = QAction(i18n.tr("Save Current Project As..."), parent)
            new_action.triggered.connect(self.add_styled_map)
            actions.append(new_action)

        # Clear map cache data
        clear_all_cache_action = QAction(i18n.tr("Clear Map Cache Data"), parent)
        clear_all_cache_action.triggered.connect(self.clear_all_map_cache)
        actions.append(clear_all_cache_action)

        return actions

    def add_empty_map(self) -> None:
        if QgsProject.instance().isDirty():
            confirm = QMessageBox.question(
                None,
                i18n.tr("Create new Map"),
                i18n.tr(
                    "Creating an new map will clear your current project. Continue?"
                ),
                Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
                Q_MESSAGEBOX_STD_BUTTON.No,
            )
            if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
                return

        self.add_styled_map(clear=True)

    def add_styled_map(self, clear: bool = False) -> None:
        """Add a new map to kumoy server
        Options:
        clear - whether to clear current QGIS project"""

        # HACK: to ensure extents of all layers are calculated - Issue #311
        for layer in QgsProject.instance().mapLayers().values():
            layer.extent()

        try:
            # Check plan limits before creating styled map
            plan_limit = api.plan.get_plan_limits(
                self.organization.subscriptionPlan,
                self.organization.storageUnits,
            )
            current_styled_maps = api.styledmap.get_styled_maps(self.project.id)
            current_styled_map_count = len(current_styled_maps) + 1
            if current_styled_map_count > plan_limit.maxStyledMaps:
                QMessageBox.critical(
                    None,
                    i18n.tr("Error"),
                    i18n.tr(
                        "Cannot create new map. Your plan allows up to {} maps, "
                        "but you have reached the limit."
                    ).format(plan_limit.maxStyledMaps),
                )
                return

            # Avoid saving a Kumoy map to a wrong project
            custom_vars = QgsProject.instance().customVariables()
            existing_map_id = custom_vars.get("kumoy_map_id")

            if existing_map_id:
                # Validate that existing map belongs to current project
                styled_map_detail = api.styledmap.get_styled_map(existing_map_id)
                settings = settings_manager.get_settings()

                if settings.selected_project_id != styled_map_detail.projectId:
                    QMessageBox.critical(
                        None,
                        i18n.tr("Wrong Project"),
                        i18n.tr(
                            "Please switch to the correct Kumoy project to create a map."
                        ),
                    )
                    return
        except Exception as e:
            handle_api_error(e, parent=None, log_prefix=i18n.tr("Error adding map"))
            return

        # Create dialog
        (
            dialog,
            name_field,
            description_field,
            attribution_field,
            is_public_field,
        ) = _create_styled_map_dialog(
            i18n.tr("Add Map"),
        )

        # Show dialog
        if not exec_dialog(dialog):
            return

        # Get values
        name = name_field.text()
        description = description_field.toPlainText()
        attribution = attribution_field.text()
        is_public = is_public_field.isChecked()

        if not name:
            return

        if clear:
            # Create an empty QGIS project
            QgsProject.instance().clear()

        # Pre-flight size check before any upload: serialize to a throwaway temp
        # file and validate, without touching the cache.
        if warn_if_project_too_large(serialize_project()):
            return

        # Convert local layers to Kumoy layers
        # (conversion.converted は不要: このフローは最後に self.parent().refresh() で
        # ルートごとツリーを再構築するため、新規レイヤーもそこで現れる)
        conversion = convert_local_layers(self.project.id)
        if conversion.cancelled:
            return

        qgisproject = serialize_project()
        if warn_if_project_too_large(qgisproject):
            return

        try:
            # Create the styled map
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

            # Update UI after the save completes
            QgsProject.instance().setCustomVariables(
                {"kumoy_map_id": new_styled_map.id}
            )
            QgsProject.instance().setTitle(new_styled_map.name)

            # Re-serialize so the file embeds kumoy_map_id linking the new map
            updated_qgisproject = serialize_project()
            if warn_if_project_too_large(updated_qgisproject):
                return

            # Generate and upload sprites
            sprite_data = generate_sprite(QgsProject.instance())
            new_assets_hash = None
            if sprite_data is not None:
                new_assets_hash = sprite_data.assets_hash
                upload_sprites(new_styled_map.id, sprite_data)

            api.styledmap.update_styled_map(
                new_styled_map.id,
                api.styledmap.UpdateStyledMapOptions(
                    qgisproject=updated_qgisproject,
                    assetsHash=new_assets_hash,  # memo: set null when new_assets_hash is None
                ),
            )

            # Persist to cache only after a successful server save.
            commit_to_cache(new_styled_map.id, updated_qgisproject)

            # Point the project at the cache file so handle_project_saved()
            # keeps the map linked on subsequent saves (in-cache check).
            QgsProject.instance().setFileName(
                local_cache.map.get_filepath(new_styled_map.id)
            )

            # reload browser panel
            self.parent().refresh()

            # Show result message with conversion errors summary if any
            show_map_save_result(
                name,
                conversion.errors,
                conversion.skipped,
            )
            QgsProject.instance().setDirty(False)
        except Exception as e:
            handle_api_error(e, parent=None, log_prefix=i18n.tr("Error adding map"))

    def createChildren(self) -> list[QgsDataItem]:
        project_id = get_settings().selected_project_id

        if not project_id:
            return [ErrorItem(self, i18n.tr("No project selected"))]

        # プロジェクトのスタイルマップを取得
        try:
            styled_maps = api.styledmap.get_styled_maps(project_id)
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return [ErrorItem(self, i18n.tr("Session expired - please log in"))]
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading maps: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, i18n.tr("Error loading maps"))]

        if not styled_maps:
            return [ErrorItem(self, i18n.tr("No maps available."))]

        children = []
        for styled_map in styled_maps:
            path = f"{self.path()}/{styled_map.id}"
            child = StyledMapItem(self, path, styled_map, self.project.role)
            children.append(child)

        return children

    def clear_all_map_cache(self) -> None:
        # Show confirmation dialog
        confirm = QMessageBox.question(
            None,
            i18n.tr("Clear Map Cache"),
            i18n.tr(
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
                i18n.tr("All map cache files cleared successfully."),
                constants.LOG_CATEGORY,
                Qgis.Info,
            )
            iface.messageBar().pushSuccess(
                i18n.tr("Success"),
                i18n.tr("All map cache files have been cleared successfully."),
            )
        else:
            iface.messageBar().pushMessage(
                i18n.tr("Map Cache Clear Failed"),
                i18n.tr(
                    "Some map cache files could not be cleared. "
                    "Please try again after closing QGIS or ensure no files are locked."
                ),
            )


def _create_styled_map_dialog(
    title: str,
    name: str = "",
    description: str = "",
    attribution: str = "",
    is_public: bool = False,
) -> tuple[QDialog, QLineEdit, QPlainTextEdit, QLineEdit, QCheckBox]:
    """Create a styled map dialog with common fields.

    Args:
        title: Dialog window title
        name: Initial name value
        description: Initial description value
        attribution: Initial attribution value
        is_public: Initial public checkbox state

    Returns:
        Tuple of (dialog, name_field, description_field, attribution_field, is_public_field)
    """
    dialog = QDialog()
    dialog.setWindowTitle(title)

    # Layout
    layout = QVBoxLayout()
    form_layout = QFormLayout()

    # Fields
    name_field = QLineEdit(name)
    name_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_NAME)

    attribution_field = QLineEdit(attribution)
    attribution_field.setMaxLength(constants.MAX_CHARACTERS_STYLEDMAP_ATTRIBUTION)

    description_field = QPlainTextEdit(description)
    description_field.setSizePolicy(Q_SIZE_POLICY.Expanding, Q_SIZE_POLICY.Expanding)

    # Limit text length (integrated as part of UI construction)
    def limit_description_length():
        text = description_field.toPlainText()
        if len(text) > constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION:
            description_field.setPlainText(
                text[: constants.MAX_CHARACTERS_STYLEDMAP_DESCRIPTION]
            )
            cursor = description_field.textCursor()
            cursor.movePosition(QT_TEXTCURSOR_MOVE_OPERATION.End)
            description_field.setTextCursor(cursor)

    description_field.textChanged.connect(limit_description_length)

    is_public_field = QCheckBox(i18n.tr("Make Public"))
    is_public_field.setChecked(is_public)

    # Add fields to form
    form_layout.addRow(
        i18n.tr("Name:") + ' <span style="color: red;">*</span>', name_field
    )
    form_layout.addRow(i18n.tr("Description:"), description_field)
    form_layout.addRow(i18n.tr("Attribution:"), attribution_field)
    form_layout.addRow(i18n.tr("Public:"), is_public_field)

    # Buttons
    button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
    button_box.accepted.connect(dialog.accept)
    button_box.rejected.connect(dialog.reject)

    # Disable OK if name is empty
    ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
    ok_button.setEnabled(bool(name_field.text().strip()))
    name_field.textChanged.connect(
        lambda text: ok_button.setEnabled(bool(text.strip()))
    )

    # Add layouts to dialog
    layout.addLayout(form_layout)
    layout.addWidget(button_box)
    dialog.setLayout(layout)

    return dialog, name_field, description_field, attribution_field, is_public_field


def delete_multiple_maps(items: list[StyledMapItem]) -> None:
    names = "\n".join(f"  - {i.styled_map.name}" for i in items)
    confirm = QMessageBox.question(
        None,
        i18n.tr("Delete Maps"),
        i18n.tr("Are you sure you want to delete {} maps?\n{}").format(
            len(items), names
        ),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    errors = []
    deleted_count = 0
    parent_item = items[0].parent() if items else None

    aborted_unauthorized = False
    for item in items:
        try:
            item.process_delete_map()
            deleted_count += 1
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            aborted_unauthorized = True
            break
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error deleting map '{item.styled_map.name}': {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            errors.append(f"{item.styled_map.name}: {error_text}")

    if parent_item:
        parent_item.refresh()

    if aborted_unauthorized:
        return

    if errors:
        QMessageBox.critical(
            None,
            i18n.tr("Error"),
            i18n.tr("Some maps could not be deleted:\n{}").format("\n".join(errors)),
        )
    else:
        iface.messageBar().pushSuccess(
            i18n.tr("Success"),
            i18n.tr("{} maps have been deleted successfully.").format(deleted_count),
        )


def clear_cache_multiple_maps(items: list[StyledMapItem]) -> None:
    confirm = QMessageBox.question(
        None,
        i18n.tr("Clear Map Cache Data"),
        i18n.tr(
            "This will clear the local cache for {} maps.\n"
            "The cached data will be re-downloaded when you access it next time.\n"
            "Do you want to continue?"
        ).format(len(items)),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    failed = [i.styled_map.name for i in items if not i.process_map_cache_clear()]

    if failed:
        iface.messageBar().pushMessage(
            i18n.tr("Cache Clear Failed"),
            i18n.tr("Could not clear cache for: {}").format(", ".join(failed)),
        )
    else:
        iface.messageBar().pushSuccess(
            i18n.tr("Success"),
            i18n.tr("Cache cleared successfully for {} maps.").format(len(items)),
        )
