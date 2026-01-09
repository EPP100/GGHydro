from PySide6.QtWidgets import QWidget, QVBoxLayout, QFormLayout, QLineEdit, QGroupBox
from PySide6.QtCore import Signal


class ProjectTab(QWidget):
    changed = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

        self.name = QLineEdit()
        self.unit = QLineEdit()

        self.name.textEdited.connect(lambda _: self.changed.emit())
        self.unit.textEdited.connect(lambda _: self.changed.emit())

        form = QFormLayout()
        form.addRow("Project Name:", self.name)
        form.addRow("Unit Number:", self.unit)

        box = QGroupBox("Project Information")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addStretch()
        layout.setContentsMargins(20, 20, 20, 20)

    def load(self):
        self.name.setText(self.cfg.get("project_name", ""))
        self.unit.setText(self.cfg.get("unit_number", ""))

    def get_data(self):
        self.cfg["project_name"] = self.name.text()
        self.cfg["unit_number"] = self.unit.text()
