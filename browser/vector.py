import os

from PyQt5.QtCore import QCoreApplication
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)
from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsEditorWidgetSetup,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
)

from ..imgs import IMGS_PATH
from ..qgishub import api
from ..qgishub.api.project_vector import (
    AddVectorOptions,
    QgishubVector,
    UpdateVectorOptions,
)
from ..qgishub.constants import LOG_CATEGORY, PLUGIN_NAME
from ..settings_manager import SettingsManager
from .utils import ErrorItem


class VectorItem(QgsDataItem):
    """Vector layer item for browser"""

    def __init__(self, parent, path: str, vector: QgishubVector):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=vector.name,
            path=path,
        )

        self.vector = vector

        # Set icon based on geometry type
        icon_filename = "icon_vector.svg"  # Default icon

        if vector.type == "POINT":
            icon_filename = "icon_point.svg"
        elif vector.type == "LINESTRING":
            icon_filename = "icon_linestring.svg"
        elif vector.type == "POLYGON":
            icon_filename = "icon_polygon.svg"

        self.setIcon(QIcon(os.path.join(IMGS_PATH, icon_filename)))

        self.populate()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("VectorItem", message)

    def actions(self, parent):
        actions = []

        # Add to map action
        add_action = QAction(self.tr("Add to Map"), parent)
        add_action.triggered.connect(self.add_to_map)
        actions.append(add_action)

        # Edit vector action
        edit_action = QAction(self.tr("Edit Vector"), parent)
        edit_action.triggered.connect(self.edit_vector)
        actions.append(edit_action)

        # Delete vector action
        delete_action = QAction(self.tr("Delete Vector"), parent)
        delete_action.triggered.connect(self.delete_vector)
        actions.append(delete_action)

        # Refresh action
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def add_to_map(self):
        """Add vector layer to QGIS map"""
        config = api.config.get_api_config()
        # Create URI
        uri = f"project_id={self.vector.projectId};vector_id={self.vector.id};endpoint={config.API_URL}"
        # Create layer
        layer_name = f"{PLUGIN_NAME} - {self.vector.name}"
        layer = QgsVectorLayer(uri, layer_name, "qgishub")

        if layer.isValid():
            # MEMO: 各地物はqgishub_idというPKを暗黙的に持っている
            # read-onlyであるし、基本的にユーザーが知る必要のない情報なので
            # GUI上で非表示とする（この情報はlayerおよびプロジェクトのレベルで保存される）
            # 属性テーブルで非表示に
            config = layer.attributeTableConfig()
            columns = config.columns()
            for column in columns:
                if column.name == "qgishub_id":
                    column.hidden = True
            config.setColumns(columns)
            layer.setAttributeTableConfig(config)
            # その他のGUI
            field_idx = layer.fields().indexOf("qgishub_id")
            editor_widget_setup = QgsEditorWidgetSetup("Hidden", {})
            layer.setEditorWidgetSetup(field_idx, editor_widget_setup)

            # Add layer to map
            QgsProject.instance().addMapLayer(layer)
        else:
            QgsMessageLog.logMessage(
                f"Layer is invalid: {uri}", LOG_CATEGORY, Qgis.Critical
            )

    def handleDoubleClick(self):
        """Handle double-click event by adding the vector layer to the map"""
        self.add_to_map()
        return True  # Return True to indicate we've handled the double-click

    def edit_vector(self):
        """Edit vector details"""
        try:
            from PyQt5.QtWidgets import (
                QDialog,
                QDialogButtonBox,
                QFormLayout,
                QLineEdit,
                QVBoxLayout,
            )

            # Create dialog
            dialog = QDialog()
            dialog.setWindowTitle(self.tr("Edit Vector"))
            dialog.resize(400, 250)

            # Create layout
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # Create fields
            name_field = QLineEdit(self.vector.name)

            # Add fields to form
            form_layout.addRow(self.tr("Name:"), name_field)

            # Create buttons
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)

            # Add layouts to dialog
            layout.addLayout(form_layout)
            layout.addWidget(button_box)
            dialog.setLayout(layout)

            # Show dialog
            result = dialog.exec_()

            if result:
                # Get values
                new_name = name_field.text()

                if new_name:
                    # Update vector
                    updated_vector = api.project_vector.update_vector(
                        self.vector.projectId,
                        self.vector.id,
                        UpdateVectorOptions(name=new_name),
                    )

                    if updated_vector:
                        self.vector = updated_vector
                        self.setName(updated_vector.name)
                        self.refresh()
                    else:
                        QgsMessageLog.logMessage(
                            self.tr("Failed to update vector"),
                            LOG_CATEGORY,
                            Qgis.Critical,
                        )

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error editing vector: {}").format(str(e)),
                LOG_CATEGORY,
                Qgis.Critical,
            )

    def delete_vector(self):
        """Delete the vector"""
        try:
            # Confirm deletion
            confirm = QMessageBox.question(
                None,
                self.tr("Delete Vector"),
                self.tr("Are you sure you want to delete vector '{}'?").format(
                    self.vector.name
                ),
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )

            if confirm == QMessageBox.Yes:
                # Delete vector
                success = api.project_vector.delete_vector(
                    self.vector.projectId, self.vector.id
                )

                if success:
                    # Refresh parent to show updated list
                    self.parent().refresh()
                else:
                    QgsMessageLog.logMessage(
                        self.tr("Failed to delete vector"), LOG_CATEGORY, Qgis.Critical
                    )

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error deleting vector: {}").format(str(e)),
                LOG_CATEGORY,
                Qgis.Critical,
            )


