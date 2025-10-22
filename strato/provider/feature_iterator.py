from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
)


class StratoFeatureIterator(QgsAbstractFeatureIterator):
    def __init__(self, source, request: QgsFeatureRequest):
        """Constructor"""

        super().__init__(request)
        self._provider = source.get_provider()
        self._request = request if request is not None else QgsFeatureRequest()
        self._transform = QgsCoordinateTransform()
        self._feature_iterator = None
        self._fid_filter = None

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

        subset_string = self._provider.subsetString()
        effective_request = QgsFeatureRequest(self._request)

        filter_type = self._request.filterType()
        if filter_type == QgsFeatureRequest.FilterFid:
            fid = self._request.filterFid()
            if fid != -1:
                self._fid_filter = {fid}
        elif filter_type == QgsFeatureRequest.FilterFids:
            fids = self._request.filterFids()
            if fids:
                self._fid_filter = set(fids)

        if subset_string:
            if effective_request.filterType() == QgsFeatureRequest.FilterExpression:
                existing_expression = effective_request.filterExpression()
                if existing_expression and existing_expression.expression():
                    combined_expression = (
                        f"({existing_expression.expression()}) AND ({subset_string})"
                    )
                    effective_request.setFilterExpression(combined_expression)
                else:
                    effective_request.setFilterExpression(subset_string)
            else:
                effective_request.setFilterExpression(subset_string)

        self._feature_iterator = self._provider.cached_layer.getFeatures(
            effective_request
        )

    def fetchFeature(self, f: QgsFeature) -> bool:
        """読むべき地物の数だけ実行される。引数のQgsFeatureを破壊的に更新する。"""
        if not self._provider.isValid() or self._feature_iterator is None:
            f.setValid(False)
            return False

        while True:
            res = self._feature_iterator.nextFeature(f)

            if not res:
                f.setValid(False)
                return False

            if self._fid_filter is not None and f.id() not in self._fid_filter:
                continue
            break

        self.geometryToDestinationCrs(f, self._transform)

        # Set feature ID and validity
        f.setValid(True)

        return True

    def nextFeatureFilterExpression(self, f: QgsFeature) -> bool:
        return self.fetchFeature(f)

    def __iter__(self):
        """Return self as an iterator object."""
        if self._feature_iterator is not None:
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
        if self._feature_iterator is None:
            return False
        return self._feature_iterator.rewind()

    def close(self) -> bool:
        """Close the iterator and release resources."""
        if self._feature_iterator is None:
            return True
        return self._feature_iterator.close()
