"""Feature source for the rare case the cache file and the provider disagree.

Normally the provider hands out the cache's own (ogr) feature source, which
QGIS already makes thread-safe. This wrapper covers the rest:

- no cache yet (first open, still downloading): no features;
- the provider's fields differ from the cache file's columns (an attribute
  was added or deleted and the rebuilt cache has not arrived yet): attributes
  are matched by name, columns the file lacks read as NULL.

It snapshots everything it needs at creation (main thread), so render
threads never touch the provider.
"""

from typing import List, Optional

from qgis.core import (
    NULL,
    Qgis,
    QgsAbstractFeatureIterator,
    QgsAbstractFeatureSource,
    QgsFeature,
    QgsFeatureIterator,
    QgsFeatureRequest,
    QgsFields,
)


class KumoyFeatureSource(QgsAbstractFeatureSource):
    def __init__(
        self,
        fields: QgsFields,
        cache_source: Optional[QgsAbstractFeatureSource] = None,
        cache_fields: Optional[QgsFields] = None,
    ):
        super().__init__()
        self.fields = QgsFields(fields)
        self.cache_source = cache_source
        # provider field index -> cache field index (-1: missing in the cache)
        self.index_map: List[int] = [
            cache_fields.indexOf(f.name()) if cache_fields is not None else -1
            for f in fields
        ]

    def getFeatures(self, request=QgsFeatureRequest()) -> QgsFeatureIterator:
        return QgsFeatureIterator(KumoyFeatureIterator(self, request))


class KumoyFeatureIterator(QgsAbstractFeatureIterator):
    def __init__(self, source: KumoyFeatureSource, request: QgsFeatureRequest):
        super().__init__(request)
        self._fields = source.fields
        self._index_map = source.index_map
        self._iterator: Optional[QgsFeatureIterator] = None
        # ogr iterators do not own their source: keep it alive with us
        self._cache_source = source.cache_source
        if source.cache_source is None:
            return
        cache_request = QgsFeatureRequest(request)
        if request.flags() & Qgis.FeatureRequestFlag.SubsetOfAttributes:
            cache_request.setSubsetOfAttributes(
                [
                    self._index_map[i]
                    for i in request.subsetOfAttributes()
                    if 0 <= i < len(self._index_map) and self._index_map[i] >= 0
                ]
            )
        # The cache source applies the whole request (filters, destination
        # CRS, limit), so nothing here may filter or transform again
        self._iterator = source.cache_source.getFeatures(cache_request)

    def fetchFeature(self, f: QgsFeature) -> bool:
        if self._iterator is None or not self._iterator.nextFeature(f):
            f.setValid(False)
            return False
        values = f.attributes()
        f.setFields(self._fields, False)
        f.setAttributes(
            [values[j] if 0 <= j < len(values) else NULL for j in self._index_map]
        )
        f.setValid(True)
        return True

    def nextFeatureFilterExpression(self, f: QgsFeature) -> bool:
        # Already evaluated by the cache source
        return self.fetchFeature(f)

    def rewind(self) -> bool:
        return self._iterator is not None and self._iterator.rewind()

    def close(self) -> bool:
        if self._iterator is not None:
            self._iterator.close()
        return True
