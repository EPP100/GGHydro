
import threading
import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, QSettings
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QGridLayout, QHBoxLayout, QGroupBox,
    QLabel, QLineEdit, QComboBox, QDoubleSpinBox, QPushButton,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox
)

from nidaqmx.system import System
from nidaqmx.constants import LoggingOperation

from .models import MicConfig, RecordMeta
from .recorder_worker import RecorderWorker
from .ni_recorder import SAMPLE_RATE
from .utils import sanitize_token, build_tdms_filename, ensure_dir, increment_path


class MainWindow(QMainWindow):
    def __init__(self, project_dir: Path):
        super().__init__()
        self.setWindowTitle("Machine Audio Sampler (NI-DAQmx + TDMS)")
        self.setMinimumWidth(980)

        # Project folder context
        self.project_dir = Path(project_dir).resolve()
        self.project_name = self.project_dir.name  # folder name defines project name
        self.project_settings_path = self.project_dir / "settings.ini"

        # recordings/<UNIT>/...
        self.recordings_root = self.project_dir / "recordings"
        ensure_dir(self.recordings_root)

        # Per-project settings stored in project folder
        self.settings = QSettings(str(self.project_settings_path), QSettings.IniFormat)

        self.stop_event = threading.Event()
        self.thread = None
        self.worker = None
        self.started_at = None

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setSpacing(10)

        # Project folder + name
        lbl_project_folder = QLabel(f"Project Folder: {self.project_dir}")
        lbl_project_folder.setStyleSheet("color: #aaa;")
        main.addWidget(lbl_project_folder)

        lbl_project_name = QLabel(f"Project: {self.project_name}")
        lbl_project_name.setStyleSheet("font-size: 16px; font-weight: 600;")
        main.addWidget(lbl_project_name)

        # -------------------------
        # Microphone (IEPE)
        # -------------------------
        gb_mic = QGroupBox("Microphone (IEPE)")
        gl_mic = QGridLayout(gb_mic)

        gl_mic.addWidget(QLabel("NI Device:"), 0, 0)
        self.cb_device = QComboBox()
        gl_mic.addWidget(self.cb_device, 0, 1)

        gl_mic.addWidget(QLabel("Channel:"), 1, 0)
        self.cb_channel = QComboBox()
        gl_mic.addWidget(self.cb_channel, 1, 1)

        gl_mic.addWidget(QLabel("Sensitivity:"), 2, 0)
        self.sb_sens = QDoubleSpinBox()
        self.sb_sens.setRange(0.01, 10000.0)
        self.sb_sens.setDecimals(2)
        self.sb_sens.setSuffix(" mV/Pa")
        self.sb_sens.setValue(float(self.settings.value("sens", 45.60)))
        gl_mic.addWidget(self.sb_sens, 2, 1)

        gl_mic.addWidget(QLabel("Microphone ID:"), 3, 0)
        self.le_mic_id = QLineEdit(self.settings.value("mic_id", "VHM-COM0266"))
        gl_mic.addWidget(self.le_mic_id, 3, 1)

        gl_mic.addWidget(QLabel("Sampling Rate:"), 4, 0)
        self.lbl_fs = QLabel(f"{SAMPLE_RATE} Hz")
        gl_mic.addWidget(self.lbl_fs, 4, 1)

        main.addWidget(gb_mic)

        # -------------------------
        # Recording
        # -------------------------
        gb_rec = QGroupBox("Recording")
        gl_rec = QGridLayout(gb_rec)

        # ✅ Unit number moved here (from microphone section)
        gl_rec.addWidget(QLabel("Unit Number:"), 0, 0)
        self.le_unit = QLineEdit(self.settings.value("unit", "U1"))
        gl_rec.addWidget(self.le_unit, 0, 1)

        gl_rec.addWidget(QLabel("Unit State:"), 1, 0)
        self.le_state = QLineEdit(self.settings.value("last_state", ""))
        self.le_state.setPlaceholderText("e.g. Idle / SNL / Full Load / ...")
        gl_rec.addWidget(self.le_state, 1, 1)

        gl_rec.addWidget(QLabel("Location:"), 2, 0)
        self.le_location = QLineEdit(self.settings.value("last_location", ""))
        self.le_location.setPlaceholderText("e.g. G1 / T1 / ...")
        gl_rec.addWidget(self.le_location, 2, 1)

        gl_rec.addWidget(QLabel("Duration:"), 3, 0)
        self.sb_duration = QDoubleSpinBox()
        self.sb_duration.setRange(0.1, 600.0)
        self.sb_duration.setDecimals(1)
        self.sb_duration.setSuffix(" s")
        self.sb_duration.setValue(float(self.settings.value("duration", 1.0)))
        gl_rec.addWidget(self.sb_duration, 3, 1)

        status_row = QHBoxLayout()
        self.lbl_dot = QLabel("●")
        self.lbl_dot.setStyleSheet("color: #777;")
        self.lbl_status = QLabel("Idle")
        self.lbl_elapsed = QLabel("Elapsed: 0.0 s")
        self.lbl_elapsed.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        status_row.addWidget(self.lbl_dot)
        status_row.addWidget(self.lbl_status)
        status_row.addStretch(1)
        status_row.addWidget(self.lbl_elapsed)
        gl_rec.addLayout(status_row, 4, 0, 1, 2)

        self.pb = QProgressBar()
        self.pb.setRange(0, 1000)
        self.pb.setValue(0)
        gl_rec.addWidget(self.pb, 5, 0, 1, 2)

        btn_row = QHBoxLayout()
        self.btn_start = QPushButton("Start")
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        gl_rec.addLayout(btn_row, 6, 0, 1, 2)

        main.addWidget(gb_rec)

        # -------------------------
        # Table Log
        # -------------------------
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["TDMS File", "Duration (s)", "Unit State", "Location", "Timestamp"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 5):
            self.table.horizontalHeader().setSectionResizeMode(c, QHeaderView.ResizeToContents)
        main.addWidget(self.table)

        # -------------------------
        # Signals / Timers
        # -------------------------
        self.btn_start.clicked.connect(self.start_recording)
        self.btn_stop.clicked.connect(self.stop_recording)

        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(50)
        self.ui_timer.timeout.connect(self._tick)

        self.refresh_devices()
        self.cb_device.currentTextChanged.connect(self.refresh_channels)

    # -------------------------
    # Device discovery
    # -------------------------
    def refresh_devices(self):
        self.cb_device.clear()
        self.cb_channel.clear()

        try:
            system = System.local()
            devices = list(system.devices)
            if not devices:
                self.cb_device.addItem("(no NI devices found)")
                self.cb_channel.addItem("(none)")
                return

            for d in devices:
                self.cb_device.addItem(d.name)

            self.refresh_channels(self.cb_device.currentText())

            # restore last used channel if present
            saved_channel = self.settings.value("ni_channel", "")
            if saved_channel:
                idx = self.cb_channel.findText(saved_channel)
                if idx >= 0:
                    self.cb_channel.setCurrentIndex(idx)

        except Exception as e:
            self.cb_device.addItem(f"(error: {e})")
            self.cb_channel.addItem("(none)")

    def refresh_channels(self, dev_name: str):
        self.cb_channel.clear()
        if not dev_name or dev_name.startswith("("):
            self.cb_channel.addItem("(none)")
            return

        try:
            system = System.local()
            dev = system.devices[dev_name]
            for ch in dev.ai_physical_chans:
                self.cb_channel.addItem(ch.name)
        except Exception as e:
            self.cb_channel.addItem(f"(error: {e})")

    # -------------------------
    # Recording actions
    # -------------------------
    def start_recording(self):
        unit = self.le_unit.text().strip()
        state = self.le_state.text().strip()
        loc = self.le_location.text().strip()
        duration = float(self.sb_duration.value())

        if not unit:
            return self._error("Missing info", "Unit Number is required.")
        if not state or not loc:
            return self._error("Missing info", "Unit State and Location are required.")

        ch = self.cb_channel.currentText().strip()
        if not ch or ch.startswith("("):
            return self._error("Missing info", "Select a valid NI channel (e.g., cDAQ1Mod1/ai0).")

        # Save per-project settings into <project folder>/settings.ini
        self.settings.setValue("unit", unit)
        self.settings.setValue("sens", float(self.sb_sens.value()))
        self.settings.setValue("mic_id", self.le_mic_id.text().strip())
        self.settings.setValue("duration", duration)
        self.settings.setValue("last_state", state)
        self.settings.setValue("last_location", loc)
        self.settings.setValue("ni_channel", ch)

        # Tokens for file naming
        project_tok = sanitize_token(self.project_name)
        unit_tok = sanitize_token(unit)
        state_tok = sanitize_token(state)
        loc_tok = sanitize_token(loc)

        # Unit creates subfolder for recordings
        out_dir = self.recordings_root / unit_tok
        ensure_dir(out_dir)

        filename = build_tdms_filename(project_tok, unit_tok, state_tok, loc_tok)
        tdms_path = out_dir / filename

        # Ask if exists: Increment / Overwrite / Cancel
        logging_operation = LoggingOperation.CREATE_OR_REPLACE
        if tdms_path.exists():
            choice = self._ask_file_exists(tdms_path.name)
            if choice == "cancel":
                return
            elif choice == "increment":
                tdms_path = increment_path(tdms_path)
            elif choice == "overwrite":
                pass

        mic_cfg = MicConfig(
            physical_channel=ch,
            sensitivity_mV_per_Pa=float(self.sb_sens.value()),
            microphone_id=self.le_mic_id.text().strip(),
        )
        meta = RecordMeta(unit=unit, unit_state=state, location=loc, duration_s=duration)

        self.stop_event.clear()

        # UI state
        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self._set_status("Recording")
        self.started_at = time.time()
        self.pb.setValue(0)
        self.lbl_elapsed.setText("Elapsed: 0.0 s")
        self.ui_timer.start()

        # Worker thread
        self.thread = QThread()
        self.worker = RecorderWorker(
            project_name=self.project_name,
            mic_cfg=mic_cfg,
            record_meta=meta,
            stop_event=self.stop_event,
            tdms_path=tdms_path,
            logging_operation=logging_operation,
        )
        self.worker.moveToThread(self.thread)

        self.thread.started.connect(self.worker.run)
        self.worker.status.connect(self._set_status)
        self.worker.finished.connect(self._on_finished)
        self.worker.error.connect(self._on_error)

        self.worker.finished.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)

        self.worker.error.connect(self.thread.quit)
        self.worker.error.connect(self.worker.deleteLater)

        self.thread.start()

    def stop_recording(self):
        self.stop_event.set()
        self._set_status("Stopping...")

    def _ask_file_exists(self, filename: str) -> str:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Warning)
        msg.setWindowTitle("File already exists")
        msg.setText(f"The file already exists:\n\n{filename}\n\nWhat do you want to do?")

        btn_increment = msg.addButton("Increment", QMessageBox.AcceptRole)
        btn_overwrite = msg.addButton("Overwrite", QMessageBox.DestructiveRole)
        btn_cancel = msg.addButton("Cancel", QMessageBox.RejectRole)

        msg.setDefaultButton(btn_increment)
        msg.exec()

        clicked = msg.clickedButton()
        if clicked == btn_increment:
            return "increment"
        if clicked == btn_overwrite:
            return "overwrite"
        return "cancel"

    def _on_finished(self, result):
        self.ui_timer.stop()
        self.started_at = None
        self.pb.setValue(1000)
        self._set_status("Idle")

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(result.tdms_path))
        self.table.setItem(row, 1, QTableWidgetItem(f"{result.duration_s:.2f}"))
        self.table.setItem(row, 2, QTableWidgetItem(result.unit_state))
        self.table.setItem(row, 3, QTableWidgetItem(result.location))
        self.table.setItem(row, 4, QTableWidgetItem(result.timestamp_iso))
        self.table.scrollToBottom()

    def _on_error(self, msg: str):
        self.ui_timer.stop()
        self.started_at = None
        self.pb.setValue(0)
        self._set_status("Idle")

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)

        self._error("Recording failed", msg)

    def _tick(self):
        if self.started_at is None:
            return
        elapsed = time.time() - self.started_at
        dur = float(self.sb_duration.value())
        self.lbl_elapsed.setText(f"Elapsed: {elapsed:.1f} s")
        if dur > 0:
            self.pb.setValue(int(min(1.0, elapsed / dur) * 1000))

    def _set_status(self, text: str):
        self.lbl_status.setText(text)
        t = text.lower()
        if t.startswith("record"):
            self.lbl_dot.setStyleSheet("color: #3fb950;")
        elif t.startswith("stopp"):
            self.lbl_dot.setStyleSheet("color: #d29922;")
        else:
            self.lbl_dot.setStyleSheet("color: #777;")

    def _error(self, title: str, msg: str):
        QMessageBox.critical(self, title, msg)
