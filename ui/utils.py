from qgis.PyQt.QtWidgets import QMessageBox, QWidget

from ..pyqt_version import QT_TEXT_FORMAT_PLAIN, exec_dialog


def show_plain_text_message(parent: QWidget, title: str, message: str) -> None:
    """Show a plain-text message box to avoid rendering HTML in user data."""
    msg_box = QMessageBox(parent)
    msg_box.setWindowTitle(title)
    msg_box.setText(message)
    msg_box.setTextFormat(QT_TEXT_FORMAT_PLAIN)
    exec_dialog(msg_box)