"""Qt5/Qt6 compatibility layer"""

from qgis.PyQt.QtCore import QT_VERSION_STR, Qt
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
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

QT_ALIGN = Qt if QT_VERSION_INT <= 5 else Qt.AlignmentFlag
"""Qt alignment flags
Qt5: Qt.AlignRight, etc.
Qt6: Qt.AlignmentFlag.AlignRight, etc.
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
