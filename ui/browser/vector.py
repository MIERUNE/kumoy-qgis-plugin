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
    QMenu,
    QMessageBox,
    QVBoxLayout,
)
from qgis.utils import iface

from ...error_handler import handle_api_error
from ...kumoy import api, constants, local_cache
from ...kumoy.api.error import UnauthorizedError, format_api_error
from ...pyqt_version import (
    Q_MESSAGEBOX_STD_BUTTON,
    QT_DIALOG_BUTTON_CANCEL,
    QT_DIALOG_BUTTON_OK,
    exec_dialog,
)
from ...kumoy.settings_manager import get_settings
from ..icons import (
    BROWSER_FOLDER_ICON,
    BROWSER_GEOMETRY_LINESTRING_ICON,
    BROWSER_GEOMETRY_POINT_ICON,
    BROWSER_GEOMETRY_POLYGON_ICON,
)
from .utils import ErrorItem


def tr(message: str, context: str = "@default") -> str:
    return QCoreApplication.translate(context, message)


class VectorItem(QgsDataItem):
    """Vector layer item for browser"""

    def __init__(
        self,
        parent,
        path: str,
        vector: api.vector.KumoyVector,
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

    def tr(self, message: str) -> str:
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("VectorItem", message)

    def hasDragEnabled(self) -> bool:
        return True

    def mimeUris(self) -> list[QgsMimeDataUtils.Uri]:
        # ドラッグドロップされた際にレイヤーを適切に追加するための実装
        u = QgsMimeDataUtils.Uri()
        u.layerType = "vector"
        u.providerKey = constants.DATA_PROVIDER_KEY
        u.name = self.vector.name
        u.uri = self.vector_uri
        return [u]

    def build_actions(self, parent: QMenu) -> list[QAction]:
        """Build context menu actions for this item (used by KumoyDataItemGuiProvider)."""
        actions = []

        # Add to map action
        add_action = QAction(self.tr("Add to Map"), parent)
        add_action.triggered.connect(self.add_to_map)
        actions.append(add_action)

        # Clear cache action
        clear_cache_action = QAction(self.tr("Clear Cache Data"), parent)
        clear_cache_action.triggered.connect(self.clear_cache)
        actions.append(clear_cache_action)

        if self.role in ["ADMIN", "OWNER"]:
            # Edit vector action
            edit_action = QAction(self.tr("Edit Vector"), parent)
            edit_action.triggered.connect(self.edit_vector)
            actions.append(edit_action)

            # Delete vector action
            delete_action = QAction(self.tr("Delete Vector"), parent)
            delete_action.triggered.connect(self.delete_vector)
            actions.append(delete_action)

        return actions

    def import_vector(self) -> None:
        api.vector.get_vector(self.vector.id)

        layer = QgsVectorLayer(
            self.vector_uri, self.vector.name, constants.DATA_PROVIDER_KEY
        )
        self._set_pixel_based_style(layer)

        if layer.isValid():
            # Set kumoy_id to read-only
            field_idx = layer.fields().indexOf("kumoy_id")
            if layer.fields().fieldOrigin(field_idx) == QgsFields.OriginProvider:
                config = layer.editFormConfig()
                config.setReadOnly(field_idx, True)
                layer.setEditFormConfig(config)
            QgsProject.instance().addMapLayer(layer)
        else:
            raise RuntimeError(self.tr("Layer is invalid: {}").format(self.vector_uri))

    def add_to_map(self) -> None:
        """Add vector layer to QGIS map"""
        try:
            self.import_vector()
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=self.tr("Error adding vector to map"),
            )

    def _set_pixel_based_style(self, layer: QgsVectorLayer) -> None:
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

    def handleDoubleClick(self) -> bool:
        """Handle double-click event by adding the vector layer to the map"""
        self.add_to_map()
        return True  # Return True to indicate we've handled the double-click

    def edit_vector(self) -> None:
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
        attribution_field = QLineEdit(self.vector.attribution)
        attribution_field.setMaxLength(constants.MAX_CHARACTERS_VECTOR_ATTRIBUTION)

        # Add fields to form
        form_layout.addRow(
            self.tr("Name:") + ' <span style="color: red;">*</span>', name_field
        )
        form_layout.addRow(self.tr("Attribution:"), attribution_field)

        # Create buttons
        button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)

        # Disable OK if name is empty
        ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
        ok_button.setEnabled(bool(name_field.text().strip()))
        name_field.textChanged.connect(
            lambda text: ok_button.setEnabled(bool(text.strip()))
        )

        # Add layouts to dialog
        layout.addLayout(form_layout)
        layout.addWidget(button_box)
        dialog.setLayout(layout)

        # Show dialog
        result = exec_dialog(dialog)
        if not result:
            return

        # Get values
        new_name = name_field.text()
        new_attribution = attribution_field.text()

        # Update vector
        try:
            updated_vector = api.vector.update_vector(
                self.vector.id,
                api.vector.UpdateVectorOptions(
                    name=new_name, attribution=new_attribution
                ),
            )
        except Exception as e:
            handle_api_error(
                e,
                parent=None,
                log_prefix=self.tr("Error updating vector"),
            )
            return

        self.vector = updated_vector
        self.setName(updated_vector.name)
        self.refresh()

    def process_delete_vector(self) -> None:
        """Call API to delete the vector, remove from map and clear cache."""
        api.vector.delete_vector(self.vector.id)

        # Remove from QGIS project if loaded
        for layer in list(QgsProject.instance().mapLayers().values()):
            if (
                layer.providerType() == constants.DATA_PROVIDER_KEY
                and layer.dataProvider().vector_id == self.vector.id
            ):
                QgsProject.instance().removeMapLayer(layer.id())

        local_cache.vector.clear(self.vector.id)

    def delete_vector(self) -> None:
        """Delete the vector"""
        confirm = QMessageBox.question(
            None,
            self.tr("Delete Vector"),
            self.tr("Are you sure you want to delete vector '{}'?").format(
                self.vector.name
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            try:
                self.process_delete_vector()
            except Exception as e:
                handle_api_error(
                    e,
                    parent=None,
                    log_prefix=self.tr("Error deleting vector"),
                )
                return

            self.parent().refresh()
            iface.mapCanvas().refresh()
            iface.messageBar().pushSuccess(
                self.tr("Success"),
                self.tr("Vector '{}' deleted successfully.").format(self.vector.name),
            )

    def is_loaded_on_map(self) -> bool:
        """Return True if this vector is currently loaded on the QGIS map."""
        for layer in QgsProject.instance().mapLayers().values():
            if (
                layer.providerType() == constants.DATA_PROVIDER_KEY
                and layer.dataProvider().vector_id == self.vector.id
            ):
                return True
        return False

    def process_vector_cache_clear(self) -> bool:
        cleared = local_cache.vector.clear(self.vector.id)
        return cleared

    def clear_cache(self) -> None:
        """Clear cache for this specific vector"""
        if self.is_loaded_on_map():
            iface.messageBar().pushMessage(
                self.tr("Cannot Clear Cache"),
                self.tr(
                    "Cannot clear cache for vector '{}' while it is loaded on the map. "
                    "Please close the map first."
                ).format(self.vector.name),
            )
            return

        confirm = QMessageBox.question(
            None,
            self.tr("Clear Cache Data"),
            self.tr(
                "This will clear the local cache for vector '{}'.\n"
                "The cached data will be re-downloaded when you access it next time.\n"
                "Do you want to continue?"
            ).format(self.vector.name),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            if self.process_vector_cache_clear():
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

    def tr(self, message: str) -> str:
        """Get the translation for a string using Qt translation API"""
        return QCoreApplication.translate("VectorRoot", message)

    def actions(self, parent: QMenu) -> list[QAction]:
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

    def new_vector(self) -> None:
        """Create a new vector layer in the project"""
        try:
            # check plan limits before creating vector
            plan_limit = api.plan.get_plan_limits(
                self.organization.subscriptionPlan,
                self.organization.storageUnits,
            )
            current_vectors = api.vector.get_vectors(self.project.id)
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
            form_layout.addRow(
                self.tr("Name:") + ' <span style="color: red;">*</span>', name_field
            )

            # Type field
            type_field = QComboBox()
            type_field.addItems(["POINT", "LINESTRING", "POLYGON"])
            form_layout.addRow(
                self.tr("Geometry Type:") + ' <span style="color: red;">*</span>',
                type_field,
            )

            # Attribution field
            attribution_field = QLineEdit()
            attribution_field.setMaxLength(constants.MAX_CHARACTERS_VECTOR_ATTRIBUTION)
            form_layout.addRow(self.tr("Attribution:"), attribution_field)

            # Add description
            description = QLabel(
                self.tr("This will create an empty vector layer in the project.")
            )
            description.setWordWrap(True)

            # Buttons
            button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)

            # Disable OK if name is empty
            ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
            ok_button.setEnabled(bool(name_field.text().strip()))
            name_field.textChanged.connect(
                lambda text: ok_button.setEnabled(bool(text.strip()))
            )

            # Add to layout
            layout.addLayout(form_layout)
            layout.addWidget(description)
            layout.addWidget(button_box)
            dialog.setLayout(layout)

            # Show dialog
            result = exec_dialog(dialog)

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

            attribution = attribution_field.text()
            options = api.vector.AddVectorOptions(
                name=name, type=vector_type, attribution=attribution
            )
            api.vector.add_vector(self.project.id, options)
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
            handle_api_error(
                e,
                parent=None,
                log_prefix=self.tr("Error adding vector"),
            )

    def upload_vector(self) -> None:
        """processingを利用してベクターレイヤーをアップロード"""
        # Execute with dialog
        result = processing.execAlgorithmDialog("kumoy:uploadvector")

        # After dialog closes, refresh if needed
        if result:
            self.refresh()

    def createChildren(self) -> list[QgsDataItem]:
        """Create child items for vectors in project"""
        project_id = get_settings().selected_project_id

        if not project_id:
            return [ErrorItem(self, self.tr("No project selected"))]

        # Get vectors for this project
        try:
            vectors = api.vector.get_vectors(project_id)
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return [ErrorItem(self, self.tr("Session expired - please log in"))]
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

    def clear_cache(self) -> None:
        """Clear all vector cache data"""
        # Check if any kumoy vector layer is currently loaded on the map
        for layer in QgsProject.instance().mapLayers().values():
            if layer.providerType() == constants.DATA_PROVIDER_KEY:
                iface.messageBar().pushMessage(
                    self.tr("Cannot Clear Cache"),
                    self.tr(
                        "Cannot clear vector cache while vector layers are loaded on the map. "
                        "Please close your map first."
                    ),
                )
                return

        # Show confirmation dialog
        confirm = QMessageBox.question(
            None,
            self.tr("Clear Vector Cache"),
            self.tr(
                "This will clear all locally cached vector files. "
                "Data will be re-downloaded next time you access vectors.\n\n"
                "Continue?"
            ),
            Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
            Q_MESSAGEBOX_STD_BUTTON.No,
        )

        if confirm == Q_MESSAGEBOX_STD_BUTTON.Yes:
            cache_cleared = local_cache.vector.clear_all()

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


def add_multiple_vectors(items: list[VectorItem]) -> None:
    errors = []
    for item in items:
        try:
            item.import_vector()
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            return
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error adding vector '{item.vector.name}': {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            errors.append(f"{item.vector.name}: {error_text}")

    if errors:
        QMessageBox.critical(
            None,
            tr("Error"),
            tr("Some vectors could not be added:\n{}").format("\n".join(errors)),
        )


def clear_cache_multiple_vectors(items: list[VectorItem]) -> None:
    loaded_names = [i.vector.name for i in items if i.is_loaded_on_map()]

    if loaded_names:
        iface.messageBar().pushMessage(
            tr("Cannot Clear Cache"),
            tr("Cannot clear cache for vectors loaded on the map: {}").format(
                ", ".join(loaded_names)
            ),
        )
        return

    confirm = QMessageBox.question(
        None,
        tr("Clear Cache Data"),
        tr(
            "This will clear the local cache for {} vectors.\n"
            "The cached data will be re-downloaded when you access it next time.\n"
            "Do you want to continue?"
        ).format(len(items)),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    failed = [i.vector.name for i in items if not i.process_vector_cache_clear()]

    if failed:
        iface.messageBar().pushMessage(
            tr("Cache Clear Failed"),
            tr("Could not clear cache for: {}").format(", ".join(failed)),
        )
    else:
        iface.messageBar().pushSuccess(
            tr("Success"),
            tr("Cache cleared successfully for {} vectors.").format(len(items)),
        )


def delete_multiple_vectors(items: list[VectorItem]) -> None:
    names = "\n".join(f"  - {i.vector.name}" for i in items)
    confirm = QMessageBox.question(
        None,
        tr("Delete Vectors"),
        tr("Are you sure you want to delete {} vectors?\n{}").format(len(items), names),
        Q_MESSAGEBOX_STD_BUTTON.Yes | Q_MESSAGEBOX_STD_BUTTON.No,
        Q_MESSAGEBOX_STD_BUTTON.No,
    )
    if confirm != Q_MESSAGEBOX_STD_BUTTON.Yes:
        return

    errors = []
    deleted_count = 0
    parent_item = items[0].parent() if items else None

    aborted_unauthorized = False
    for item in items:
        try:
            item.process_delete_vector()
            deleted_count += 1
        except UnauthorizedError as e:
            handle_api_error(e, parent=None)
            aborted_unauthorized = True
            break
        except Exception as e:
            error_text = format_api_error(e)
            QgsMessageLog.logMessage(
                f"Error deleting vector '{item.vector.name}': {error_text}",
                constants.LOG_CATEGORY,
                Qgis.Critical,
            )
            errors.append(f"{item.vector.name}: {error_text}")

    if parent_item:
        parent_item.refresh()

    iface.mapCanvas().refresh()

    if aborted_unauthorized:
        return

    if errors:
        QMessageBox.critical(
            None,
            tr("Error"),
            tr("Some vectors could not be deleted:\n{}").format("\n".join(errors)),
        )
    else:
        iface.messageBar().pushSuccess(
            tr("Success"),
            tr("{} vectors have been deleted successfully.").format(deleted_count),
        )
