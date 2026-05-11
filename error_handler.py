"""共通のAPIエラーハンドラ。

UI層の `except Exception` ブロックから呼び出して、
- セッション切れ（UnauthorizedError）の場合はトークンを破棄して再ログインを促す
- それ以外は従来どおりエラーメッセージを表示する
を一箇所で行う。
"""

from typing import Callable, List, Optional

from qgis.core import Qgis, QgsMessageLog
from qgis.PyQt.QtCore import QCoreApplication, QTimer
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from .kumoy import constants
from .kumoy.api.error import UnauthorizedError, format_api_error
from .kumoy.settings_manager import get_settings, store_setting


def _tr(message: str) -> str:
    return QCoreApplication.translate("@default", message)


# セッション切れを検知した際に呼ばれるコールバック群。
# 主に Browser パネルの再構築（古い Item を消す）に使う想定。
# error_handler はここに何も登録せず、上位の plugin.py 側が initGui で
# 登録、unload で解除する。
_session_cleared_callbacks: List[Callable[[], None]] = []


def register_session_cleared_callback(fn: Callable[[], None]) -> None:
    if fn not in _session_cleared_callbacks:
        _session_cleared_callbacks.append(fn)


def unregister_session_cleared_callback(fn: Callable[[], None]) -> None:
    if fn in _session_cleared_callbacks:
        _session_cleared_callbacks.remove(fn)


def _clear_session() -> None:
    """セッション関連設定のうち、トークン情報のみクリアする。

    selected_organization_id / selected_project_id は残し、
    再ログイン後にユーザーがプロジェクトを選び直さなくて済むようにする。
    """
    store_setting("session_token", "")
    store_setting("user_info", "")


def _notify_session_cleared() -> None:
    for cb in list(_session_cleared_callbacks):
        try:
            cb()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"session-cleared callback failed: {e}",
                constants.LOG_CATEGORY,
                Qgis.Warning,
            )


def _show_session_expired_and_notify() -> None:
    """セッション切れダイアログを表示し、登録済みコールバックを発火する。
    QTimer.singleShot 経由でメインイベントループの次の tick に呼ばれる前提。"""
    QMessageBox.warning(
        None,
        _tr("Session expired"),
        _tr(
            "Your Kumoy session has expired or is no longer valid.\n"
            "Please log in again from the Kumoy item in the Browser panel."
        ),
    )
    _notify_session_cleared()


def handle_api_error(
    exception: Exception,
    parent: Optional[QWidget] = None,
    log_prefix: str = "",
) -> bool:
    """API例外を共通ハンドリングして表示する。

    UnauthorizedError の場合はトークンをクリアした上で、ダイアログ表示と
    コールバック発火 (Browser パネル再構築) を **次のイベントループ tick に
    遅延させる**。これは QGIS の `createChildren` のような Python オブジェクトの
    寿命を巻き込むコンテキストから呼ばれたときに、Browser model から item を
    取り除く操作が同期実行されてクラッシュするのを防ぐため。

    また、複数の `createChildren` が並行発火して 401 が連発する状況でも
    モーダルが多重キューイングされないよう、トークンが「直前まで有効」だった
    最初の1回だけ通知する（dedup）。再ログインで token が再設定されると判定は
    リセットされる。

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
            QTimer.singleShot(0, _show_session_expired_and_notify)
        return True

    detail = format_api_error(exception)
    title = log_prefix or _tr("Error")
    log_message = f"{title}: {detail}" if log_prefix else detail
    QgsMessageLog.logMessage(log_message, constants.LOG_CATEGORY, Qgis.Warning)
    QMessageBox.critical(parent, title, detail)
    return False
