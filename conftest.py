"""pytest conftest: make plugin importable as 'plugin_dir' package."""

import sys
from pathlib import Path

# The plugin root is this directory. For relative imports like
# `from ...kumoy` (in processing/upload_vector/algorithm.py) to work,
# the plugin root must be importable as a package — not as top-level.
#
# We create a symlink so the plugin can always be imported as 'plugin_dir'
# regardless of the actual directory name.
_plugin_root = Path(__file__).resolve().parent
_symlink = _plugin_root.parent / "plugin_dir"

if not _symlink.exists():
    _symlink.symlink_to(_plugin_root)

if str(_symlink.parent) not in sys.path:
    sys.path.insert(0, str(_symlink.parent))

# Remove the plugin root from sys.path so that plugin subpackages
# (e.g. 'processing/') don't shadow QGIS built-in modules.
# Plugin modules must be imported via 'plugin_dir.xxx' instead.
_plugin_root_str = str(_plugin_root)
sys.path[:] = [p for p in sys.path if p not in (_plugin_root_str, "")]
