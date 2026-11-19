from typing import Dict, List

from qgis.PyQt.QtWidgets import (
    QAction,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QVBoxLayout,
)

from ... import i18n
from ...kumoy import api, constants, local_cache, vector_layer
from ...kumoy.tasks import run_task
from ...pyqt_version import QT_DIALOG_BUTTON_CANCEL, QT_DIALOG_BUTTON_OK, exec_dialog
from ..error_handler import handle_api_error, push_success
from ..icons import (
    BROWSER_GEOMETRY_LINESTRING_ICON,
    BROWSER_GEOMETRY_POINT_ICON,
    BROWSER_GEOMETRY_POLYGON_ICON,
)
from .utils import ResourceItem, ResourceRoot

_ICONS = {
    "POINT": BROWSER_GEOMETRY_POINT_ICON,
    "LINESTRING": BROWSER_GEOMETRY_LINESTRING_ICON,
    "POLYGON": BROWSER_GEOMETRY_POLYGON_ICON,
}


class VectorItem(ResourceItem):
    PROVIDER_KEY = constants.DATA_PROVIDER_KEY
    ID_KEY = "vector_id"
    LAYER_TYPE = "vector"
    MAX_NAME = constants.MAX_CHARACTERS_VECTOR_NAME
    MAX_ATTRIBUTION = constants.MAX_CHARACTERS_VECTOR_ATTRIBUTION
    CACHE = local_cache.vector

    @staticmethod
    def api_update(vector_id: str, name: str, attribution: str):
        return api.vector.update_vector(vector_id, name=name, attribution=attribution)

    @staticmethod
    def api_delete(vector_id: str) -> None:
        api.vector.delete_vector(vector_id)

    @staticmethod
    def layer_uri(vector) -> str:
        return vector_layer.vector_uri(vector)

    def __init__(self, parent, path: str, vector: api.models.Vector, role: str):
        super().__init__(parent, path, vector, role, _ICONS.get(vector.type))

    @property
    def vector(self) -> api.models.Vector:
        return self.resource

    def create_layer(self):
        # Opening must not block: the provider reads the local cache and
        # syncs with the server in the background
        layer = vector_layer.create_vector_layer(self.resource)
        vector_layer.apply_pixel_based_style(layer)
        return layer

    @staticmethod
    def texts() -> Dict[str, str]:
        return {
            "edit": i18n.tr("Edit Vector"),
            "delete": i18n.tr("Delete Vector"),
            "add_many": i18n.tr("Add {} Vectors to Map"),
            "add_failed": i18n.tr("Some vectors could not be added"),
            "clear_many": i18n.tr("Clear Cache for {} Vectors"),
            "delete_many": i18n.tr("Delete {} Vectors"),
            "delete_title_many": i18n.tr("Delete Vectors"),
            "confirm_delete": i18n.tr("Are you sure you want to delete vector '{}'?"),
            "confirm_delete_many": i18n.tr(
                "Are you sure you want to delete {} vectors?\n{}"
            ),
            "deleted": i18n.tr("Vector '{}' deleted successfully."),
            "deleted_many": i18n.tr("{} vectors have been deleted successfully."),
            "delete_failed": i18n.tr("Some vectors could not be deleted"),
            "clear_all": i18n.tr("Clear Vector Cache Data"),
            "clear_all_loaded": i18n.tr(
                "Cannot clear vector cache while vector layers are loaded on the "
                "map. Please close your map first."
            ),
            "confirm_clear_all": i18n.tr(
                "This will clear all locally cached vector files ({}). "
                "Data will be re-downloaded next time you access vectors.\n\n"
                "Continue?"
            ),
            "all_cleared": i18n.tr(
                "All vector cache files have been cleared successfully."
            ),
            "load_failed": i18n.tr("Error loading vectors"),
            "empty": i18n.tr("No vector layers found in this project"),
        }


class VectorRoot(ResourceRoot):
    """Root item for vectors in a project"""

    ITEM_CLASS = VectorItem
    UPLOAD_ALGORITHM = "kumoy:uploadvector"

    @staticmethod
    def fetch(project_id: str):
        return api.vector.get_vectors(project_id)

    def new_item(self, path: str, vector) -> VectorItem:
        return VectorItem(self, path, vector, self.project.role)

    def editor_actions(self, parent: QMenu) -> List[QAction]:
        new_vector_action = QAction(i18n.tr("Create Vector"), parent)
        new_vector_action.triggered.connect(self.new_vector)
        upload_vector_action = QAction(i18n.tr("Upload Vector"), parent)
        upload_vector_action.triggered.connect(self.upload)
        return [new_vector_action, upload_vector_action]

    def new_vector(self) -> None:
        """Create an empty vector in the project"""
        dialog = QDialog()  # no parent: freed when the function returns
        dialog.setWindowTitle(i18n.tr("Create New Vector Layer"))
        dialog.resize(400, 200)

        form_layout = QFormLayout()
        name_field = QLineEdit()
        name_field.setMaxLength(constants.MAX_CHARACTERS_VECTOR_NAME)
        form_layout.addRow(
            i18n.tr("Name:") + ' <span style="color: red;">*</span>', name_field
        )
        type_field = QComboBox()
        type_field.addItems(["POINT", "LINESTRING", "POLYGON"])
        form_layout.addRow(
            i18n.tr("Geometry Type:") + ' <span style="color: red;">*</span>',
            type_field,
        )
        attribution_field = QLineEdit()
        attribution_field.setMaxLength(constants.MAX_CHARACTERS_VECTOR_ATTRIBUTION)
        form_layout.addRow(i18n.tr("Attribution:"), attribution_field)

        description = QLabel(
            i18n.tr("This will create an empty vector layer in the project.")
        )
        description.setWordWrap(True)

        button_box = QDialogButtonBox(QT_DIALOG_BUTTON_OK | QT_DIALOG_BUTTON_CANCEL)
        button_box.accepted.connect(dialog.accept)
        button_box.rejected.connect(dialog.reject)
        ok_button = button_box.button(QT_DIALOG_BUTTON_OK)
        ok_button.setEnabled(False)
        name_field.textChanged.connect(lambda t: ok_button.setEnabled(bool(t.strip())))

        layout = QVBoxLayout()
        layout.addLayout(form_layout)
        layout.addWidget(description)
        layout.addWidget(button_box)
        dialog.setLayout(layout)

        if not exec_dialog(dialog):
            return

        name = name_field.text().strip()
        vector_type = type_field.currentText()
        attribution = attribution_field.text()
        project_id = self.project.id

        def on_success(_vector_id: str) -> None:
            push_success(i18n.tr("Vector '{}' has been created.").format(name))
            self.refresh()

        # The plan's vector limit is checked by the server (429 is explained
        # by the error handler); checking it here needed a blocking request
        run_task(
            i18n.tr("Creating vector"),
            lambda task: api.vector.create_vector(
                project_id, name, vector_type, attribution
            ),
            on_success,
            lambda e: handle_api_error(e, title=i18n.tr("Error adding vector")),
        )
