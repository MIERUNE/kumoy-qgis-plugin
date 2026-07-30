"""QGISの「プロジェクト保存」イベントに連動して Kumoy 側を更新する UI 連携ロジック。

ローカルキャッシュ層 (`kumoy/local_cache/map.py`) は純粋なファイル操作だけを担い、
ユーザー対話・APIアップロードを伴うこのフローは UI 層に置く。
"""

import os
from typing import Optional

from qgis.core import QgsProject
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.utils import iface

from .. import i18n
from ..kumoy import api, settings_manager
from ..kumoy.local_cache import map as cache_map
from ..kumoy.sprite import generate_sprite
from ..kumoy.sprite.uploader import upload_sprites
from ..pyqt_version import Q_MESSAGEBOX_STD_BUTTON
from .error_handler import handle_api_error, refresh_kumoy_browser
from .layers.convert_local import convert_local_layers


def show_map_save_result(
    map_name: str,
    conversion_errors: list[tuple[str, str]],
    skipped_layers: Optional[list[str]] = None,
) -> None:
    """Show success or warning message after map save operation.

    ``skipped_layers`` はアップロードを中断して未変換のまま保存されたレイヤー。
    """
    warnings = []

    if skipped_layers:
        warnings.append(
            i18n.tr(
                "Upload was cancelled: {} layers were not converted and remain local."
            ).format(len(skipped_layers))
        )

    if conversion_errors:
        error_details = "\n".join(
            [f"• {layer_name}\n{error}\n" for layer_name, error in conversion_errors]
        )
        msg_max_length = 1000
        if len(error_details) > msg_max_length:
            error_details = error_details[:msg_max_length] + "..."

        warnings.append(
            i18n.tr("Warning: {} layers could not be converted:\n\n{}").format(
                len(conversion_errors), error_details
            )
        )

    if warnings:
        report_msg = i18n.tr("Map '{}' has been saved successfully.").format(
            map_name
        ) + "\n\n{}".format("\n\n".join(warnings))

        QMessageBox.warning(None, i18n.tr("Map Saved with Warnings"), report_msg)
    else:
        report_msg = i18n.tr("Map '{}' has been saved successfully.").format(map_name)
        iface.messageBar().pushSuccess(i18n.tr("Success"), report_msg)


def warn_if_project_too_large(qgs_str: str) -> bool:
    """Show an error dialog and return True if the project exceeds the size limit."""
    size_error = cache_map.size_limit_error(qgs_str)
    if size_error:
        QMessageBox.critical(None, i18n.tr("Error"), size_error)
        return True
    return False


def handle_project_saved() -> None:
    """Update current project to Kumoy when QGIS project is saved"""
    # Prevent re-entrancy while we are saving the project ourselves via
    # serialize_project().
    if cache_map.is_updating:
        return

    project = QgsProject.instance()

    custom_vars = project.customVariables()
    styled_map_id = custom_vars.get("kumoy_map_id")
    if not styled_map_id:
        return

    # Check if project file is saved in local cache
    file_path = os.path.abspath(project.absoluteFilePath())
    local_cache_dir = os.path.abspath(cache_map.get_cache_dir())

    try:
        in_cache = os.path.commonpath([file_path, local_cache_dir]) == local_cache_dir
    except ValueError:
        in_cache = False

    if not in_cache:
        # 他プラグイン/ユーザー定義の customVariables を消さないように
        # kumoy_map_id だけを除いて書き戻す。
        # setCustomVariables() による副次的な dirty 化のみを打ち消すため、
        # 事前の dirty 状態を保持して復元する（他フックが意図的に立てた dirty は維持）。
        was_dirty = project.isDirty()
        new_vars = {k: v for k, v in custom_vars.items() if k != "kumoy_map_id"}
        project.setCustomVariables(new_vars)
        if not was_dirty:
            project.setDirty(False)
        return

    # Get and validate map belongs to current project
    try:
        styled_map_detail = api.styledmap.get_styled_map(styled_map_id)
        settings = settings_manager.get_settings()

        if settings.selected_project_id != styled_map_detail.projectId:
            QMessageBox.critical(
                None,
                i18n.tr("Wrong Project"),
                i18n.tr(
                    "This map belongs to a different Kumoy project. "
                    "Please switch to the correct project."
                ),
            )
            return
    except Exception as e:
        handle_api_error(e, parent=None, log_prefix=i18n.tr("Error loading map"))
        return

    if styled_map_detail.role not in ["ADMIN", "OWNER"]:
        iface.messageBar().pushMessage(
            i18n.tr("Failed"),
            i18n.tr("You do not have permission to save this map to Kumoy."),
        )
        return

    confirm = QMessageBox.question(
        None,
        i18n.tr("Save Map"),
        i18n.tr(
            "Are you sure you want to overwrite the map '{}' with the current project state?"
        ).format(styled_map_detail.name),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    # Pre-flight size check before any upload: serialize to a throwaway temp
    # file and validate, without touching the cache.
    if warn_if_project_too_large(cache_map.serialize_project()):
        return

    conversion = convert_local_layers(styled_map_detail.projectId)
    if conversion.cancelled:
        return

    qgsproject_str = cache_map.serialize_project()
    if warn_if_project_too_large(qgsproject_str):
        return

    try:
        sprite_data = generate_sprite(project)
        new_assets_hash = sprite_data.assets_hash if sprite_data else None

        update_options = api.styledmap.UpdateStyledMapOptions(
            qgisproject=qgsproject_str,
        )
        if new_assets_hash != styled_map_detail.assetsHash:
            if sprite_data is not None:
                upload_sprites(styled_map_id, sprite_data)
            # memo: set null when new_assets_hash is None
            update_options.assetsHash = new_assets_hash
        updated_styled_map = api.styledmap.update_styled_map(
            styled_map_id,
            update_options,
        )

        # Persist to cache only after a successful server save.
        cache_map.commit_to_cache(styled_map_id, qgsproject_str)
    except Exception as e:
        handle_api_error(e, parent=None, log_prefix=i18n.tr("Error saving map"))
        return

    QgsProject.instance().setTitle(updated_styled_map.name)
    QgsProject.instance().setDirty(False)

    show_map_save_result(updated_styled_map.name, conversion.errors, conversion.skipped)

    # 変換で新しいKumoyレイヤーができた場合のみブラウザを更新する。
    # ツリー再構築でアイテムが破棄されるので、フローの最後に置くこと。
    if conversion.converted:
        refresh_kumoy_browser()