class DbRoot(QgsDataItem):
    """Root item for vectors in a project"""

    def __init__(self, parent, name: str, path: str):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=name,
            path=path,
        )

        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon_folder.svg")))

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("DbRoot", message)

    def actions(self, parent):
        actions = []

        # New vector action
        new_vector_action = QAction(self.tr("New Vector"), parent)
        new_vector_action.triggered.connect(self.new_vector)
        actions.append(new_vector_action)

        # Upload vector action
        upload_vector_action = QAction(self.tr("Upload Vector"), parent)
        upload_vector_action.triggered.connect(self.upload_vector)
        actions.append(upload_vector_action)

        # Refresh action
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def new_vector(self):
        """Create a new vector layer in the project"""
        settings = SettingsManager()
        organization_id = settings.get_setting("selected_organization_id")
        organization = api.organization.get_organization(organization_id)
        project_id = settings.get_setting("selected_project_id")

        # check plan limits before creating vector
        plan_limit = api.plan.get_plan_limits(organization.plan)
        if not plan_limit:
            return

        current_vectors = api.project_vector.get_vectors(project_id)
        upload_vector_count = len(current_vectors) + 1
        if upload_vector_count > plan_limit.maxVectors:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr(
                    "Cannot create new vector layer. Your plan allows up to {} vectors, "
                    "but you have reached the limit."
                ).format(plan_limit.maxVectors),
            )
            return

        dialog = QDialog()
        dialog.setWindowTitle(self.tr("Create New Vector Layer"))
        dialog.resize(400, 200)

        # Create layout
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # Name field
        name_field = QLineEdit()
        form_layout.addRow(self.tr("Name:"), name_field)

        # Type field
        type_field = QComboBox()
        type_field.addItems(["POINT", "LINESTRING", "POLYGON"])
        form_layout.addRow(self.tr("Geometry Type:"), type_field)

        # Add description
        description = QLabel(
            self.tr("This will create an empty vector layer in the project.")
        )
        description.setWordWrap(True)

        # Buttons
        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        # Add to layout
        layout.addLayout(form_layout)
        layout.addWidget(description)
        layout.addWidget(button_box)
        dialog.setLayout(layout)

        # Show dialog
        result = dialog.exec_()

        if not result:
            return  # User canceled

        # Get values
        name = name_field.text()
        vector_type = type_field.currentText()

        if not name:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Vector name cannot be empty."),
            )
            return

        options = AddVectorOptions(name=name, type=vector_type)
        new_vector = api.project_vector.add_vector(project_id, options)

        if new_vector:
            QgsMessageLog.logMessage(
                self.tr("Created new vector layer '{}' in project {}").format(
                    name, project_id
                ),
                LOG_CATEGORY,
                Qgis.Info,
            )
            # Refresh to show new vector
            self.refresh()
        else:
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Failed to create the vector layer '{}'.").format(name),
            )

    def upload_vector(self):
        """QGISアクティブレイヤーの地物をサーバーへアップロード"""
        try:
            from qgis import processing

            # Execute with dialog
            result = processing.execAlgorithmDialog("strato:uploadvector")

            # After dialog closes, refresh if needed
            if result:
                self.refresh()

        except Exception as e:
            QgsMessageLog.logMessage(
                self.tr("Error uploading vector: {}").format(str(e)),
                LOG_CATEGORY,
                Qgis.Critical,
            )

    def createChildren(self):
        """Create child items for vectors in project"""
        try:
            settings = SettingsManager()
            project_id = settings.get_setting("selected_project_id")

            if not project_id:
                return [ErrorItem(self, self.tr("No project selected"))]

            # Get vectors for this project
            vectors = api.project_vector.get_vectors(project_id)

            if not vectors:
                return [ErrorItem(self, self.tr("No vectors available"))]

            children = []

            # Create VectorItem for each vector
            for idx, vector in enumerate(vectors):
                vector_path = f"{self.path()}/vector/{vector.id}"
                vector_item = VectorItem(self, vector_path, vector)
                vector_item.setSortKey(idx)
                children.append(vector_item)

            return children

        except Exception as e:
            return [ErrorItem(self, self.tr("Error: {}").format(str(e)))]
