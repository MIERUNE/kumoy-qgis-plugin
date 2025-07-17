import time

from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
)


class QgishubFeatureIterator(QgsAbstractFeatureIterator):
    def __init__(self, source, request: QgsFeatureRequest):
        """Constructor"""

        super().__init__(request)
        self._provider = source.get_provider()
        self._request = request if request is not None else QgsFeatureRequest()
        self._transform = QgsCoordinateTransform()

        if (
            self._request.destinationCrs().isValid()
            and self._request.destinationCrs() != self._provider.crs()
        ):
            self._transform = QgsCoordinateTransform(
                self._provider.crs(),
                self._request.destinationCrs(),
                self._request.transformContext(),
            )
        try:
            self._filter_rect = self.filterRectToSourceCrs(self._transform)
        except Exception as e:
            print("ERROR", e)
            self.close()
            return

        self._feature_iterator = self._provider.cached_layer.getFeatures(self._request)

    def fetchFeature(self, f: QgsFeature) -> bool:
        """読むべき地物の数だけ実行される。引数のQgsFeatureを破壊的に更新する。"""
        if not self._provider.isValid():
            f.setValid(False)
            return False

        res = self._feature_iterator.nextFeature(f)

        if not res:
            # If no more features are available, return False
            f.setValid(False)
            return False

        self.geometryToDestinationCrs(f, self._transform)

        # Set feature ID and validity
        f.setValid(True)

        return True

    def nextFeatureFilterExpression(self, f: QgsFeature) -> bool:
        return self.fetchFeature(f)

    def __iter__(self):
        """Return self as an iterator object."""
        self._feature_iterator.rewind()
        return self

    def __next__(self) -> QgsFeature:
        """Returns the next value till current is lower than high"""
        f = QgsFeature()
        if not self.nextFeature(f):
            raise StopIteration
        else:
            return f

    def rewind(self) -> bool:
        """Reset the iterator."""
        return self._feature_iterator.rewind()

    def close(self) -> bool:
        """Close the iterator and release resources."""
        return self._feature_iterator.close()
