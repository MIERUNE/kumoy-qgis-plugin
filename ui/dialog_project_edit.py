from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
)

from ..kumoy.constants import (
    MAX_CHARACTERS_PROJECT_NAME,
    MAX_CHARACTERS_PROJECT_DESCRIPTION,
)
from ..pyqt_version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK


class ProjectEditDialog(QDialog):
    """Dialog for creating or editing a project with name and description"""

    def __init__(
        self,
        org_name: str,
        parent=None,
        initial_name: str = "",
        initial_description: str = "",
    ):
        super().__init__(parent)
        self.org_name = org_name
        self.project_name = ""
        self.project_description = ""
        self.initial_name = initial_name
        self.initial_description = initial_description
        self.setup_ui()

    def tr(self, message):
        return QCoreApplication.translate("ProjectEditDialog", message)

    def setup_ui(self):
        self.setWindowTitle(self.tr("New Project"))

        layout = QVBoxLayout()

        # Name field
        name_label = QLabel(self.tr("Name") + ' <span style="color: red;">*</span>')
        layout.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText(self.tr("Enter project name"))
        self.name_input.setMaxLength(MAX_CHARACTERS_PROJECT_NAME)
        self.name_input.setText(self.initial_name)
        layout.addWidget(self.name_input)

        # Description field
        description_label = QLabel(self.tr("Description"))
        layout.addWidget(description_label)

        self.description_input = QTextEdit()
        self.description_input.setPlaceholderText(self.tr("Enter project description"))
        self.description_input.setMaximumHeight(100)
        self.description_input.textChanged.connect(self._limit_description)
        self.description_input.setPlainText(self.initial_description or "")
        layout.addWidget(self.description_input)

        # Buttons
        button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

        self.setLayout(layout)

    def _limit_description(self):
        """Limit description to maximum characters"""
        if (
            len(self.description_input.toPlainText())
            > MAX_CHARACTERS_PROJECT_DESCRIPTION
        ):
            cursor = self.description_input.textCursor()
            self.description_input.setPlainText(
                self.description_input.toPlainText()[
                    :MAX_CHARACTERS_PROJECT_DESCRIPTION
                ]
            )
            cursor.setPosition(MAX_CHARACTERS_PROJECT_DESCRIPTION)
            self.description_input.setTextCursor(cursor)

    def accept(self):
        """Validate and accept the dialog"""
        self.project_name = self.name_input.text().strip()
        self.project_description = self.description_input.toPlainText().strip()

        if not self.project_name:
            QMessageBox.warning(
                self,
                self.tr("Invalid Input"),
                self.tr("Project name cannot be empty."),
            )
            return

        super().accept()
