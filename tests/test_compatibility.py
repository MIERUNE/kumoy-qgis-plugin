import importlib.util
import unittest
from pathlib import Path

# Load plugin_version module without importing the heavy QGIS package tree.
MODULE_PATH = Path(__file__).resolve().parent.parent / "plugin_version.py"
spec = importlib.util.spec_from_file_location("plugin_version_module", MODULE_PATH)
plugin_version_module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(plugin_version_module)
_parse_version = plugin_version_module._parse_version
is_plugin_version_compatible = plugin_version_module.is_plugin_version_compatible


class TestParseVersion(unittest.TestCase):
    def test_simple_version(self):
        self.assertEqual(_parse_version("1.2.3"), (1, 2, 3))

    def test_v_prefix(self):
        self.assertEqual(_parse_version("v1.0.0"), (1, 0, 0))

    def test_prerelease_hyphen(self):
        self.assertEqual(_parse_version("v1.0.0-beta"), (1, 0, 0))

    def test_prerelease_dot(self):
        self.assertEqual(_parse_version("v1.0.alpha"), (1, 0))

    def test_two_segments(self):
        self.assertEqual(_parse_version("v1.0"), (1, 0))

    def test_two_segments_with_prerelease(self):
        self.assertEqual(_parse_version("v1.0-beta"), (1, 0))


class TestIsPluginVersionCompatible(unittest.TestCase):
    def test_compatible_when_equal(self):
        self.assertTrue(is_plugin_version_compatible("v1.0.0", "v1.0.0"))

    def test_compatible_when_newer(self):
        self.assertTrue(is_plugin_version_compatible("v1.1.0", "v1.0.0"))

    def test_incompatible_when_older(self):
        self.assertFalse(is_plugin_version_compatible("v1.0.0", "v1.1.0"))

    def test_compatible_patch_version(self):
        self.assertTrue(is_plugin_version_compatible("v1.0.1", "v1.0.0"))

    def test_incompatible_patch_version(self):
        self.assertFalse(is_plugin_version_compatible("v1.0.0", "v1.0.1"))

    def test_compatible_major_version(self):
        self.assertTrue(is_plugin_version_compatible("v2.0.0", "v1.0.0"))

    def test_incompatible_major_version(self):
        self.assertFalse(is_plugin_version_compatible("v1.0.0", "v2.0.0"))

    def test_empty_min_version(self):
        self.assertTrue(is_plugin_version_compatible("v1.0.0", ""))

    def test_none_min_version(self):
        self.assertTrue(is_plugin_version_compatible("v1.0.0", None))

    def test_dev_version_always_compatible(self):
        self.assertTrue(is_plugin_version_compatible("dev", "v99.0.0"))

    def test_different_length_versions_padded(self):
        self.assertTrue(is_plugin_version_compatible("v1.0.0", "v1.0"))

    def test_different_length_versions_incompatible(self):
        self.assertFalse(is_plugin_version_compatible("v1.0", "v1.0.1"))

    def test_prerelease_ignored_in_comparison(self):
        self.assertTrue(is_plugin_version_compatible("v1.0.0-beta", "v1.0.0"))

    def test_without_v_prefix(self):
        self.assertTrue(is_plugin_version_compatible("1.2.3", "1.2.0"))


if __name__ == "__main__":
    unittest.main()
