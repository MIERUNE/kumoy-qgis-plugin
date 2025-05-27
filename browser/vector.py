import os

from PyQt5.QtCore import QMetaType
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QAction, QMessageBox
from qgis.core import (
    Qgis,
    QgsDataItem,
    QgsFeature,
    QgsField,
    QgsFields,
    QgsMessageLog,
    QgsProject,
    QgsVectorLayer,
    QgsWkbTypes,
)
from qgis.utils import iface

from ..imgs import IMGS_PATH
from ..qgishub import api
from ..qgishub.api.project_vector import (
    AddVectorOptions,
    QgishubVector,
    UpdateVectorOptions,
    add_vector,
)
from ..qgishub.config import config as qgishub_config
from ..qgishub.constants import LOG_CATEGORY
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

    def actions(self, parent):
        actions = []

        # Add to map action
        add_action = QAction("Add to Map", parent)
        add_action.triggered.connect(self.add_to_map)
        actions.append(add_action)

        # Edit vector action
        edit_action = QAction("Edit Vector", parent)
        edit_action.triggered.connect(self.edit_vector)
        actions.append(edit_action)

        # Delete vector action
        delete_action = QAction("Delete Vector", parent)
        delete_action.triggered.connect(self.delete_vector)
        actions.append(delete_action)

        # Refresh action
        refresh_action = QAction("Refresh", parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def add_to_map(self):
        """Add vector layer to QGIS map"""
        try:
            # Create URI
            uri = f"project_id={self.vector.projectId};vector_id={self.vector.id};endpoint={qgishub_config.API_URL}"
            # Create layer
            layer = QgsVectorLayer(uri, self.vector.name, "qgishub")

            if layer.isValid():
                # Add layer to map
                QgsProject.instance().addMapLayer(layer)
            else:
                QgsMessageLog.logMessage(
                    f"Layer is invalid: {uri}", LOG_CATEGORY, Qgis.Critical
                )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error adding vector to map: {str(e)}", LOG_CATEGORY, Qgis.Critical
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
            dialog.setWindowTitle("Edit Vector")
            dialog.resize(400, 250)

            # Create layout
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # Create fields
            name_field = QLineEdit(self.vector.name)

            # Add fields to form
            form_layout.addRow("Name:", name_field)

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
                            "Failed to update vector", LOG_CATEGORY, Qgis.Critical
                        )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error editing vector: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def delete_vector(self):
        """Delete the vector"""
        try:
            # Confirm deletion
            confirm = QMessageBox.question(
                None,
                "Delete Vector",
                f"Are you sure you want to delete vector '{self.vector.name}'?",
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
                        "Failed to delete vector", LOG_CATEGORY, Qgis.Critical
                    )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error deleting vector: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )


