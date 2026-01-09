import os, sys
import os
from PySide6.QtWidgets import (
    QMainWindow,
    QTabWidget,
    QToolBar,
    QPushButton,
    QLabel,
    QApplication,
)
from PySide6.QtGui import QIcon
from config import load_config, save_config
from ui.project_browser_tab import ProjectBrowserTab
from ui.project_tab import ProjectTab
from ui.microphone_tab import MicrophoneTab
from ui.recording_tab import RecordingTab

PROJECTS_ROOT = "projects"


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DAQ Recorder")

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.cfg = None
        self.project_path = None
        self.is_dirty = False

        # --- Save toolbar ---
        self.save_btn = QPushButton()
        self.save_btn.setIcon(QIcon.fromTheme("document-save"))
        self.save_btn.clicked.connect(self.save_project)

        self.dirty_label = QLabel("")
        self.dirty_label.setStyleSheet("color:#E53935;font-weight:bold;")

        tb = QToolBar()
        tb.addWidget(self.save_btn)
        tb.addWidget(self.dirty_label)
        self.addToolBar(tb)

        # --- Project browser ---
        self.browser = ProjectBrowserTab(self.open_project)
        self.tabs.addTab(self.browser, "Projects")

    # -------------------------------------------------

    def mark_dirty(self):
        if not self.is_dirty:
            self.is_dirty = True
            self.dirty_label.setText("⚠ Unsaved changes")
            print("AAAA")

    # -------------------------------------------------

    def save_project(self):
        if not self.cfg:
            return

        self.project_tab.get_data()
        self.mic_tab.get_data()
        self.rec_tab.get_data()

        save_config(os.path.join(self.project_path, "project.json"), self.cfg)
        self.is_dirty = False
        self.dirty_label.setText("")

    # -------------------------------------------------

    def open_project(self, name):
        self.project_path = os.path.join(PROJECTS_ROOT, name)
        self.cfg = load_config(os.path.join(self.project_path, "project.json"))

        while self.tabs.count() > 1:
            self.tabs.removeTab(1)

        self.project_tab = ProjectTab(self.cfg)
        self.mic_tab = MicrophoneTab(self.cfg)
        self.rec_tab = RecordingTab(self.cfg, self.project_path)

        self.project_tab.load()
        self.mic_tab.load()

        self.project_tab.changed.connect(self.mark_dirty)
        self.mic_tab.changed.connect(self.mark_dirty)
        self.mic_tab.changed.connect(self.rec_tab.update_start_button)

        self.rec_tab.recording_started.connect(self.lock_tabs)
        self.rec_tab.recording_finished.connect(self.unlock_tabs)

        self.tabs.addTab(self.project_tab, "Project")
        self.tabs.addTab(self.mic_tab, "Microphone")
        self.tabs.addTab(self.rec_tab, "Recording")

        self.rec_tab.update_start_button()

        self.tabs.setCurrentIndex(1)  # focus Project Settings

    # -------------------------------------------------

    def lock_tabs(self):
        for i in range(self.tabs.count()):
            self.tabs.setTabEnabled(i, False)
        self.tabs.setTabEnabled(self.tabs.indexOf(self.rec_tab), True)

    def unlock_tabs(self):
        for i in range(self.tabs.count()):
            self.tabs.setTabEnabled(i, True)


if __name__ == "__main__":
    os.makedirs(PROJECTS_ROOT, exist_ok=True)
    app = QApplication(sys.argv)
    win = MainWindow()
    win.resize(700, 800)
    win.show()
    sys.exit(app.exec())
