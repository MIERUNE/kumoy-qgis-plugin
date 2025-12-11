from ..imgs import MAIN_ICON, DARK_MODE_ICON
from ..ui.browser.utils import is_in_darkmode


def get_adaptive_icon():
    """Get icon adapted to OS setting"""

    return DARK_MODE_ICON if is_in_darkmode() else MAIN_ICON
