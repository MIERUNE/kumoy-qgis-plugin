from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
)

from .. import api


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
        self._page_size = 5000  # Number of features to fetch per page
        self._current_offset = 0
        self._last_fetch = False  # Flag to indicate if the last page has been fetched
        self._fetched_count = 0  # Total number of features fetched
        
        # Apply 10k limit only for attribute table requests (not for map rendering)
        self._max_features = None
        if hasattr(request, 'flags') and request.flags() & QgsFeatureRequest.NoGeometry:
            # Attribute table requests typically use NoGeometry flag for performance
            self._max_features = 10000

    def _load_features_page(self):
        """Load a page of features using pagination"""
        # Return immediately if we've already fetched all features
        if self._last_fetch:
            return
        
        # Stop fetching if we've reached the maximum feature limit (only if limit is set)
        if self._max_features is not None and self._fetched_count >= self._max_features:
            self._last_fetch = True
            return

        # Prepare filter parameters
        qgishub_ids = []
        if self._request.filterType() == QgsFeatureRequest.FilterType.FilterFids:
            qgishub_ids = self._request.filterFids()
        elif self._request.filterType() == QgsFeatureRequest.FilterType.FilterFid:
            qgishub_ids = [self._request.filterFid()]

        # Prepare bbox parameter if spatial filter is applied
        bbox = None
        if not self._filter_rect.isEmpty():
            bbox = [
                self._filter_rect.xMinimum(),
                self._filter_rect.yMinimum(),
                self._filter_rect.xMaximum(),
                self._filter_rect.yMaximum(),
            ]

        # Adjust page size if we have a feature limit
        actual_page_size = self._page_size
        if self._max_features is not None:
            remaining_features = self._max_features - self._fetched_count
            actual_page_size = min(self._page_size, remaining_features)
        
        # Fetch features with pagination parameters
        features = api.qgis_vector.get_features(
            vector_id=self._provider._qgishub_vector.id,
            qgishub_ids=qgishub_ids,
            bbox=bbox,
            limit=actual_page_size,
            offset=self._current_offset,
        )

        # Update pagination state
        self._features = features
        self._features_idx = 0
        self._current_offset += len(features)

        # If we received fewer features than requested, we've reached the end
        # Or if we have a max limit and we've reached it
        if len(features) < actual_page_size:
            self._last_fetch = True
        elif self._max_features is not None and self._fetched_count + len(features) >= self._max_features:
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
        wkb = feature["qgishub_wkb"]
        fid = feature["qgishub_id"]

        # Set geometry
        g = QgsGeometry()
        g.fromWkb(wkb)
        f.setGeometry(g)
        self.geometryToDestinationCrs(f, self._transform)

        # Set attributes
        # feature["properties"] = { field_name: value, ... }
        f.setFields(self._provider.fields())
        for i in range(f.fields().count()):
            f.setAttribute(i, feature["properties"][f.fields().field(i).name()])

        # Set feature ID and validity
        f.setId(fid)
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
        # Reset max features limit based on request
        self._max_features = None
        if hasattr(self._request, 'flags') and self._request.flags() & QgsFeatureRequest.NoGeometry:
            self._max_features = 10000
        return True

    def close(self) -> bool:
        """Close the iterator and release resources."""
        self._features = []
        self._features_idx = -1
        self._last_fetch = True
        return True
