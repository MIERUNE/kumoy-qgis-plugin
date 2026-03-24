"""restore_project_crs_if_invalid / _read_project_crs_from_xml / restore_xyz のユニットテスト"""

from unittest.mock import MagicMock, patch

import pytest
from plugin_dir.qgis_version import (
    _restore_xyz_datasource,
    _read_project_crs_from_xml,
    restore_xyz_layer_datasources,
    restore_project_crs_if_invalid,
)
from qgis.core import QgsCoordinateReferenceSystem, QgsProject

pytestmark = pytest.mark.usefixtures("qgis_plugin_path")

# Minimal .qgs XML template with <projectCrs> block
_PROJECT_XML_TEMPLATE = """\
<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.40">
  <projectCrs>
    <spatialrefsys>
      <authid>{authid}</authid>
      <wkt>{wkt}</wkt>
      <proj4>{proj4}</proj4>
    </spatialrefsys>
  </projectCrs>
</qgis>
"""

_EMPTY_PROJECT_XML = """\
<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<qgis version="3.40">
</qgis>
"""


class TestReadProjectCrsFromXml:
    def test_valid_authid(self):
        xml = _PROJECT_XML_TEMPLATE.format(authid="EPSG:4326", wkt="", proj4="")
        crs = _read_project_crs_from_xml(xml)
        assert crs.isValid()
        assert crs.authid() == "EPSG:4326"

    def test_valid_epsg_3857(self):
        xml = _PROJECT_XML_TEMPLATE.format(authid="EPSG:3857", wkt="", proj4="")
        crs = _read_project_crs_from_xml(xml)
        assert crs.isValid()
        assert crs.authid() == "EPSG:3857"

    def test_no_projectcrs_element(self):
        crs = _read_project_crs_from_xml(_EMPTY_PROJECT_XML)
        assert not crs.isValid()

    def test_empty_authid_with_proj4_fallback(self):
        xml = _PROJECT_XML_TEMPLATE.format(
            authid="", wkt="", proj4="+proj=longlat +datum=WGS84 +no_defs"
        )
        crs = _read_project_crs_from_xml(xml)
        assert crs.isValid()

    def test_user_authid_ignored_with_wkt_fallback(self):
        wkt = QgsCoordinateReferenceSystem("EPSG:4326").toWkt()
        xml = _PROJECT_XML_TEMPLATE.format(authid="USER:100000", wkt=wkt, proj4="")
        crs = _read_project_crs_from_xml(xml)
        assert crs.isValid()

    def test_all_empty_returns_invalid(self):
        xml = _PROJECT_XML_TEMPLATE.format(authid="", wkt="", proj4="")
        crs = _read_project_crs_from_xml(xml)
        assert not crs.isValid()


class TestRestoreProjectCrsIfInvalid:
    def test_does_nothing_when_crs_already_valid(self):
        project = QgsProject.instance()
        original_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        project.setCrs(original_crs)

        xml = _PROJECT_XML_TEMPLATE.format(authid="EPSG:4326", wkt="", proj4="")
        restore_project_crs_if_invalid(xml)

        # CRS should remain unchanged
        assert project.crs().authid() == "EPSG:3857"

    def test_restores_crs_when_invalid(self):
        project = QgsProject.instance()
        project.setCrs(QgsCoordinateReferenceSystem())  # set invalid CRS

        xml = _PROJECT_XML_TEMPLATE.format(authid="EPSG:4326", wkt="", proj4="")
        restore_project_crs_if_invalid(xml)

        assert project.crs().isValid()
        assert project.crs().authid() == "EPSG:4326"

    def test_no_restore_when_xml_has_no_crs(self):
        project = QgsProject.instance()
        project.setCrs(QgsCoordinateReferenceSystem())  # set invalid CRS

        restore_project_crs_if_invalid(_EMPTY_PROJECT_XML)

        assert not project.crs().isValid()


