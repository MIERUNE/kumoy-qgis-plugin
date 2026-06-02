"""共通のAPIエラーハンドラ。

UI 層・processing 層の `except Exception` ブロックから呼び出して、
- セッション切れ（UnauthorizedError）の場合はトークンを破棄して再ログインを促す
- それ以外は従来どおりエラーメッセージを表示する
を一箇所で行う。

QMessageBox 表示や Browser パネルの再構築など UI 操作を含むため `ui/` 配下に
置く。`processing/` からの import は sideways（横方向）になるが、
`error_handler` が UI 責務を負う以上やむを得ない位置取り。
"""

from typing import Optional

from qgis.core import Qgis, QgsApplication, QgsMessageLog
from qgis.PyQt.QtCore import QTimer
from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from .. import i18n
from ..kumoy import constants
from ..kumoy.api.error import UnauthorizedError, format_api_error
from ..kumoy.settings_manager import get_settings, store_setting


def _clear_session() -> None:
    """セッション関連設定のうち、トークン情報のみクリアする。

    selected_organization_id / selected_project_id は残し、
    再ログイン後にユーザーがプロジェクトを選び直さなくて済むようにする。
    """
    store_setting("session_token", "")
    store_setting("user_info", "")


def _refresh_kumoy_browser() -> None:
    """QGIS の dataItemProviderRegistry を辿って Kumoy provider を見つけ、
    RootCollection.refresh() を呼ぶ。

    registry は QGIS の公開 API、provider 名は `constants.PLUGIN_NAME` で
    一意。plugin.py への参照や callback 登録を介さずに直接 UI を更新できる。"""
    registry = QgsApplication.instance().dataItemProviderRegistry()
    for provider in registry.providers():
        if provider.name() != constants.PLUGIN_NAME:
            continue
        root = getattr(provider, "root_collection", None)
        if root is not None:
            root.refresh()
        return


def _show_session_expired_and_refresh() -> None:
    """セッション切れダイアログを表示し、Browser パネルをリフレッシュする。
    QTimer.singleShot 経由でメインイベントループの次の tick に呼ばれる前提。"""
    QMessageBox.warning(
        None,
        i18n.tr("Session expired"),
        i18n.tr(
            "Your Kumoy session has expired or is no longer valid.\n"
            "Please log in again from the Kumoy item in the Browser panel."
        ),
    )
    _refresh_kumoy_browser()


def handle_api_error(
    exception: Exception,
    parent: Optional[QWidget] = None,
    log_prefix: str = "",
) -> bool:
    """API例外を共通ハンドリングして表示する。

    UnauthorizedError の場合はトークンをクリアした上で、ダイアログ表示と
    Browser パネル再構築を **次のイベントループ tick に遅延させる**。
    これは QGIS の `createChildren` のような Python オブジェクトの寿命を
    巻き込むコンテキストから呼ばれたときに、Browser model から item を
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
        if not already_cleared:
            # 実際にトークンを破棄するのは「直前まで有効だった」最初の1回のみ。
            # それ以降の UnauthorizedError は、無効化済みのトークンに対する
            # 追加 API 呼び出しが空振りしているだけなので、ログ/ダイアログ/
            # Browser リフレッシュは抑制する。
            _clear_session()
            QgsMessageLog.logMessage(
                i18n.tr("Session expired. Cleared local session token."),
                constants.LOG_CATEGORY,
                Qgis.Warning,
            )
            QTimer.singleShot(0, _show_session_expired_and_refresh)
        return True

    detail = format_api_error(exception)
    title = log_prefix or i18n.tr("Error")
    log_message = f"{title}: {detail}" if log_prefix else detail
    QgsMessageLog.logMessage(log_message, constants.LOG_CATEGORY, Qgis.Warning)
    QMessageBox.critical(parent, title, detail)
    return False
