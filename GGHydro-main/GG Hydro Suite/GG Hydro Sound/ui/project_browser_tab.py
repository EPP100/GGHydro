import os
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QListWidget,
    QPushButton,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
)
from config import default_config, save_config

PROJECTS_ROOT = "projects"


class ProjectBrowserTab(QWidget):
    def __init__(self, open_project_cb):
        super().__init__()
        self.open_project_cb = open_project_cb

        self.list = QListWidget()
        self.refresh_btn = QPushButton("Refresh")
        self.new_btn = QPushButton("New Project")

        btns = QHBoxLayout()
        btns.addWidget(self.refresh_btn)
        btns.addWidget(self.new_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        layout.addLayout(btns)

        self.refresh_btn.clicked.connect(self.refresh)
        self.new_btn.clicked.connect(self.new_project)

        # --- Double-click opens project ---
        self.list.itemDoubleClicked.connect(self.open_item)

        os.makedirs(PROJECTS_ROOT, exist_ok=True)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for d in os.listdir(PROJECTS_ROOT):
            path = os.path.join(PROJECTS_ROOT, d)
            if os.path.isdir(path):
                self.list.addItem(d)

    def new_project(self):
        name, ok = QInputDialog.getText(self, "New Project", "Project name:")
        if not ok or not name:
            return

        path = os.path.join(PROJECTS_ROOT, name)
        if os.path.exists(path):
            QMessageBox.warning(self, "Error", "Project already exists")
            return

        os.makedirs(os.path.join(path, "recordings"), exist_ok=True)
        save_config(os.path.join(path, "project.json"), default_config())
        self.refresh()

    def open_item(self, item):
        if item:
            self.open_project_cb(item.text())

    def open_selected(self):
        item = self.list.currentItem()
        if item:
            self.open_project_cb(item.text())
