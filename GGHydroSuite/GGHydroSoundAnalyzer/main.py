import sys
import os
import numpy as np
from scipy import signal
from nptdms import TdmsFile

from PyQt6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QPushButton, QLabel, QFileDialog,
    QHBoxLayout, QComboBox, QLineEdit, QMessageBox, QGroupBox
)
from PyQt6.QtCore import Qt

P0 = 20e-6  # Reference sound pressure in Pa (20 µPa)


def design_a_weighting_sos(fs: float):
    """
    Design an A-weighting filter (IEC 61672) using bilinear transform.

    The implementation follows the widely used analog prototype with
    the four A-weighting corner frequencies and the 1 kHz gain alignment.

    Returns: Second-order sections (sos) for stable zero-phase filtering (with filtfilt).
    """
    if fs <= 0:
        raise ValueError("Sampling frequency must be positive.")

    # Corner frequencies in Hz (IEC 61672)
    f1 = 20.598997
    f2 = 107.65265
    f3 = 737.86223
    f4 = 12194.217

    # Gain at 1 kHz to normalize weighting (approximately +1.9997 dB)
    A1000 = 1.9997

    # Build the analog transfer function H(s)
    # NUM = (2*pi*f4)^2 * s^4 * 10^(A1000/20)
    # DEN = (s + 2*pi*f4)^2 * (s + 2*pi*f1)^2 * (s + 2*pi*f3) * (s + 2*pi*f2)
    # plus a quadratic HF term is often expressed as [1, 4*pi*f4, (2*pi*f4)^2]; similar for f1
    pi = np.pi
    NUM = [(2 * pi * f4) ** 2 * (10 ** (A1000 / 20.0)), 0.0, 0.0, 0.0, 0.0]
    DEN = np.polymul(
        [1.0, 4.0 * pi * f4, (2.0 * pi * f4) ** 2],
        np.polymul(
            [1.0, 4.0 * pi * f1, (2.0 * pi * f1) ** 2],
            np.polymul([1.0, 2.0 * pi * f3], [1.0, 2.0 * pi * f2])
        )
    )

    # Bilinear transform to digital filter
    b_z, a_z = signal.bilinear(NUM, DEN, fs=fs)
    sos = signal.tf2sos(b_z, a_z)
    return sos


def compute_la_eq(pressure_pa: np.ndarray, fs: float) -> float:
    """
    Compute LAeq (A-weighted SPL over entire signal).
    pressure_pa: numpy array of pressure in Pascals
    fs: sampling rate in Hz

    Returns LAeq in dB(A).
    """
    if pressure_pa.size == 0:
        raise ValueError("Empty signal.")
    if not np.isfinite(pressure_pa).all():
        pressure_pa = np.nan_to_num(pressure_pa, nan=0.0, posinf=0.0, neginf=0.0)

    # Remove any DC offset to avoid skewing RMS
    x = pressure_pa - np.mean(pressure_pa)

    # Design and apply A-weighting
    sos = design_a_weighting_sos(fs)
    # Zero-phase filtering to avoid phase distortion (requires enough samples)
    x_a = signal.sosfiltfilt(sos, x)

    # RMS of A-weighted pressure
    p_rms_a = np.sqrt(np.mean(x_a ** 2))
    if p_rms_a <= 0:
        # If everything is silence or numeric underflow
        return -np.inf

    laeq = 20.0 * np.log10(p_rms_a / P0)
    return laeq


def try_get_sampling_rate_from_tdms_channel(ch):
    """
    Try to find the sampling rate (Hz) from common TDMS waveform properties.
    Returns fs (float) or None if not found.
    """
    props = getattr(ch, "properties", {}) or {}
    # NI Waveform convention: wf_increment is the time step (seconds)
    dt = None
    for key in ["wf_increment", "dt", "Waveform dt", "wf dt"]:
        if key in props:
            try:
                dt = float(props[key])
                break
            except Exception:
                pass
    if dt and dt > 0:
        return 1.0 / dt

    # Alternatively, some files may store fs directly
    for key in ["fs", "sampling_rate", "SamplingRate", "sample_rate", "wf_samples_per_second"]:
        if key in props:
            try:
                fs = float(props[key])
                if fs > 0:
                    return fs
            except Exception:
                pass

    return None


