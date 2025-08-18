"""
Dialog Utilities
"""
import os

from qgis.PyQt.QtWidgets import QDialog, QPushButton
from qgis.PyQt.QtGui import QPainter, QImage, QColor
from qgis.PyQt.QtSvg import QSvgRenderer
from qgis.PyQt.QtCore import Qt
from typing import Optional

STRATO_STYLESHEET = """
QDialog {
    background-color: #F9F9F9;
    color: black;
}
"""

class ButtonColors:
    """Button color definitions for the dialog"""
    # Apply Button Colors
    APPLY = "5165FF"
    APPLY_HOVER = "4158B8"
    APPLY_PRESSED = "314A8A"

    # Cancel Button Colors
    CANCEL = "D12447"
    CANCEL_HOVER = "B31D3A"
    CANCEL_PRESSED = "9C162B"

class DialogUtils:
    @staticmethod
    def apply_stylesheet(dialog: QDialog):
        dialog.setStyleSheet(STRATO_STYLESHEET)

    @staticmethod
    def get_svg_as_image(icon: str, width: int, height: int,
                         background_color: Optional[QColor] = None,
                         device_pixel_ratio: float = 1) -> QImage:
        
        plugin_dir = os.path.dirname(os.path.dirname(__file__))
        path = os.path.join(plugin_dir, "imgs", f"{icon}.svg")

        if not os.path.exists(path):
            return QImage()

        renderer = QSvgRenderer(path)
        image = QImage(int(width * device_pixel_ratio),
                       int(height * device_pixel_ratio),
                       QImage.Format_ARGB32)
        image.setDevicePixelRatio(device_pixel_ratio)
        if not background_color:
            image.fill(Qt.transparent)
        else:
            image.fill(background_color)

        painter = QPainter(image)
        painter.scale(1 / device_pixel_ratio,
                      1 / device_pixel_ratio)
        renderer.render(painter)
        painter.end()

        return image

    @staticmethod
    def apply_button_style(button: QPushButton, button_type: str):
        """Apply the style to a button based on its type"""
        color_map = {
            "apply": (ButtonColors.APPLY, ButtonColors.APPLY_HOVER, ButtonColors.APPLY_PRESSED),
            "cancel": (ButtonColors.CANCEL, ButtonColors.CANCEL_HOVER, ButtonColors.CANCEL_PRESSED),
        }

        if button_type not in color_map:
            return    

        colors = color_map[button_type]

        button.setStyleSheet(f"""
            QPushButton {{
                background-color: #{colors[0]};
                color: #FFFFFF;
                border: none;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: #{colors[1]};
            }}
            QPushButton:pressed {{
                background-color: #{colors[2]};
            }}
        """)
