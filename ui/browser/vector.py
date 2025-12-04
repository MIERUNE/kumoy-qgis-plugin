from typing import Literal

from qgis import processing
from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsFields,
    QgsMessageLog,
    QgsMimeDataUtils,
    QgsProject,
    QgsSimpleFillSymbolLayer,
    QgsSimpleLineSymbolLayer,
    QgsSimpleMarkerSymbolLayer,
    QgsSingleSymbolRenderer,
    QgsSymbol,
    QgsUnitTypes,
    QgsVectorLayer,
)
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtWidgets import (
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
from qgis.utils import iface

from ...imgs import (
    BROWSER_FOLDER_ICON,
    BROWSER_GEOMETRY_LINESTRING_ICON,
    BROWSER_GEOMETRY_POINT_ICON,
    BROWSER_GEOMETRY_POLYGON_ICON,
)
from ...settings_manager import get_settings, store_setting
from ...kumoy import api, constants
from ...kumoy.api.error import format_api_error
from ...kumoy.provider import local_cache
from .utils import ErrorItem


class VectorItem(QgsDataItem):
    """Vector layer item for browser"""

    def __init__(
        self,
        parent,
        path: str,
        vector: api.project_vector.KumoyVector,
        role: Literal["ADMIN", "OWNER", "MEMBER"],
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=vector.name,
            path=path,
        )

        self.vector = vector
        self.vector_uri = f"project_id={self.vector.projectId};vector_id={self.vector.id};vector_name={self.vector.name};vector_type={self.vector.type};"
        self.role = role

        # Set icon based on geometry type
        if vector.type == "POINT":
            self.setIcon(BROWSER_GEOMETRY_POINT_ICON)
        elif vector.type == "LINESTRING":
            self.setIcon(BROWSER_GEOMETRY_LINESTRING_ICON)
        elif vector.type == "POLYGON":
            self.setIcon(BROWSER_GEOMETRY_POLYGON_ICON)

        self.populate()

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("VectorItem", message)

    def hasDragEnabled(self):
        return True

    def mimeUris(self):
        # ドラッグドロップされた際にレイヤーを適切に追加するための実装
        u = QgsMimeDataUtils.Uri()
        u.layerType = "vector"
        u.providerKey = constants.DATA_PROVIDER_KEY
        u.name = self.vector.name
        u.uri = self.vector_uri
        return [u]

    def actions(self, parent):
        actions = []

        # Add to map action
        add_action = QAction(self.tr("Add to Map"), parent)
        add_action.triggered.connect(self.add_to_map)
        actions.append(add_action)

        if self.role in ["ADMIN", "OWNER"]:
            # Edit vector action
            edit_action = QAction(self.tr("Edit Vector"), parent)
            edit_action.triggered.connect(self.edit_vector)
            actions.append(edit_action)

            # Delete vector action
            delete_action = QAction(self.tr("Delete Vector"), parent)
            delete_action.triggered.connect(self.delete_vector)
            actions.append(delete_action)

        # Clear cache action
        clear_cache_action = QAction(self.tr("Clear Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_cache)
        actions.append(clear_cache_action)

        # Refresh action
        refresh_action = QAction(self.tr("Refresh"), parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def add_to_map(self):
        """Add vector layer to QGIS map"""
        try:
            # memo: Kumoy Provider内でAPIはコールされるが、データの存在確認のため、Vectorを取得しておく
            api.project_vector.get_vector(self.vector.projectId, self.vector.id)
        except Exception as e:
            msg = self.tr("Error fetching vector: {}").format(format_api_error(e))
            QgsMessageLog.logMessage(msg, constants.LOG_CATEGORY, Qgis.Critical)
            QMessageBox.critical(None, self.tr("Error"), msg)
            return

        # Create layer
        layer = QgsVectorLayer(self.vector_uri, self.vector.name, "kumoy")
        layer.extent()  # HACK: to ensure extent is calculated - Issue #224

        # Set pixel-based styling
        self._set_pixel_based_style(layer)

        if layer.isValid():
            # kumoy_idをread-onlyに設定
            field_idx = layer.fields().indexOf("kumoy_id")
            # フィールド設定で読み取り専用を設定
            if layer.fields().fieldOrigin(field_idx) == QgsFields.OriginProvider:
                # プロバイダーフィールドの場合
                config = layer.editFormConfig()
                config.setReadOnly(field_idx, True)
                layer.setEditFormConfig(config)

            # Add layer to map
            QgsProject.instance().addMapLayer(layer)
        else:
            QgsMessageLog.logMessage(
                f"Layer is invalid: {self.vector_uri}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )

    def _set_pixel_based_style(self, layer):
        """Set pixel-based styling for the layer"""
        # Create symbol based on geometry type
        if self.vector.type == "POINT":
            # Create point symbol with pixel units
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol and symbol.symbolLayerCount() > 0:
                marker_layer = symbol.symbolLayer(0)
                if isinstance(marker_layer, QgsSimpleMarkerSymbolLayer):
                    # Set size in pixels
                    marker_layer.setSize(5.0)
                    marker_layer.setSizeUnit(QgsUnitTypes.RenderPixels)
                    # Set stroke width in pixels
                    marker_layer.setStrokeWidth(1.0)
                    marker_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPixels)
                    # offset
                    marker_layer.setOffsetUnit(QgsUnitTypes.RenderPixels)

        elif self.vector.type == "LINESTRING":
            # Create line symbol with pixel units
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol and symbol.symbolLayerCount() > 0:
                line_layer = symbol.symbolLayer(0)
                if isinstance(line_layer, QgsSimpleLineSymbolLayer):
                    # Set line width in pixels
                    line_layer.setWidth(2.0)
                    line_layer.setWidthUnit(QgsUnitTypes.RenderPixels)
                    # Set line offset in pixels
                    line_layer.setOffsetUnit(QgsUnitTypes.RenderPixels)

        elif self.vector.type == "POLYGON":
            # Create polygon symbol with pixel units
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())
            if symbol and symbol.symbolLayerCount() > 0:
                fill_layer = symbol.symbolLayer(0)
                if isinstance(fill_layer, QgsSimpleFillSymbolLayer):
                    # Set stroke width in pixels
                    fill_layer.setStrokeWidth(1.0)
                    fill_layer.setStrokeWidthUnit(QgsUnitTypes.RenderPixels)
                    # Set offset in pixels
                    fill_layer.setOffsetUnit(QgsUnitTypes.RenderPixels)

        else:
            # Use default symbol for unknown types
            symbol = QgsSymbol.defaultSymbol(layer.geometryType())

        # Apply the symbol to the layer
        if symbol:
            renderer = QgsSingleSymbolRenderer(symbol)
            layer.setRenderer(renderer)
            layer.triggerRepaint()

    def handleDoubleClick(self):
        """Handle double-click event by adding the vector layer to the map"""
        self.add_to_map()
        return True  # Return True to indicate we've handled the double-click

    def edit_vector(self):
        """Edit vector details"""
        # Create dialog
        dialog = QDialog()
        dialog.setWindowTitle(self.tr("Edit Vector"))
        dialog.resize(400, 250)

        # Create layout
        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # Create fields
        name_field = QLineEdit(self.vector.name)
        name_field.setMaxLength(constants.MAX_CHARACTERS_VECTOR_NAME)

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
        if not result:
            return

        # Get values
        new_name = name_field.text()

        # Update vector
        try:
            updated_vector = api.project_vector.update_vector(
                self.vector.projectId,
                self.vector.id,
                api.project_vector.UpdateVectorOptions(name=new_name),
            )
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error updating vector: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error updating vector: {}").format(format_api_error(e)),
            )
            return

        self.vector = updated_vector
        self.setName(updated_vector.name)
        self.refresh()

    def delete_vector(self):
        """Delete the vector"""
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
            try:
                api.project_vector.delete_vector(self.vector.id)
            except Exception as e:
                QgsMessageLog.logMessage(
                    f"Error deleting vector: {format_api_error(e)}",
                    constants.LOG_CATEGORY,
                    Qgis.Critical,
                )
                QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr("Error deleting vector: {}").format(format_api_error(e)),
                )
                return

            # Refresh parent to show updated list
            self.parent().refresh()

            # remove vector layer from QGIS project if loaded
            for layer in QgsProject.instance().mapLayers().values():
                if (
                    layer.providerType() == "kumoy"
                    and layer.dataProvider().vector_id == self.vector.id
                ):
                    QgsProject.instance().removeMapLayer(layer.id())

            # Clear cache for this vector

            cache_cleared = local_cache.clear_vector(self.vector.id)

            if not cache_cleared:
                iface.messageBar().pushMessage(
                    self.tr("Failed"),
                    self.tr(
                        "Cache could not be cleared completely for vector '{}'. "
                        "Please try again while vector is not open after restarting QGIS"
                    ).format(self.vector.name),
                )

            # Avoid deleted layer to remain on map
            iface.mapCanvas().refresh()

            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("Vector '{}' deleted successfully.").format(self.vector.name),
            )

    def clear_cache(self):
        """Clear cache for this specific vector"""
        # Show confirmation dialog
        confirm = QMessageBox.question(
            None,
            self.tr("Clear Cache Data"),
            self.tr(
                "This will clear the local cache for vector '{}'.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(self.vector.name),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if confirm == QMessageBox.Yes:
            # Clear cache for this specific vector
            cache_cleared = local_cache.clear_vector(self.vector.id)

            if cache_cleared:
                QgsMessageLog.logMessage(
                    self.tr("Cache cleared for vector '{}'").format(self.vector.name),
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("Cache cleared successfully for vector '{}'.").format(
                        self.vector.name
                    ),
                )
            else:
                iface.messageBar().pushMessage(
                    self.tr("Cache Clear Failed"),
                    self.tr(
                        "Cache could not be cleared for vector '{}'. "
                        "Please try again while vector is not open after restarting QGIS"
                    ).format(self.vector.name),
                )


class VectorRoot(QgsDataItem):
    """Root item for vectors in a project"""

    def __init__(
        self,
        parent,
        name: str,
        path: str,
        organization: api.organization.OrganizationDetail,
        project: api.project.ProjectDetail,
    ):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=name,
            path=path,
        )

        self.setIcon(BROWSER_FOLDER_ICON)

        self.organization = organization
        self.project = project

    def tr(self, message):
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("VectorRoot", message)

    def actions(self, parent):
        actions = []

        if self.project.role in ["ADMIN", "OWNER"]:
            # New vector action
            new_vector_action = QAction(self.tr("Create Vector"), parent)
            new_vector_action.triggered.connect(self.new_vector)
            actions.append(new_vector_action)

            # Upload vector action
            upload_vector_action = QAction(self.tr("Upload Vector"), parent)
            upload_vector_action.triggered.connect(self.upload_vector)
            actions.append(upload_vector_action)

        # Clear cache action
        clear_cache_action = QAction(self.tr("Clear Vector Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_cache)
        actions.append(clear_cache_action)

        return actions

    def new_vector(self):
        """Create a new vector layer in the project"""
        try:
            # check plan limits before creating vector
            plan_limit = api.plan.get_plan_limits(self.organization.subscriptionPlan)
            current_vectors = api.project_vector.get_vectors(self.project.id)
            upload_vector_count = len(current_vectors) + 1
            if upload_vector_count > plan_limit.maxVectors:
                QMessageBox.critical(
                    None,
                    self.tr("Error"),
                    self.tr(
                        "You have reached your plan's limit of {} vector layers. "
                        "Please delete one or upgrade your plan to continue."
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
            name_field.setMaxLength(constants.MAX_CHARACTERS_VECTOR_NAME)
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
                    self.tr("Please enter a name for your vector layer."),
                )
                return

            options = api.project_vector.AddVectorOptions(name=name, type=vector_type)
            api.project_vector.add_vector(self.project.id, options)
            QgsMessageLog.logMessage(
                self.tr(
                    "Successfully created vector layer '{}' in project '{}'"
                ).format(name, self.project.id),
                constants.LOG_CATEGORY,
                Qgis.Info,
            )
            # Refresh to show new vector
            self.refresh()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error adding vector: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            QMessageBox.critical(
                None,
                self.tr("Error"),
                self.tr("Error adding vector: {}").format(format_api_error(e)),
            )

    def upload_vector(self):
        """processingを利用してベクターレイヤーをアップロード"""
        # Execute with dialog
        result = processing.execAlgorithmDialog("kumoy:uploadvector")

        # After dialog closes, refresh if needed
        if result:
            self.refresh()

    def createChildren(self):
        """Create child items for vectors in project"""
        project_id = get_settings().selected_project_id

        if not project_id:
            return [ErrorItem(self, self.tr("No project selected"))]

        # Get vectors for this project
        try:
            vectors = api.project_vector.get_vectors(project_id)
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading vectors: {format_api_error(e)}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            return [ErrorItem(self, self.tr("Error loading vectors"))]

        if len(vectors) == 0:
            return [ErrorItem(self, self.tr("No vector layers found in this project"))]

        children = []

        # Create VectorItem for each vector
        for idx, vector in enumerate(vectors):
            vector_path = f"{self.path()}/vector/{vector.id}"
            vector_item = VectorItem(self, vector_path, vector, self.project.role)
            vector_item.setSortKey(idx)
            children.append(vector_item)

        return children

    def clear_cache(self):
        """Clear all vector cache data"""
        # Show confirmation dialog
        confirm = QMessageBox.question(
            None,
            self.tr("Clear Vector Cache"),
            self.tr(
                "This will clear all locally cached vector files. "
                "Data will be re-downloaded next time you access vectors.\n\n"
                "Continue?"
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

        if confirm == QMessageBox.Yes:
            # Get cache directory path
            cache_cleared = local_cache.clear_all_vector()

            if cache_cleared:
                QgsMessageLog.logMessage(
                    self.tr("All vector cache files cleared successfully."),
                    constants.LOG_CATEGORY,
                    Qgis.Info,
                )
                iface.messageBar().pushSuccess(
                    self.tr("Success"),
                    self.tr("All vector cache files have been cleared successfully."),
                )
            else:
                iface.messageBar().pushMessage(
                    self.tr("Vector Cache Clear Failed"),
                    self.tr(
                        "Some vector cache files could not be cleared. "
                        "Please try again after closing QGIS or ensure no files are locked."
                    ),
                )
