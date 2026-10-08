"""pytest conftest: make plugin importable as 'plugin_dir' package."""

import os
import sys
import types
from pathlib import Path

import pytest

# The plugin root is this directory. For relative imports like
# `from ...kumoy` (in processing/vector/upload/algorithm.py) to work,
# the plugin root must be importable as a package — not as top-level.
#
# Register a virtual 'plugin_dir' package whose __path__ points to the
# plugin root.  This avoids creating a filesystem symlink outside the
# project directory (which can fail in Docker / read-only environments).
_plugin_root = Path(__file__).resolve().parent

_pkg = types.ModuleType("plugin_dir")
_pkg.__path__ = [str(_plugin_root)]
sys.modules["plugin_dir"] = _pkg

# Remove the plugin root from sys.path so that plugin subpackages
# (e.g. 'processing/') don't shadow QGIS built-in modules.
# Plugin modules must be imported via 'plugin_dir.xxx' instead.
_plugin_root_str = str(_plugin_root)
sys.path[:] = [p for p in sys.path if p not in (_plugin_root_str, "")]


@pytest.fixture(scope="session")
def qgis_plugin_path(qgis_app):
    """Add QGIS's built-in plugin directory to sys.path.

    Depends on qgis_app (provided by pytest-qgis) to ensure
    QgsApplication is fully initialized before querying pkgDataPath().
    """
    from qgis.core import QgsApplication

    qgis_plugins = os.path.join(QgsApplication.pkgDataPath(), "python", "plugins")
    if os.path.isdir(qgis_plugins) and qgis_plugins not in sys.path:
        sys.path.append(qgis_plugins)


@pytest.fixture(scope="session")
def _registered_fake_provider(qgis_app):
    """Register a stub provider under the Kumoy vector provider key.

    Provider metadata can only be registered once per QGIS session, so the stub
    reads its extent / feature count from the returned mutable object.
    """
    from qgis.core import (
        QgsCoordinateReferenceSystem,
        QgsDataProvider,
        QgsFeatureRequest,
        QgsField,
        QgsFields,
        QgsProviderMetadata,
        QgsProviderRegistry,
        QgsRectangle,
        QgsVectorDataProvider,
        QgsVectorLayer,
        QgsWkbTypes,
    )
    from qgis.PyQt.QtCore import QVariant

    from plugin_dir.kumoy.constants import DATA_PROVIDER_KEY

    state = types.SimpleNamespace(extent=QgsRectangle(), feature_count=0)

    class _FakeProvider(QgsVectorDataProvider):
        @classmethod
        def createProvider(cls, uri, options, flags=QgsDataProvider.ReadFlags()):
            return _FakeProvider(uri)

        def name(self):
            return DATA_PROVIDER_KEY

        def isValid(self):
            return True

        def crs(self):
            return QgsCoordinateReferenceSystem("EPSG:4326")

        def wkbType(self):
            return QgsWkbTypes.Point

        def geometryType(self):
            return QgsWkbTypes.Point

        def fields(self):
            fields = QgsFields()
            fields.append(QgsField("kumoy_id", QVariant.LongLong))
            return fields

        def extent(self):
            return state.extent

        def featureCount(self):
            return state.feature_count

        def getFeatures(self, request=QgsFeatureRequest()):
            empty = QgsVectorLayer("Point?crs=EPSG:4326", "empty", "memory")
            return empty.getFeatures(request)

        def capabilities(self):
            return QgsVectorDataProvider.Capabilities()

    # 同一キーの二重登録は False になるだけで無害
    QgsProviderRegistry.instance().registerProvider(
        QgsProviderMetadata(
            DATA_PROVIDER_KEY, "fake kumoy provider", _FakeProvider.createProvider
        )
    )
    return state


@pytest.fixture
def fake_kumoy_provider(_registered_fake_provider):
    """Reset the stub provider's state for each test."""
    from qgis.core import QgsRectangle

    _registered_fake_provider.extent = QgsRectangle()
    _registered_fake_provider.feature_count = 0
    return _registered_fake_provider
