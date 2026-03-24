"""restore_project_crs_if_invalid / _read_project_crs_from_xml のユニットテスト"""

import pytest
from plugin_dir.qgis_version import (
    _read_project_crs_from_xml,
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
