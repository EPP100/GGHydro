from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QFileDialog, QMessageBox, QLineEdit, QGroupBox
)

from .main_window import MainWindow


class ProjectSelectorWindow(QWidget):
    """
    Startup window:
      - Select an existing project folder
      - Create a new project folder
      - Shows recent projects (stored globally)
    """
    ORG = "MachineAudioSampler"
    APP = "Launcher"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Select Project Folder")
        self.setMinimumWidth(720)

        self.global_settings = QSettings(self.ORG, self.APP)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        title = QLabel("Choose a Project Folder")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        # --- Recent Projects
        gb_recent = QGroupBox("Recent Projects")
        recent_layout = QVBoxLayout(gb_recent)
        self.list_recent = QListWidget()
        recent_layout.addWidget(self.list_recent)

        btn_row_recent = QHBoxLayout()
        self.btn_open_recent = QPushButton("Open Selected")
        self.btn_remove_recent = QPushButton("Remove from List")
        btn_row_recent.addWidget(self.btn_open_recent)
        btn_row_recent.addWidget(self.btn_remove_recent)
        recent_layout.addLayout(btn_row_recent)

        layout.addWidget(gb_recent)

        # --- Browse / Create
        gb_actions = QGroupBox("Open or Create")
        actions_layout = QVBoxLayout(gb_actions)

        browse_row = QHBoxLayout()
        self.le_folder = QLineEdit()
        self.le_folder.setPlaceholderText("Project folder path…")
        self.btn_browse = QPushButton("Browse…")
        browse_row.addWidget(self.le_folder)
        browse_row.addWidget(self.btn_browse)
        actions_layout.addLayout(browse_row)

        btn_row = QHBoxLayout()
        self.btn_open = QPushButton("Open Folder")
        self.btn_new = QPushButton("Create New Project Folder…")
        btn_row.addWidget(self.btn_open)
        btn_row.addWidget(self.btn_new)
        actions_layout.addLayout(btn_row)

        layout.addWidget(gb_actions)

        # Wiring
        self.btn_browse.clicked.connect(self.browse_folder)
        self.btn_open.clicked.connect(self.open_typed_folder)
        self.btn_new.clicked.connect(self.create_new_project_folder)
        self.btn_open_recent.clicked.connect(self.open_selected_recent)
        self.btn_remove_recent.clicked.connect(self.remove_selected_recent)
        self.list_recent.itemDoubleClicked.connect(lambda _: self.open_selected_recent())

        self.load_recent()

    # -------------------------
    # Recent projects persistence
    # -------------------------
    def load_recent(self):
        self.list_recent.clear()
        recents = self.global_settings.value("recent_projects", [])
        if isinstance(recents, str):
            recents = [recents]
        if not recents:
            self.list_recent.addItem("(none)")
            self.list_recent.setEnabled(False)
        else:
            self.list_recent.setEnabled(True)
            for p in recents:
                self.list_recent.addItem(p)

    def save_recent(self, paths: list[str]):
        # Keep unique, preserve order
        unique = []
        for p in paths:
            if p not in unique:
                unique.append(p)
        self.global_settings.setValue("recent_projects", unique)

    def add_recent(self, folder: Path):
        folder = folder.resolve()
        recents = self.global_settings.value("recent_projects", [])
        if isinstance(recents, str):
            recents = [recents]
        recents = [str(folder)] + [p for p in recents if p != str(folder)]
        self.save_recent(recents[:15])
        self.load_recent()

    def remove_selected_recent(self):
        item = self.list_recent.currentItem()
        if not item:
            return
        text = item.text()
        if text.startswith("("):
            return

        recents = self.global_settings.value("recent_projects", [])
        if isinstance(recents, str):
            recents = [recents]
        recents = [p for p in recents if p != text]
        self.save_recent(recents)
        self.load_recent()

    # -------------------------
    # Actions
    # -------------------------
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Project Folder")
        if folder:
            self.le_folder.setText(folder)

    def open_typed_folder(self):
        text = self.le_folder.text().strip()
        if not text:
            QMessageBox.warning(self, "Missing path", "Please choose or type a project folder path.")
            return

        folder = Path(text)
        self.open_project(folder)

    def open_selected_recent(self):
        item = self.list_recent.currentItem()
        if not item:
            return
        text = item.text()
        if text.startswith("("):
            return

        folder = Path(text)
        self.open_project(folder)

    def create_new_project_folder(self):
        base = QFileDialog.getExistingDirectory(self, "Choose a parent folder for the new project")
        if not base:
            return

        # Ask for project folder name using a small dialog
        name, ok = self._ask_text("New Project Folder", "Enter new project folder name:")
        if not ok or not name.strip():
            return

        folder = Path(base) / name.strip()
        try:
            folder.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            QMessageBox.warning(self, "Already exists", "That folder already exists. Choose a different name.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not create folder:\n{e}")
            return

        self.open_project(folder)

    def open_project(self, folder: Path):
        try:
            folder = folder.resolve()
            folder.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot open/create folder:\n{e}")
            return

        # Add to recent
        self.add_recent(folder)

        # Launch Recorder window with project folder context
        self.recorder = MainWindow(project_dir=folder)
        self.recorder.show()

        # Close selector (or hide)
        self.close()

    def _ask_text(self, title: str, label: str):
        from PySide6.QtWidgets import QDialog, QDialogButtonBox

        d = QDialog(self)
        d.setWindowTitle(title)
        v = QVBoxLayout(d)
        v.addWidget(QLabel(label))
        le = QLineEdit()
        v.addWidget(le)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        v.addWidget(bb)

        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)

        ok = d.exec() == QDialog.Accepted
        return le.text(), ok