class TestFixXyzDatasource:
    # --- already in QGIS 3 format → no-op ---

    def test_qgis3_format_returns_same_string(self):
        src = "http-header:referer=&type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=18&zmin=0"
        assert _restore_xyz_datasource(src) == src

    def test_non_xyz_layer_returns_same_string(self):
        src = "contextualWMSLegend=0&crs=EPSG:4326&url=https://example.com/wms"
        assert _restore_xyz_datasource(src) == src

    # --- QGIS 4 percent-encoded format → converted ---

    def test_qgis4_https_url_decoded(self):
        src = "crs=EPSG%3A3857&format&type=xyz&url=https%3A%2F%2Ftile.openstreetmap.org%2F%7Bz%7D%2F%7Bx%7D%2F%7By%7D.png&zmax=18&zmin=0&http-header:referer="
        result = _restore_xyz_datasource(src)
        assert "url=https://tile.openstreetmap.org/" in result
        # other parameters preserved
        assert "crs=EPSG%3A3857" in result
        assert "zmin=0" in result
        assert "zmax=18" in result

    def test_qgis4_http_url_decoded(self):
        src = "type=xyz&url=http%3A%2F%2Ftile.example.com%2F%7Bz%7D%2F%7Bx%7D%2F%7By%7D.png&zmax=10&zmin=2"
        result = _restore_xyz_datasource(src)
        assert "url=http://tile.example.com/" in result

    def test_only_url_param_is_decoded(self):
        # crs= and http-header:referer= must stay percent-encoded as in the original
        src = "crs=EPSG%3A3857&format&type=xyz&url=https%3A%2F%2Ftile.openstreetmap.org%2F%7Bz%7D%2F%7Bx%7D%2F%7By%7D.png&zmax=18&zmin=0&http-header:referer="
        result = _restore_xyz_datasource(src)
        assert (
            result
            == "crs=EPSG%3A3857&format&type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=18&zmin=0&http-header:referer="
        )

    def test_extra_params_preserved(self):
        # authcfg and other unknown params must not be dropped
        src = "type=xyz&url=https%3A%2F%2Ftile.example.com%2F%7Bz%7D.png&zmax=18&zmin=0&authcfg=abc123"
        result = _restore_xyz_datasource(src)
        assert "authcfg=abc123" in result

    def test_custom_referer_preserved(self):
        src = "type=xyz&url=https%3A%2F%2Ftile.example.com%2F%7Bz%7D.png&zmax=18&zmin=0&http-header:referer=https%3A%2F%2Fexample.com"
        result = _restore_xyz_datasource(src)
        assert "http-header:referer=https%3A%2F%2Fexample.com" in result


class TestFixXyzLayerDatasources:
    def _make_xyz_layer(self, source: str, provider: str = "wms") -> MagicMock:
        layer = MagicMock()
        layer.providerType.return_value = provider
        layer.source.return_value = source
        layer.name.return_value = "OpenStreetMap"
        return layer

    def test_fixes_qgis4_xyz_layer(self):
        src = "crs=EPSG%3A3857&format&type=xyz&url=https%3A%2F%2Ftile.openstreetmap.org%2F%7Bz%7D%2F%7Bx%7D%2F%7By%7D.png&zmax=18&zmin=0&http-header:referer="
        layer = self._make_xyz_layer(src)

        with patch("plugin_dir.qgis_version.QgsProject") as mock_project:
            mock_project.instance.return_value.mapLayers.return_value = {"id1": layer}
            restore_xyz_layer_datasources()

        layer.setDataSource.assert_called_once()
        fixed_src = layer.setDataSource.call_args[0][0]
        assert "url=https://tile.openstreetmap.org/" in fixed_src

    def test_skips_qgis3_xyz_layer(self):
        src = "http-header:referer=&type=xyz&url=https://tile.openstreetmap.org/%7Bz%7D/%7Bx%7D/%7By%7D.png&zmax=18&zmin=0"
        layer = self._make_xyz_layer(src)

        with patch("plugin_dir.qgis_version.QgsProject") as mock_project:
            mock_project.instance.return_value.mapLayers.return_value = {"id1": layer}
            restore_xyz_layer_datasources()

        layer.setDataSource.assert_not_called()

    def test_skips_non_wms_layer(self):
        layer = self._make_xyz_layer(
            "type=xyz&url=https%3A%2F%2Fexample.com", provider="ogr"
        )

        with patch("plugin_dir.qgis_version.QgsProject") as mock_project:
            mock_project.instance.return_value.mapLayers.return_value = {"id1": layer}
            restore_xyz_layer_datasources()

        layer.setDataSource.assert_not_called()

    def test_fixes_multiple_layers(self):
        src = "type=xyz&url=https%3A%2F%2Ftile.example.com%2F%7Bz%7D.png&zmax=18&zmin=0"
        layers = {f"id{i}": self._make_xyz_layer(src) for i in range(3)}

        with patch("plugin_dir.qgis_version.QgsProject") as mock_project:
            mock_project.instance.return_value.mapLayers.return_value = layers
            restore_xyz_layer_datasources()

        for layer in layers.values():
            layer.setDataSource.assert_called_once()
