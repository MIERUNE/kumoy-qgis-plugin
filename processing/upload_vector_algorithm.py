"""
Upload vector layer to STRATO backend
"""

from typing import Dict, List

from PyQt5.QtCore import QCoreApplication
from qgis.core import (
    QgsFeature,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingParameterEnum,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsVectorLayer,
    QgsWkbTypes,
)

from ..qgishub.api.organization import get_organizations
from ..qgishub.api.project import get_projects_by_organization
from ..qgishub.api.project_vector import AddVectorOptions, add_vector
from ..qgishub.api.qgis_vector import add_features, update_columns
from ..qgishub.get_token import get_token


class UploadVectorAlgorithm(QgsProcessingAlgorithm):
    """Algorithm to upload vector layer to STRATO backend"""

    INPUT = "INPUT"
    PROJECT = "PROJECT"
    VECTOR_NAME = "VECTOR_NAME"

    def tr(self, string):
        """Translate string"""
        return QCoreApplication.translate("Processing", string)

    def createInstance(self):
        """Create new instance of algorithm"""
        return UploadVectorAlgorithm()

    def name(self):
        """Algorithm name"""
        return "uploadvector"

    def displayName(self):
        """Algorithm display name"""
        return self.tr("STRATOにベクターレイヤーをアップロード")

    def group(self):
        """Algorithm group"""
        return self.tr("ベクター")

    def groupId(self):
        """Algorithm group ID"""
        return "vector"

    def shortHelpString(self):
        """Short help string"""
        return self.tr(
            "ベクターレイヤーをSTRATOバックエンドにアップロードします。\n\n"
            "このアルゴリズムは以下の手順を実行します：\n"
            "1. 選択したプロジェクトに新しいベクターレイヤーを作成\n"
            "2. レイヤーの属性スキーマを設定\n"
            "3. すべてのフィーチャーをアップロード"
        )

    def initAlgorithm(self, config=None):
        """Initialize algorithm parameters"""
        # Input vector layer
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                self.tr("入力ベクターレイヤー"),
                [QgsProcessing.TypeVector],
            )
        )

        # Get available projects
        try:
            token = get_token()
            if token:
                # Get all organizations first
                organizations = get_organizations()
                project_options = []
                project_ids = []
                
                # Get projects for each organization
                for org in organizations:
                    projects = get_projects_by_organization(org.id)
                    for project in projects:
                        project_options.append(f"{org.name} / {project.name}")
                        project_ids.append(project.id)
                
                self.project_map = dict(zip(project_options, project_ids))
            else:
                project_options = []
                self.project_map = {}
        except Exception as e:
            print(f"Error loading projects: {str(e)}")
            project_options = []
            self.project_map = {}

        # Project selection
        self.addParameter(
            QgsProcessingParameterEnum(
                self.PROJECT,
                self.tr("アップロード先プロジェクト"),
                options=project_options,
                allowMultiple=False,
                optional=False,
            )
        )

        # Vector name
        self.addParameter(
            QgsProcessingParameterString(
                self.VECTOR_NAME,
                self.tr("ベクターレイヤー名"),
                defaultValue="",
                optional=True,
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        """Process the algorithm"""
        # Get parameters
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        project_index = self.parameterAsEnum(parameters, self.PROJECT, context)
        vector_name = self.parameterAsString(parameters, self.VECTOR_NAME, context)

        if not layer:
            raise QgsProcessingException(self.tr("入力レイヤーが無効です"))

        # Get project ID
        project_options = list(self.project_map.keys())
        if project_index >= len(project_options):
            raise QgsProcessingException(self.tr("プロジェクトの選択が無効です"))

        project_id = self.project_map[project_options[project_index]]

        # Use layer name if vector name not provided
        if not vector_name:
            vector_name = layer.name()

        # Check authentication
        token = get_token()
        if not token:
            raise QgsProcessingException(
                self.tr("認証が必要です。プラグイン設定からログインしてください。")
            )

        # Determine geometry type
        geom_type_map = {
            QgsWkbTypes.PointGeometry: "POINT",
            QgsWkbTypes.LineGeometry: "LINESTRING",
            QgsWkbTypes.PolygonGeometry: "POLYGON",
        }

        wkb_type = layer.wkbType()
        geom_type = QgsWkbTypes.geometryType(wkb_type)

        if geom_type not in geom_type_map:
            raise QgsProcessingException(
                self.tr("サポートされていないジオメトリタイプです")
            )

        vector_type = geom_type_map[geom_type]

        feedback.pushInfo(
            self.tr(f"プロジェクト {project_id} に {vector_type} レイヤーを作成中...")
        )

        # Create vector in project
        try:
            add_options = AddVectorOptions(name=vector_name, type=vector_type)
            new_vector = add_vector(project_id, add_options)

            if not new_vector:
                raise QgsProcessingException(
                    self.tr("ベクターレイヤーの作成に失敗しました")
                )

            vector_id = new_vector.id
            feedback.pushInfo(self.tr(f"ベクターレイヤーが作成されました: {vector_id}"))

        except Exception as e:
            raise QgsProcessingException(
                self.tr(f"ベクターレイヤーの作成中にエラーが発生しました: {str(e)}")
            )

        # Define column schema
        feedback.pushInfo(self.tr("属性スキーマを設定中..."))
        columns = self._get_column_schema(layer)

        if columns:
            try:
                success = update_columns(vector_id, columns)
                if not success:
                    feedback.reportError(self.tr("属性スキーマの設定に失敗しました"))
            except Exception as e:
                feedback.reportError(self.tr(f"属性スキーマ設定エラー: {str(e)}"))

        # Upload features
        feedback.pushInfo(self.tr("フィーチャーをアップロード中..."))
        total_features = layer.featureCount()
        
        if total_features == 0:
            feedback.pushInfo(self.tr("アップロードするフィーチャーがありません"))
            return {"VECTOR_ID": vector_id}

        # Process features in batches
        batch_size = 100
        features_uploaded = 0

        try:
            features = list(layer.getFeatures())
            
            for i in range(0, total_features, batch_size):
                if feedback.isCanceled():
                    break

                batch = features[i : i + batch_size]
                success = add_features(vector_id, batch)

                if not success:
                    raise QgsProcessingException(
                        self.tr(f"フィーチャーのアップロードに失敗しました (バッチ {i//batch_size + 1})")
                    )

                features_uploaded += len(batch)
                progress = int((features_uploaded / total_features) * 100)
                feedback.setProgress(progress)
                feedback.pushInfo(
                    self.tr(f"進捗: {features_uploaded}/{total_features} フィーチャー")
                )

        except Exception as e:
            raise QgsProcessingException(
                self.tr(f"フィーチャーのアップロード中にエラーが発生しました: {str(e)}")
            )

        feedback.pushInfo(
            self.tr(f"アップロード完了: {features_uploaded} フィーチャー")
        )

        return {"VECTOR_ID": vector_id}

    def _get_column_schema(self, layer: QgsVectorLayer) -> Dict[str, str]:
        """Get column schema from layer fields"""
        columns = {}
        
        # Type mapping from QGIS to STRATO
        type_map = {
            "Integer": "integer",
            "Integer64": "integer",
            "Real": "float",
            "Double": "float",
            "String": "string",
            "Boolean": "boolean",
        }

        for field in layer.fields():
            field_type = field.typeName()
            
            # Map to STRATO type
            strato_type = type_map.get(field_type, "string")
            columns[field.name()] = strato_type

        return columns