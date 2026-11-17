"""Stand-ins for modules the rewrite removed but other areas still import.

Temporary: the maps area is rewritten in parallel with the others, whose
files in this branch still import pre-rewrite modules. Each shim is installed
only while the module is missing and the real code still needs it. Delete
this file once the areas are merged.
"""

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent


def install() -> None:
    from plugin_dir.kumoy import settings_manager

    def add(name: str, **attrs) -> None:
        # Checked on disk: find_spec() would import the broken parent package
        relative = name.split(".", 1)[1].replace(".", "/")
        if name in sys.modules or (_ROOT / f"{relative}.py").exists():
            return
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        sys.modules[name] = module

    # kumoy/local_cache/vector.py (area A)
    add(
        "plugin_dir.kumoy.local_cache.settings",
        delete_last_updated=lambda *_: None,
        get_last_updated=lambda *_: None,
        store_last_updated=lambda *_: None,
    )

    # processing/base.py (area E)
    def get_token():
        from plugin_dir.kumoy import session

        return session.get_token()

    add("plugin_dir.kumoy.get_token", get_token=get_token)
    if not hasattr(settings_manager, "get_settings"):
        settings_manager.get_settings = lambda: types.SimpleNamespace(
            selected_project_id=settings_manager.selected_project_id()
        )