class DbRoot(QgsDataItem):
    """Root item for vectors in a project"""

    def __init__(self, parent, name: str, path: str, project_id: str = None):
        QgsDataItem.__init__(
            self,
            QgsDataItem.Collection,
            parent=parent,
            name=name,
            path=path,
        )

        self.project_id = project_id
        self.setIcon(QIcon(os.path.join(IMGS_PATH, "icon_folder.svg")))

    def actions(self, parent):
        actions = []

        # New vector action
        new_vector_action = QAction("New Vector", parent)
        new_vector_action.triggered.connect(self.new_vector)
        actions.append(new_vector_action)

        # Upload vector action
        upload_vector_action = QAction("Upload Vector", parent)
        upload_vector_action.triggered.connect(self.upload_vector)
        actions.append(upload_vector_action)

        # Refresh action
        refresh_action = QAction("Refresh", parent)
        refresh_action.triggered.connect(self.refresh)
        actions.append(refresh_action)

        return actions

    def new_vector(self):
        """Create a new vector layer in the project"""
        try:
            # Get project ID
            project_id = self.project_id
            if not project_id and hasattr(self.parent(), "project"):
                project_id = self.parent().project.id

            if not project_id:
                QgsMessageLog.logMessage(
                    "No project selected", LOG_CATEGORY, Qgis.Critical
                )
                return

            # Create dialog for new vector
            from PyQt5.QtWidgets import (
                QComboBox,
                QDialog,
                QDialogButtonBox,
                QFormLayout,
                QLabel,
                QLineEdit,
                QVBoxLayout,
            )

            dialog = QDialog()
            dialog.setWindowTitle("Create New Vector Layer")
            dialog.resize(400, 200)

            # Create layout
            layout = QVBoxLayout()
            form_layout = QFormLayout()

            # Name field
            name_field = QLineEdit()
            form_layout.addRow("Name:", name_field)

            # Type field
            type_field = QComboBox()
            type_field.addItems(["POINT", "LINESTRING", "POLYGON"])
            form_layout.addRow("Geometry Type:", type_field)

            # Add description
            description = QLabel(
                "This will create an empty vector layer in the project."
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
                QgsMessageLog.logMessage(
                    "Vector name cannot be empty", LOG_CATEGORY, Qgis.Critical
                )
                return

            options = AddVectorOptions(name=name, type=vector_type)
            new_vector = add_vector(project_id, options)

            if new_vector:
                QgsMessageLog.logMessage(
                    f"Created new vector layer '{name}' in project {project_id}",
                    "QGISHub",
                    Qgis.Info,
                )
                # Refresh to show new vector
                self.refresh()
            else:
                QgsMessageLog.logMessage(
                    f"Failed to create vector layer '{name}'",
                    "QGISHub",
                    Qgis.Critical,
                )

        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error creating vector: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def upload_vector(self):
        """QGISアクティブレイヤーの地物をサーバーへアップロード"""
        try:
            from PyQt5.QtWidgets import (
                QDialog,
                QDialogButtonBox,
                QLabel,
                QListWidget,
                QVBoxLayout,
            )

            # プロジェクト内の全ベクターレイヤー取得
            layers = [
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if layer.type() == Qgis.LayerType.Vector
            ]
            if not layers:
                QgsMessageLog.logMessage(
                    "ベクターレイヤーがありません", LOG_CATEGORY, Qgis.Critical
                )
                return

            # ダイアログでレイヤー選択
            dialog = QDialog()
            dialog.setWindowTitle("アップロードするレイヤーを選択")
            layout = QVBoxLayout()
            layout.addWidget(QLabel("アップロードするレイヤーを選択してください："))
            list_widget = QListWidget()
            for lyr in layers:
                list_widget.addItem(lyr.name())
            layout.addWidget(list_widget)
            button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            layout.addWidget(button_box)
            dialog.setLayout(layout)
            button_box.accepted.connect(dialog.accept)
            button_box.rejected.connect(dialog.reject)
            if dialog.exec_() != QDialog.Accepted or list_widget.currentRow() < 0:
                return

            # 選択されたレイヤー取得
            layer = layers[list_widget.currentRow()]

            # ジオメトリタイプ判定
            wkb_type = layer.wkbType()
            if wkb_type in [QgsWkbTypes.Point]:  # Point
                geom_type = "POINT"
            elif wkb_type in [QgsWkbTypes.LineString]:  # LineString
                geom_type = "LINESTRING"
            elif wkb_type in [QgsWkbTypes.Polygon]:  # Polygon
                geom_type = "POLYGON"
            else:
                QMessageBox.critical(
                    None,
                    "Unsupported Geometry Type",
                    "This geometry type is not supported for upload.",
                    QMessageBox.Ok,
                )
                return

            # 新規Vector作成
            vector_name = layer.name()
            project_id = self.project_id
            if not project_id and hasattr(self.parent(), "project"):
                project_id = self.parent().project.id
            if not project_id:
                QgsMessageLog.logMessage(
                    "No project selected", LOG_CATEGORY, Qgis.Critical
                )
                return
            options = AddVectorOptions(name=vector_name, type=geom_type)
            new_vector = add_vector(project_id, options)
            if not new_vector:
                QgsMessageLog.logMessage(
                    "サーバー側のベクター作成に失敗", LOG_CATEGORY, Qgis.Critical
                )
                return

            # 属性追加
            fields = layer.fields()
            attr_dict = {}
            for field in fields:
                if field.type() == QMetaType.Int:
                    attr_dict[field.name()] = "integer"
                elif (
                    field.type() == QMetaType.Double or field.type() == QMetaType.Float
                ):
                    attr_dict[field.name()] = "float"
                elif field.type() == QMetaType.Bool:
                    attr_dict[field.name()] = "boolean"
                elif field.type() == QMetaType.QString:
                    attr_dict[field.name()] = "string"
                else:
                    QgsMessageLog.logMessage(
                        f"未対応の属性タイプ: {field.type()}", LOG_CATEGORY, Qgis.Critical
                    )
                    continue

            if attr_dict:
                api.qgis_vector.add_attributes(new_vector.id, attr_dict)

            # QgsFeatureで使うために、サポートしているカラムだけのQgsFieldsを作成
            upload_fields = QgsFields()
            for field in fields:
                if field.name() not in attr_dict:
                    # サポートされていないデータ型はスキップ
                    continue
                upload_fields.append(QgsField(field))

            # 地物アップロード
            PAGE_SIZE = 1000
            chunk = []
            for feature in layer.getFeatures():
                if not feature.hasGeometry():
                    # geometryがない地物は無視
                    continue

                # geometryのwkbTypeが異なる場合は無視
                if feature.geometry().wkbType() != wkb_type:
                    continue

                # サポートしているカラムのみを保存するために
                # 新たにQgsFeatureを作成して、事前に作成しておいたQgsFieldsをセット
                fields = QgsFields()
                _f = QgsFeature()
                _f.setGeometry(feature.geometry())
                _f.setFields(upload_fields)
                for field in upload_fields:
                    _f.setAttribute(field.name(), feature.attribute(field.name()))

                chunk.append(_f)

                if len(chunk) == PAGE_SIZE:
                    ok = api.qgis_vector.add_features(new_vector.id, chunk)
                    if not ok:
                        QgsMessageLog.logMessage(
                            "地物アップロード失敗",
                            "QGISHub",
                            Qgis.Critical,
                        )
                        return
                    chunk = []

            if chunk:
                ok = api.qgis_vector.add_features(new_vector.id, chunk)
                if not ok:
                    QgsMessageLog.logMessage(
                        "地物アップロード失敗",
                        "QGISHub",
                        Qgis.Critical,
                    )
                    return

            QgsMessageLog.logMessage(
                f"レイヤー '{vector_name}' のアップロードが完了しました",
                "QGISHub",
                Qgis.Info,
            )
            self.refresh()
        except Exception as e:
            QgsMessageLog.logMessage(
                f"アップロードエラー: {str(e)}", LOG_CATEGORY, Qgis.Critical
            )

    def createChildren(self):
        """Create child items for vectors in project"""
        try:
            # Get project ID from parent or use the one provided in constructor
            project_id = self.project_id
            if not project_id and hasattr(self.parent(), "project"):
                project_id = self.parent().project.id

            if not project_id:
                return [ErrorItem(self, "No project selected")]

            # Get vectors for this project
            vectors = api.project_vector.get_vectors(project_id)

            if not vectors:
                return [ErrorItem(self, "No vectors available")]

            children = []

            # Create VectorItem for each vector
            for idx, vector in enumerate(vectors):
                vector_path = f"{self.path()}/vector/{vector.id}"
                vector_item = VectorItem(self, vector_path, vector)
                vector_item.setSortKey(idx)
                children.append(vector_item)

            return children

        except Exception as e:
            return [ErrorItem(self, f"Error: {str(e)}")]
