import os
from typing import List

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)
from qgis.core import Qgis, QgsMessageLog, QgsProject, QgsRasterLayer, QgsVectorLayer

from ..imgs import IMGS_PATH
from ..qgishub.api import layer
from ..qgishub.api.layer import Layer


class LayerAddDialog(QDialog):
    """Dialog for adding layers from a project"""

    def __init__(self, project_id: str):
        super().__init__()
        self.setWindowTitle("Add Layers")
        self.resize(400, 300)

        self.project_id = project_id
        self.selected_layers = []

        # Load icons
        self.layer_icon = QIcon(os.path.join(IMGS_PATH, "icon_layer.svg"))

        # Create layout
        self.setup_ui()

        # Load layers
        self.load_layers()

    def setup_ui(self):
        """Set up the dialog UI"""
        layout = QVBoxLayout()

        # Instructions
        layout.addWidget(QLabel("Select layers to add to QGIS:"))

        # Layer list
        self.layer_list = QListWidget()
        self.layer_list.setSelectionMode(QListWidget.ExtendedSelection)
        layout.addWidget(self.layer_list)

        # Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self.setLayout(layout)

    def load_layers(self):
        """Load layers for the project"""
        try:
            # Clear existing items
            self.layer_list.clear()

            # Get layers from API
            layers = layer.get_layers_by_project(self.project_id)

            if not layers:
                QgsMessageLog.logMessage(
                    "No layers available for project", "QGISHub", Qgis.Warning
                )
                return

            # Add layers to list
            for layer_item in layers:
                item = QListWidgetItem(self.layer_list)
                item.setText(layer_item.name)
                item.setIcon(self.layer_icon)
                item.setData(Qt.UserRole, layer_item)

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error loading layers: {str(e)}", "QGISHub", Qgis.Critical
            )

    def accept(self):
        """Handle dialog acceptance"""
        # Get selected layers
        selected_items = self.layer_list.selectedItems()
        if not selected_items:
            return

        # Store selected layers
        self.selected_layers = [item.data(Qt.UserRole) for item in selected_items]

        super().accept()

    def get_selected_layers(self) -> List[Layer]:
        """Get the selected layers"""
        return self.selected_layers

    def add_layers_to_qgis(self, layers: List[Layer]):
        """Add the selected layers to QGIS"""
        # This is a placeholder implementation
        # In a real implementation, you would add the layers to QGIS based on their type and source
        for layer_item in layers:
            if layer_item.type.lower() == "vector":
                # Create a vector layer
                vector_layer = QgsVectorLayer(layer_item.source, layer_item.name, "ogr")
                if vector_layer.isValid():
                    QgsProject.instance().addMapLayer(vector_layer)
                    QgsMessageLog.logMessage(
                        f"Added vector layer {layer_item.name}", "QGISHub", Qgis.Success
                    )
                else:
                    QgsMessageLog.logMessage(
                        f"Failed to add vector layer {layer_item.name}",
                        "QGISHub",
                        Qgis.Warning,
                    )
            elif layer_item.type.lower() == "raster":
                # Create a raster layer
                raster_layer = QgsRasterLayer(layer_item.source, layer_item.name)
                if raster_layer.isValid():
                    QgsProject.instance().addMapLayer(raster_layer)
                    QgsMessageLog.logMessage(
                        f"Added raster layer {layer_item.name}", "QGISHub", Qgis.Success
                    )
                else:
                    QgsMessageLog.logMessage(
                        f"Failed to add raster layer {layer_item.name}",
                        "QGISHub",
                        Qgis.Warning,
                    )
            else:
                QgsMessageLog.logMessage(
                    f"Unsupported layer type: {layer_item.type}",
                    "QGISHub",
                    Qgis.Warning,
                )