class TDMSAWeightingApp(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("TDMS → dB(A)  |  LAeq Calculator")
        self.tdms_path = None
        self.tdms = None
        self.groups = []
        self.channels = []
        self.current_group = None
        self.current_channel = None

        self.build_ui()

    def build_ui(self):
        layout = QVBoxLayout()

        # File selection
        file_box = QGroupBox("TDMS File")
        file_layout = QHBoxLayout()
        self.file_label = QLabel("No file selected.")
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.clicked.connect(self.on_browse)
        file_layout.addWidget(self.file_label, 1)
        file_layout.addWidget(self.btn_browse, 0)
        file_box.setLayout(file_layout)
        layout.addWidget(file_box)

        # Group/Channel selection
        gc_box = QGroupBox("Data Selection")
        gc_layout = QHBoxLayout()
        self.group_combo = QComboBox()
        self.group_combo.currentIndexChanged.connect(self.on_group_changed)
        self.channel_combo = QComboBox()
        gc_layout.addWidget(QLabel("Group:"))
        gc_layout.addWidget(self.group_combo, 1)
        gc_layout.addWidget(QLabel("Channel:"))
        gc_layout.addWidget(self.channel_combo, 1)
        gc_box.setLayout(gc_layout)
        layout.addWidget(gc_box)

        # Sampling rate
        fs_box = QGroupBox("Sampling Rate")
        fs_layout = QHBoxLayout()
        self.fs_edit = QLineEdit()
        self.fs_edit.setPlaceholderText("Hz (auto-detected if available)")
        self.fs_edit.setClearButtonEnabled(True)
        fs_layout.addWidget(QLabel("fs:"))
        fs_layout.addWidget(self.fs_edit, 1)
        fs_box.setLayout(fs_layout)
        layout.addWidget(fs_box)

        # Actions
        self.btn_compute = QPushButton("Compute LAeq (dB(A))")
        self.btn_compute.clicked.connect(self.on_compute)
        layout.addWidget(self.btn_compute)

        # Result
        self.result_label = QLabel("Result: —")
        self.result_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(self.result_label)

        # Tips
        tip = QLabel(
            "<i>Notes:</i> "
            "Signal must be in Pascals (Pa). If the sampling rate is not auto-detected, enter it manually. "
            "LAeq is computed over the entire file."
        )
        tip.setWordWrap(True)
        layout.addWidget(tip)

        self.setLayout(layout)
        self.resize(720, 260)

    def on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select TDMS File", "", "TDMS Files (*.tdms);;All Files (*)"
        )
        if not path:
            return
        self.load_tdms(path)

    def load_tdms(self, path: str):
        try:
            t = TdmsFile.read(path)
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read TDMS:\n{e}")
            return

        self.tdms = t
        self.tdms_path = path
        self.file_label.setText(os.path.basename(path))

        # Populate groups and channels
        groups = t.groups()
        self.group_combo.clear()
        self.channel_combo.clear()
        self.groups = groups

        for g in groups:
            self.group_combo.addItem(g.name)

        # Auto-populate first group's channels
        if groups:
            self.populate_channels_for_group(groups[0])

        # If only one group/channel, auto-select
        if len(groups) == 1 and len(groups[0].channels()) == 1:
            ch = groups[0].channels()[0]
            self.try_autofill_fs_from_channel(ch)

    def populate_channels_for_group(self, group):
        self.channel_combo.clear()
        self.channels = group.channels()
        for ch in self.channels:
            self.channel_combo.addItem(ch.name)
        # Try to auto-fill fs from first channel
        if self.channels:
            self.try_autofill_fs_from_channel(self.channels[0])

    def on_group_changed(self, idx: int):
        if self.tdms is None:
            return
        if idx < 0 or idx >= len(self.groups):
            return
        group = self.groups[idx]
        self.populate_channels_for_group(group)

    def get_selected_channel(self):
        gi = self.group_combo.currentIndex()
        ci = self.channel_combo.currentIndex()
        if gi < 0 or ci < 0 or gi >= len(self.groups):
            return None
        group = self.groups[gi]
        chs = group.channels()
        if ci >= len(chs):
            return None
        return chs[ci]

    def try_autofill_fs_from_channel(self, ch):
        fs = try_get_sampling_rate_from_tdms_channel(ch)
        if fs is not None:
            self.fs_edit.setText(f"{fs:.6f}")

    def on_compute(self):
        if self.tdms is None:
            QMessageBox.warning(self, "No File", "Please select a TDMS file first.")
            return

        ch = self.get_selected_channel()
        if ch is None:
            QMessageBox.warning(self, "No Channel", "Please select a channel.")
            return

        # Determine sampling rate
        fs_text = self.fs_edit.text().strip()
        fs = None
        if fs_text:
            try:
                fs = float(fs_text)
            except Exception:
                QMessageBox.warning(self, "Invalid fs", "Sampling rate must be a number (Hz).")
                return
        else:
            fs = try_get_sampling_rate_from_tdms_channel(ch)
            if fs is None:
                QMessageBox.information(
                    self, "Sampling Rate Needed",
                    "Sampling rate (fs) not found in TDMS properties.\n"
                    "Please enter fs (Hz) in the Sampling Rate box."
                )
                return

        if fs <= 0:
            QMessageBox.warning(self, "Invalid fs", "Sampling rate must be positive.")
            return

        try:
            # Read data as numpy array
            data = ch[:]
            # Ensure float64 for numeric stability
            data = np.asarray(data, dtype=np.float64)

            laeq = compute_la_eq(data, fs)
            if not np.isfinite(laeq):
                display = "Result: LAeq could not be computed (silence or invalid data)."
            else:
                display = f"Result: LAeq = {laeq:.2f} dB(A)"

            self.result_label.setText(display)

        except Exception as e:
            QMessageBox.critical(self, "Computation Error", f"Failed to compute LAeq:\n{e}")


def main():
    app = QApplication(sys.argv)
    w = TDMSAWeightingApp()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()