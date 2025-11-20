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


class CheckmarkWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)

    def paintEvent(self, event):
        del event  # Unused parameter
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Draw green circle
        painter.setBrush(QBrush(QColor(76, 175, 80)))
        painter.setPen(QPen(Qt.NoPen))
        painter.drawEllipse(0, 0, 80, 80)

        # Draw white checkmark
        painter.setPen(
            QPen(QColor(255, 255, 255), 5, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        )
        painter.drawLine(20, 40, 35, 55)
        painter.drawLine(35, 55, 60, 25)


class LoginSuccess(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(self.tr("Authentication"))
        self.setFixedSize(500, 350)
        self.setModal(True)

        # Main layout
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(40, 40, 40, 40)
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
        title_label.setAlignment(Qt.AlignCenter)
        title_font = QFont()
        title_font.setPointSize(24)
        title_font.setBold(True)
        title_label.setFont(title_font)
        main_layout.addWidget(title_label)

        # Subtitle label
        subtitle_label = QLabel(
            self.tr("Next, please select a project\nto open in Strato.")
        )
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_font = QFont()
        subtitle_font.setPointSize(14)
        subtitle_label.setFont(subtitle_font)
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
