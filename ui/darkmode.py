from qgis.PyQt.QtWidgets import QMessageBox

from ..imgs import DARK_MODE_ICON, MAIN_ICON


def _is_in_darkmode(threshold=383):
    """detect the Qt in Darkmode or not

    This function has a dependancy on PyQt, QMessageBox.
    Although Qt has no API to detect running in Darkmode or not,
    it is able to get RGB value of widgets, including UI parts of them.
    This function detect Darkmode by evaluating a sum of RGB value of the widget with threshold.

    Note:
        Implementation based on MapTiler QGIS Plugin
        https://github.com/maptiler/qgis-maptiler-plugin/blob/719957adcddf12a1251f03b73f4ecebc393faee0/utils.py
        Licensed under GPL-2.0

    Args:
        threshold (int, optional): a sum of RGB value (each 0-255, sum 0-765). Default to 383, is just median.
    Returns:
        bool: True means in Darkmode, False in not.
    """
    # generate empty QMessageBox to detect
    # generated widgets has default color palette in the OS
    empty_mbox = QMessageBox()

    # get a background color of the widget
    red = empty_mbox.palette().window().color().red()
    green = empty_mbox.palette().window().color().green()
    blue = empty_mbox.palette().window().color().blue()

    sum_rgb_value = red + green + blue
    return sum_rgb_value < threshold


def get_adaptive_icon():
    """Get icon adapted to OS setting"""
    print("Detecting darkmode:", _is_in_darkmode())
    return DARK_MODE_ICON if _is_in_darkmode() else MAIN_ICON
