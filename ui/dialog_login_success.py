from qgis.PyQt.QtCore import QCoreApplication, Qt
from qgis.PyQt.QtGui import QBrush, QColor, QFont, QPainter, QPen
from qgis.PyQt.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..pyqt_version import QT_ALIGN, QT_PEN_CAP_STYLE, QT_PEN_JOIN_STYLE, QT_PEN_STYLE


class CheckmarkWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(50, 50)

    def paintEvent(self, event):
        del event  # Unused parameter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw green circle
        painter.setBrush(QBrush(QColor(76, 175, 80)))
        painter.setPen(QPen(QT_PEN_STYLE.NoPen))
        painter.drawEllipse(0, 0, 50, 50)

        # Draw white checkmark
        painter.setPen(
            QPen(
                QColor(255, 255, 255),
                3,
                QT_PEN_STYLE.SolidLine,
                QT_PEN_CAP_STYLE.RoundCap,
                QT_PEN_JOIN_STYLE.RoundJoin,
            )
        )
        painter.drawLine(15, 26, 22, 33)
        painter.drawLine(22, 33, 35, 20)


class LoginSuccess(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Authentication"))
        self.setFixedSize(500, 350)
        self.setModal(True)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 32, 40, 32)
        main_layout.setSpacing(20)

        # Checkmark widget centered
        checkmark_container = QHBoxLayout()
        checkmark_container.addStretch()
        self.checkmark = CheckmarkWidget()
        checkmark_container.addWidget(self.checkmark)
        checkmark_container.addStretch()
        main_layout.addLayout(checkmark_container)

        # Title label
        title_label = QLabel(self.tr("Welcome!\nYou are now logged in."))
        title_label.setAlignment(QT_ALIGN.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setStyleSheet("padding: 0px 0px 5px 0px;")
        main_layout.addWidget(title_label)

        # Subtitle label
        subtitle_label = QLabel(
            self.tr("Next, please select a project\nto open in Kumoy.")
        )
        subtitle_label.setAlignment(QT_ALIGN.AlignCenter)
        subtitle_font = QFont()
        subtitle_font.setPointSize(14)
        subtitle_label.setFont(subtitle_font)
        subtitle_label.setStyleSheet("padding: 0px 0px 5px 0px;")
        main_layout.addWidget(subtitle_label)

        # Add spacing before button
        main_layout.addStretch()

        # Continue button
        self.continue_button = QPushButton(self.tr("Continue"))
        self.continue_button.clicked.connect(self.accept)
        main_layout.addWidget(self.continue_button)

        self.setLayout(main_layout)

    def tr(self, text):
        return QCoreApplication.translate("LoginSuccess", text)
