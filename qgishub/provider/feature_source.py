from qgis.core import (
    QgsAbstractFeatureSource,
    QgsExpressionContext,
    QgsExpressionContextUtils,
    QgsFeatureIterator,
    QgsProject,
    QgsVectorDataProvider,
)

from . import local_cache


class QgishubFeatureSource(QgsAbstractFeatureSource):
    def __init__(self, provider: QgsVectorDataProvider):
        """Constructor"""
        super().__init__()
        self._provider = provider

        self._expression_context = QgsExpressionContext()
        self._expression_context.appendScope(QgsExpressionContextUtils.globalScope())
        self._expression_context.appendScope(
            QgsExpressionContextUtils.projectScope(QgsProject.instance())
        )
        self._expression_context.setFields(self._provider.fields())

    def getFeatures(self, request) -> QgsFeatureIterator:
        """Return features based on the request."""
        return local_cache.get_cached_layer(
            self._provider._qgishub_vector.id
        ).getFeatures(request)

    def get_provider(self):
        """Return the associated provider."""
        return self._provider
