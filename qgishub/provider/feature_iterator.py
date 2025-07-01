from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
)

from . import cache


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

        # Pagination parameters
        self._features = []
        self._features_idx = 0
        self._page_size = 10000  # Number of features to fetch per page
        self._current_offset = 0
        self._last_fetch = False  # Flag to indicate if the last page has been fetched
        self._fetched_count = 0  # Total number of features fetched

        cache.sync_local_cache(
            self._provider._qgishub_vector.id,
            self._provider.fields(),
            self._provider.wkbType(),
        )

    def _load_features_page(self):
        """Load a page of features using pagination"""
        # Return immediately if we've already fetched all features
        if self._last_fetch:
            return

        # Prepare filter parameters
        qgishub_ids = []
        if self._request.filterType() == QgsFeatureRequest.FilterType.FilterFids:
            qgishub_ids = self._request.filterFids()
        elif self._request.filterType() == QgsFeatureRequest.FilterType.FilterFid:
            qgishub_ids = [self._request.filterFid()]

        # Fetch features with pagination parameters
        features = cache.get_features(
            self._provider._qgishub_vector.id,
            self._page_size,
            self._current_offset,
            bbox=self._filter_rect,
            ids=qgishub_ids,
        )

        # Update pagination state
        self._features = features
        self._features_idx = 0
        self._current_offset += len(features)

        # If we received fewer features than requested, we've reached the end
        if len(features) < self._page_size:
            self._last_fetch = True

    def fetchFeature(self, f: QgsFeature) -> bool:
        """読むべき地物の数だけ実行される。引数のQgsFeatureを破壊的に更新する。"""
        if not self._provider.isValid():
            f.setValid(False)
            return False

        # If we've reached the end of the current page, load the next page
        if self._features_idx >= len(self._features):
            # If we've already fetched all features, return False
            if self._last_fetch:
                f.setValid(False)
                return False

            # Load the next page of features
            self._load_features_page()

            # If no more features were loaded, return False
            if len(self._features) == 0:
                f.setValid(False)
                return False

        # Get the current feature
        feature = self._features[self._features_idx]

        f.setGeometry(feature.geometry())
        self.geometryToDestinationCrs(f, self._transform)

        # Set attributes
        # feature["properties"] = { field_name: value, ... }
        f.setFields(feature.fields())
        f.setAttributes(feature.attributes())

        # Set feature ID and validity
        f.setId(feature.id())
        f.setValid(True)

        # Increment counters
        self._features_idx += 1
        self._fetched_count += 1

        return True

    def nextFeatureFilterExpression(self, f: QgsFeature) -> bool:
        return self.fetchFeature(f)

    def __iter__(self):
        """Return self as an iterator object."""
        self.rewind()
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
        self._features = []
        self._features_idx = 0
        self._current_offset = 0
        self._last_fetch = False
        self._fetched_count = 0
        return True

    def close(self) -> bool:
        """Close the iterator and release resources."""
        self._features = []
        self._features_idx = -1
        self._last_fetch = True
        return True
