"""Non-secret plugin settings in QSettings. The session token is in session.py."""

from typing import Optional

from qgis.PyQt.QtCore import QSettings

GROUP = "Kumoy"


def _key(name: str) -> str:
    return f"{GROUP}/{name}"


def get(name: str, default: str = "") -> str:
    value = QSettings().value(_key(name), default)
    return "" if value is None else str(value)


def store(name: str, value: Optional[str]) -> None:
    if value is None:
        QSettings().remove(_key(name))
    else:
        QSettings().setValue(_key(name), value)


def selected_organization_id() -> str:
    return get("selected_organization_id")


def selected_project_id() -> str:
    return get("selected_project_id")


def select_project(organization_id: str, project_id: str) -> None:
    store("selected_organization_id", organization_id)
    store("selected_project_id", project_id)


def clear_selection() -> None:
    select_project("", "")


def custom_server_url() -> str:
    """The custom server URL, or "" when the default server is used."""
    if get("use_custom_server", "false") != "true":
        return ""
    return get("custom_server_url").strip().rstrip("/")


def set_custom_server(enabled: bool, url: str) -> None:
    store("use_custom_server", "true" if enabled else "false")
    store("custom_server_url", url.strip())


def reset() -> None:
    """Remove every Kumoy setting, including cache bookkeeping."""
    settings = QSettings()
    settings.beginGroup(GROUP)
    settings.remove("")
    settings.endGroup()
