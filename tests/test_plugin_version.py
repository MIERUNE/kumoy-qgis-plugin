import pytest

from plugin_dir.plugin_version import _parse_version, is_plugin_version_compatible

pytestmark = pytest.mark.usefixtures("qgis_plugin_path")


class TestParseVersion:
    def test_simple_version(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_v_prefix(self):
        assert _parse_version("v1.0.0") == (1, 0, 0)

    def test_prerelease_hyphen(self):
        assert _parse_version("v1.0.0-beta") == (1, 0, 0)

    def test_prerelease_dot(self):
        assert _parse_version("v1.0.alpha") == (1, 0)

    def test_two_segments(self):
        assert _parse_version("v1.0") == (1, 0)

    def test_two_segments_with_prerelease(self):
        assert _parse_version("v1.0-beta") == (1, 0)


class TestIsPluginVersionCompatible:
    def test_compatible_when_equal(self):
        assert is_plugin_version_compatible("v1.0.0", "v1.0.0")

    def test_compatible_when_newer(self):
        assert is_plugin_version_compatible("v1.1.0", "v1.0.0")

    def test_incompatible_when_older(self):
        assert not is_plugin_version_compatible("v1.0.0", "v1.1.0")

    def test_compatible_patch_version(self):
        assert is_plugin_version_compatible("v1.0.1", "v1.0.0")

    def test_incompatible_patch_version(self):
        assert not is_plugin_version_compatible("v1.0.0", "v1.0.1")

    def test_compatible_major_version(self):
        assert is_plugin_version_compatible("v2.0.0", "v1.0.0")

    def test_incompatible_major_version(self):
        assert not is_plugin_version_compatible("v1.0.0", "v2.0.0")

    def test_empty_min_version(self):
        assert is_plugin_version_compatible("v1.0.0", "")

    def test_dev_version_always_compatible(self):
        assert is_plugin_version_compatible("dev", "v99.0.0")

    def test_different_length_versions_padded(self):
        assert is_plugin_version_compatible("v1.0.0", "v1.0")

    def test_different_length_versions_incompatible(self):
        assert not is_plugin_version_compatible("v1.0", "v1.0.1")

    def test_prerelease_ignored_in_comparison(self):
        assert is_plugin_version_compatible("v1.0.0-beta", "v1.0.0")

    def test_without_v_prefix(self):
        assert is_plugin_version_compatible("1.2.3", "1.2.0")
