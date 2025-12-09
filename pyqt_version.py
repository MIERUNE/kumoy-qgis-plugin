"""Qt5/Qt6 compatibility layer"""

from qgis.PyQt.QtCore import QT_VERSION_STR, Qt, QBuffer
from qgis.PyQt.QtGui import QRegion
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QMessageBox,
    QSizePolicy,
)

QT_VERSION_INT = int(QT_VERSION_STR.split(".")[0])
"""Qt major version as integer"""

QT_USER_ROLE = Qt.UserRole if QT_VERSION_INT <= 5 else Qt.ItemDataRole.UserRole
"""Qt user role constant
Qt5: Qt.UserRole
Qt6: Qt.ItemDataRole.UserRole
"""

QT_DIALOG_BUTTON_OK = (
    QDialogButtonBox.Ok if QT_VERSION_INT <= 5 else QDialogButtonBox.StandardButton.Ok
)
"""OK button constant
Qt5: QDialogButtonBox.Ok
Qt6: QDialogButtonBox.StandardButton.Ok
"""

QT_DIALOG_BUTTON_CANCEL = (
    QDialogButtonBox.Cancel
    if QT_VERSION_INT <= 5
    else QDialogButtonBox.StandardButton.Cancel
)
"""Cancel button constant
Qt5: QDialogButtonBox.Cancel
Qt6: QDialogButtonBox.StandardButton.Cancel
"""

Q_MESSAGEBOX_STD_BUTTON = (
    QMessageBox.StandardButton if QT_VERSION_INT > 5 else QMessageBox
)
"""Qt message box standard button class
Qt5: QMessageBox
Qt6: QMessageBox.StandardButton
"""

QT_ALIGN = Qt if QT_VERSION_INT <= 5 else Qt.AlignmentFlag
"""Qt alignment flags
Qt5: Qt.AlignRight, etc.
Qt6: Qt.AlignmentFlag.AlignRight, etc.
"""

QT_CUSTOM_CONTEXT_MENU = (
    Qt.CustomContextMenu
    if QT_VERSION_INT <= 5
    else Qt.ContextMenuPolicy.CustomContextMenu
)
"""Qt custom context menu policy
Qt5: Qt.CustomContextMenu
Qt6: Qt.ContextMenuPolicy.CustomContextMenu
"""

QT_PEN_STYLE = Qt if QT_VERSION_INT <= 5 else Qt.PenStyle
"""Qt pen style
Qt5: Qt.NoPen, Qt.SolidLine, etc.
Qt6: Qt.PenStyle.NoPen, Qt.PenStyle.SolidLine, etc.
"""

QT_PEN_CAP_STYLE = Qt if QT_VERSION_INT <= 5 else Qt.PenCapStyle
"""Qt pen cap style
Qt5: Qt.RoundCap, etc.
Qt6: Qt.PenCapStyle.RoundCap, etc.
"""

QT_PEN_JOIN_STYLE = Qt if QT_VERSION_INT <= 5 else Qt.PenJoinStyle
"""Qt pen join style
Qt5: Qt.RoundJoin, etc.
Qt6: Qt.PenJoinStyle.RoundJoin, etc.
"""

QT_TEXT_INTERACTION = Qt if QT_VERSION_INT <= 5 else Qt.TextInteractionFlag
"""Qt text interaction flags
Qt5: Qt.TextBrowserInteraction, Qt.TextSelectableByMouse, etc.
Qt6: Qt.TextInteractionFlag.TextBrowserInteraction, etc.
"""

QT_CURSOR_SHAPE = Qt if QT_VERSION_INT <= 5 else Qt.CursorShape
"""Qt cursor shapes
Qt5: Qt.PointingHandCursor, Qt.ArrowCursor, etc.
Qt6: Qt.CursorShape.PointingHandCursor, etc.
"""

QT_APPLICATION_MODAL = (
    Qt.ApplicationModal if QT_VERSION_INT <= 5 else Qt.WindowModality.ApplicationModal
)
"""Qt application modal flag
Qt5: Qt.ApplicationModal
Qt6: Qt.WindowModality.ApplicationModal
"""

QT_ASPECT_RATIO_MODE = Qt if QT_VERSION_INT <= 5 else Qt.AspectRatioMode
"""Qt aspect ratio mode
Qt5: Qt.KeepAspectRatio, Qt.KeepAspectRatioByExpanding, etc.
Qt6: Qt.AspectRatioMode.KeepAspectRatio, etc.
"""

QT_TRANSFORMATION_MODE = Qt if QT_VERSION_INT <= 5 else Qt.TransformationMode
"""Qt transformation mode
Qt5: Qt.SmoothTransformation, Qt.FastTransformation
Qt6: Qt.TransformationMode.SmoothTransformation, etc.
"""

Q_BUFFER_OPEN_MODE = QBuffer if QT_VERSION_INT <= 5 else QBuffer.OpenModeFlag
"""QBuffer open mode
Qt5: QBuffer.ReadOnly, QBuffer.WriteOnly, etc.
Qt6: QBuffer.OpenModeFlag.ReadOnly, etc.
"""

Q_NETWORK_REQUEST_HEADER = (
    QNetworkRequest if QT_VERSION_INT <= 5 else QNetworkRequest.KnownHeaders
)
"""Qt network request header type
Qt5: QNetworkRequest.ContentTypeHeader, etc.
Qt6: QNetworkRequest.KnownHeaders.ContentTypeHeader, etc.
"""

Q_REGION_TYPE = QRegion if QT_VERSION_INT <= 5 else QRegion.RegionType
"""Qt region type
Qt5: QRegion.Ellipse, etc.
Qt6: QRegion.RegionType.Ellipse, etc.
"""

Q_SIZE_POLICY = QSizePolicy if QT_VERSION_INT <= 5 else QSizePolicy.Policy
"""Qt size policy   
Qt5: QSizePolicy.Fixed, etc.
Qt6: QSizePolicy.Policy.Fixed, etc.
"""


def exec_dialog(dialog: QDialog):
    """Execute a modal dialog and return the result.

    Handles differences between Qt5 and Qt6.
    Qt5: dialog.exec_()
    Qt6: dialog.exec()
    """
    if QT_VERSION_INT <= 5:
        return dialog.exec_()
    else:
        return dialog.exec()


def exec_menu(menu, position):
    """Execute a QMenu at a given position.
    Qt5: menu.exec_(position)
    Qt6: menu.exec(position)
    """
    if QT_VERSION_INT <= 5:
        return menu.exec_(position)
    else:
        return menu.exec(position)


def exec_event_loop(loop):
    """Execute a QEventLoop.
    Qt5: loop.exec_()
    Qt6: loop.exec()
    """
    if QT_VERSION_INT <= 5:
        return loop.exec_()
    else:
        return loop.exec()
