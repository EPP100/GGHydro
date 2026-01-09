from PySide6.QtWidgets import *
from PySide6.QtGui import QIcon
from PySide6.QtCore import Signal
from nidaqmx.system import System
from widgets.led import LedIndicator
from daq_worker import DAQWorker
import re
from datetime import datetime
from nptdms import TdmsFile, TdmsWriter, RootObject, GroupObject, ChannelObject


def safe(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s.strip())


def validate_mic(cfg):
    mic = cfg["microphone"]
    sys = System.local()
    if mic.get("device") not in [d.name for d in sys.devices]:
        return False
    dev = sys.devices[mic["device"]]
    return mic.get("channel") in [c.name for c in dev.ai_physical_chans]


class RecordingTab(QWidget):
    recording_started = Signal()
    recording_finished = Signal()

    def __init__(self, cfg, project_path):
        super().__init__()
        self.cfg = cfg
        self.project_path = project_path
        self.worker = None

        self.duration = QSpinBox()
        self.duration.setRange(1, 120)
        self.duration.setSuffix(" s")

        self.unit_state = QLineEdit()
        self.location = QLineEdit()

        self.unit_state.setPlaceholderText("e.g. Idle / SNL / Full Load / ...")
        self.location.setPlaceholderText("e.g. G1 / T1 / ...")

        self.start = QPushButton(" Start")
        self.start.setIcon(QIcon.fromTheme("media-record"))

        self.stop = QPushButton(" Stop")
        self.stop.setIcon(QIcon.fromTheme("media-playback-stop"))
        self.stop.setEnabled(False)

        self.led = LedIndicator()
        self.state = QLabel("Idle")
        self.elapsed = QLabel("Elapsed: 0.0 s")

        self.progress = QProgressBar()

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["File", "Duration (s)", "Unit State", "Location", "Timestamp"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        # Layout
        form = QFormLayout()
        form.addRow("Unit State:", self.unit_state)
        form.addRow("Location:", self.location)
        form.addRow("Duration:", self.duration)

        box = QGroupBox("Recording")
        box.setLayout(form)

        led_row = QHBoxLayout()
        led_row.addWidget(self.led)
        led_row.addWidget(self.state)
        led_row.addSpacing(20)
        led_row.addWidget(self.elapsed)
        led_row.addStretch()

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addLayout(led_row)
        layout.addWidget(self.start)
        layout.addWidget(self.stop)
        layout.addWidget(self.progress)
        layout.addWidget(self.table)
        layout.addStretch()
        layout.setContentsMargins(20, 20, 20, 20)

        self.start.clicked.connect(self.start_rec)
        self.stop.clicked.connect(self.stop_rec)

        self.unit_state.textEdited.connect(self.update_start_button)
        self.location.textEdited.connect(self.update_start_button)

        self.update_start_button()

    def update_start_button(self):
        valid_mic = validate_mic(self.cfg)
        meta_ok = bool(self.unit_state.text().strip()) and bool(
            self.location.text().strip()
        )

        enabled = valid_mic and meta_ok and not self.worker
        self.start.setEnabled(enabled)

        if enabled:
            self.led.set_armed()
            self.state.setText("Armed")
        else:
            self.led.set_off()
            self.state.setText("Idle")

    def start_rec(self):
        filename = self.build_filename()

        self.worker = DAQWorker(
            project_path=self.project_path,
            cfg=self.cfg,
            duration=self.duration.value(),
            filename=filename,
        )

        self.worker.elapsed_signal.connect(self.update_progress)
        self.worker.finished_signal.connect(self.finish)
        self.worker.start()

        self.start.setEnabled(False)
        self.stop.setEnabled(True)

        self.led.set_recording()
        self.state.setText("Recording")

        self.recording_started.emit()

    def stop_rec(self):
        if self.worker:
            self.worker.stop()

    def update_progress(self, t):
        self.elapsed.setText(f"Elapsed: {t:.1f} s")
        self.progress.setValue(int(100 * t / self.duration.value()))

    def finish(self, filename):
        print(filename["filename"])

        file_path = (
            "C:\\Users\\Gabriel\\Documents\\GG Hydro Suite\\GG Hydro Sound\\"
            + self.project_path
            + "\\recordings\\"
            + filename["filename"]
        )

        # --- 1. Define new metadata ---

        # Example: New file-level properties
        new_file_properties = {
            "New_Author": "Jane Doe",
            "Project_ID": 12345,
        }

        # Example: Properties for a specific existing group and channel
        group_name = "DAQ"
        channel_name = "Sound"
        new_channel_properties = {
            "Unit_String": "Volts",  # Updates default properties
            "Sensor_Serial": "SN12345",  # Adds a custom property
        }

        with TdmsWriter(file_path, mode="a") as writer:
            # Append new file-level properties via a RootObject
            # Note: This updates/adds properties to the root object
            writer.write_segment([RootObject(properties=new_file_properties)])

            # Append new channel-level properties via a ChannelObject
            # This also implicitly includes the parent group name
            # writer.write_segment(
            #     [
            #         ChannelObject(
            #             group_name, channel_name, properties=new_channel_properties
            #         )
            #     ]
            # )

        print(f"Metadata appended to {file_path}")

        # self.cfg.setdefault("recordings", []).append(rec)
        self.worker = None
        self.stop.setEnabled(False)
        self.progress.setValue(100)
        self.recording_finished.emit()
        self.update_start_button()

    def get_data(self):
        pass

    def build_filename(self):
        today = datetime.now().strftime("%Y-%m-%d")

        project = safe(self.cfg.get("project_name", "PROJECT"))
        unit = safe(self.cfg.get("unit_number", "UNIT"))
        state = safe(self.unit_state.text())
        location = safe(self.location.text())

        return f"{today} - {project} - {unit} - {state} - {location}.tdms"
