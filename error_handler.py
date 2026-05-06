"""共通のAPIエラーハンドラ。

UI層の `except Exception` ブロックから呼び出して、
- セッション切れ（UnauthorizedError）の場合はトークンを破棄して再ログインを促す
- それ以外は従来どおりエラーメッセージを表示する
を一箇所で行う。
"""

from typing import Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from .kumoy import constants
from .kumoy.api.error import UnauthorizedError, format_api_error
from .kumoy.settings_manager import get_settings, store_setting


def _tr(message: str) -> str:
    return QCoreApplication.translate("KumoyErrorHandler", message)


def _clear_session() -> None:
    """セッション関連設定のうち、トークン情報のみクリアする。

    selected_organization_id / selected_project_id は残し、
    再ログイン後にユーザーがプロジェクトを選び直さなくて済むようにする。
    """
    store_setting("session_token", "")
    store_setting("user_info", "")


def handle_api_error(
    exception: Exception,
    parent: Optional[QWidget] = None,
    log_prefix: str = "",
) -> bool:
    """API例外を共通ハンドリングして表示する。

    UnauthorizedError の場合はトークンをクリアし、ユーザーへの通知ダイアログは
    「最初の1回だけ」表示する（QGIS Browser の createChildren など、同一の
    セッション切れ事象で連続的に呼ばれるパスでもダイアログが多重表示されない
    ようにするため）。トークンが再ログインで設定されると判定がリセットされる。

    Returns:
        UnauthorizedError として処理した場合は True、それ以外は False
    """
    if isinstance(exception, UnauthorizedError):
        already_cleared = not get_settings().session_token
        _clear_session()
        QgsMessageLog.logMessage(
            _tr("Session expired. Cleared local session token."),
            constants.LOG_CATEGORY,
            Qgis.Warning,
        )
        if not already_cleared:
            QMessageBox.warning(
                parent,
                _tr("Session expired"),
                _tr(
                    "Your Kumoy session has expired or is no longer valid.\n"
                    "Please log in again from the Kumoy item in the Browser panel."
                ),
            )
        return True

    detail = format_api_error(exception)
    title = log_prefix or _tr("Error")
    log_message = f"{title}: {detail}" if log_prefix else detail
    QgsMessageLog.logMessage(log_message, constants.LOG_CATEGORY, Qgis.Warning)
    QMessageBox.critical(parent, title, detail)
    return False
