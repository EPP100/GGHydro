from PySide6.QtWidgets import QLabel
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt


class LedIndicator(QLabel):
    def __init__(self, diameter=14):
        super().__init__()
        self.setFixedSize(diameter, diameter)
        self.set_off()

    def set_color(self, color):
        self.setStyleSheet(
            f"border-radius:{self.width()//2}px;"
            f"background-color:{color};"
            f"border:1px solid #444;"
        )

    def set_off(self):
        self.set_color("#555")  # gray

    def set_armed(self):
        self.set_color("#FFA500")  # orange

    def set_recording(self):
        self.set_color("#E53935")  # red
