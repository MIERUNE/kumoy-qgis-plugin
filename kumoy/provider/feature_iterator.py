from collections import deque
from typing import Deque, List, Optional

from qgis.core import (
    QgsAbstractFeatureIterator,
    QgsCoordinateTransform,
    QgsFeature,
    QgsFeatureRequest,
)

from .. import api, local_cache

FETCH_BATCH_SIZE = 1000


class KumoyFeatureIterator(QgsAbstractFeatureIterator):
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
        except Exception:
            self.close()
            self._filter_rect = None

        self._feature_iterator = self._provider.cached_layer.getFeatures(self._request)
        # Queue for freshly appended features before being handed off to QGIS
        self._pending_features: Deque[QgsFeature] = deque()
        self._remote_exhausted = False
        self._remaining_limit = (
            self._request.limit()
            if self._request.limit() and self._request.limit() > 0
            else None
        )
        self._last_served_id: Optional[int] = None
        self._next_fetch_after_id: Optional[int] = (
            local_cache.vector.max_cached_kumoy_id(self._provider.cached_layer)
        )
        self._original_requested_kumoy_ids = self._extract_requested_fids()
        self._pending_kumoy_ids = (
            set(self._original_requested_kumoy_ids)
            if self._original_requested_kumoy_ids is not None
            else None
        )

    def _extract_requested_fids(self) -> Optional[List[int]]:
        filter_type = self._request.filterType()
        if filter_type == QgsFeatureRequest.FilterFid:
            return [self._request.filterFid()]
        if filter_type == QgsFeatureRequest.FilterFids:
            return list(self._request.filterFids())
        return None

    def _remaining_limit_value(self) -> Optional[int]:
        return self._remaining_limit

    def _should_stop(self) -> bool:
        return self._remaining_limit is not None and self._remaining_limit <= 0

    def fetchFeature(self, f: QgsFeature) -> bool:
        """Return next feature, fetching lazily from API as needed."""
        if not self._provider.isValid() or self._should_stop():
            f.setValid(False)
            return False

        if self._pending_features:
            self._consume_pending(f)
            return True

        if self._feature_iterator.nextFeature(f):
            self._post_process_feature(f)
            return True

        if not self._fetch_more():
            f.setValid(False)
            return False

        return self.fetchFeature(f)

    def _consume_pending(self, f: QgsFeature):
        queued = self._pending_features.popleft()
        f.setFields(queued.fields(), True)
        f.setGeometry(queued.geometry())
        f.setAttributes(queued.attributes())
        self._post_process_feature(f)

    def _post_process_feature(self, f: QgsFeature):
        self.geometryToDestinationCrs(f, self._transform)
        self._track_kumoy_id(f)
        if self._remaining_limit is not None:
            self._remaining_limit -= 1
        f.setValid(True)

    def _track_kumoy_id(self, feature: QgsFeature):
        value = None
        if feature.fields().indexOf("kumoy_id") != -1:
            try:
                value = feature["kumoy_id"]
            except KeyError:
                value = None

        if value is None:
            value = feature.id()

        try:
            kumoy_id = int(value)
        except (TypeError, ValueError):
            return

        self._last_served_id = kumoy_id
        if self._next_fetch_after_id is None or kumoy_id > self._next_fetch_after_id:
            self._next_fetch_after_id = kumoy_id

        if self._pending_kumoy_ids is not None:
            self._pending_kumoy_ids.discard(kumoy_id)
            if not self._pending_kumoy_ids:
                self._remote_exhausted = True

    def _fetch_more(self) -> bool:
        """Fetch more features from remote API and append to local cache."""
        if self._remote_exhausted:
            return False

        if self._pending_kumoy_ids is not None:
            requested_ids = list(self._pending_kumoy_ids)
            if not requested_ids:
                self._remote_exhausted = True
                return False

            remote_features = api.qgis_vector.get_features(
                vector_id=self._provider.kumoy_vector.id,
                kumoy_ids=requested_ids,
            )
        else:
            fetch_limit = FETCH_BATCH_SIZE
            remaining = self._remaining_limit_value()
            if remaining is not None:
                fetch_limit = max(0, min(fetch_limit, remaining))

            if fetch_limit == 0:
                return False

            remote_features = api.qgis_vector.get_features(
                vector_id=self._provider.kumoy_vector.id,
                limit=fetch_limit,
                after_id=self._next_fetch_after_id,
            )

        if not remote_features:
            self._remote_exhausted = True
            return False

        appended = local_cache.vector.append_features(
            self._provider.kumoy_vector.id,
            self._provider.cached_layer,
            self._provider.fields(),
            remote_features,
        )

        self._pending_features.extend(appended)

        if self._pending_kumoy_ids is None and remote_features:
            last = remote_features[-1].get("kumoy_id")
            if last is not None:
                self._next_fetch_after_id = int(last)

        return True

    def nextFeatureFilterExpression(self, f: QgsFeature) -> bool:
        return self.fetchFeature(f)

    def __iter__(self):
        self.rewind()
        return self

    def __next__(self) -> QgsFeature:
        f = QgsFeature()
        if not self.nextFeature(f):
            raise StopIteration
        return f

    def rewind(self) -> bool:
        """Reset the iterator."""
        self._feature_iterator = self._provider.cached_layer.getFeatures(self._request)
        self._pending_features.clear()
        self._remote_exhausted = False
        self._remaining_limit = (
            self._request.limit()
            if self._request.limit() and self._request.limit() > 0
            else None
        )
        self._next_fetch_after_id = local_cache.vector.max_cached_kumoy_id(
            self._provider.cached_layer
        )
        self._last_served_id = None
        if self._original_requested_kumoy_ids is not None:
            self._pending_kumoy_ids = set(self._original_requested_kumoy_ids)
        else:
            self._pending_kumoy_ids = None
        return True

    def close(self) -> bool:
        """Close the iterator and release resources."""
        self._pending_features.clear()
        return self._feature_iterator.close()
