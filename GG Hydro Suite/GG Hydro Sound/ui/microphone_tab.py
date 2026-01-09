from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QGroupBox,
)
from PySide6.QtCore import Signal
from nidaqmx.system import System


class MicrophoneTab(QWidget):
    changed = Signal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg

        self.dev = QComboBox()
        self.chan = QComboBox()
        self.sens = QDoubleSpinBox()
        self.sens.setRange(0.1, 10000)
        self.sens.setSuffix(" mV/Pa")
        self.mic_id = QLineEdit()

        self.dev.currentTextChanged.connect(lambda _: self.changed.emit())
        self.chan.currentTextChanged.connect(lambda _: self.changed.emit())
        self.sens.valueChanged.connect(lambda _: self.changed.emit())
        self.mic_id.textEdited.connect(lambda _: self.changed.emit())

        self.populate_devices()
        self.dev.currentTextChanged.connect(self.populate_channels)

        form = QFormLayout()
        form.addRow("NI Device:", self.dev)
        form.addRow("Channel:", self.chan)
        form.addRow("Sensitivity:", self.sens)
        form.addRow("Microphone ID:", self.mic_id)

        box = QGroupBox("Microphone (IEPE)")
        box.setLayout(form)

        layout = QVBoxLayout(self)
        layout.addWidget(box)
        layout.addStretch()
        layout.setContentsMargins(20, 20, 20, 20)

    def populate_devices(self):
        self.dev.clear()
        self.dev.addItems([d.name for d in System.local().devices])

    def populate_channels(self, dev):
        self.chan.clear()
        if dev:
            self.chan.addItems(
                [c.name for c in System.local().devices[dev].ai_physical_chans]
            )

    def load(self):
        mic = self.cfg["microphone"]
        self.sens.setValue(mic.get("sensitivity_mV_per_Pa", 50))
        self.mic_id.setText(mic.get("microphone_id", ""))
        self.dev.setCurrentText(mic.get("device", ""))
        self.populate_channels(self.dev.currentText())
        self.chan.setCurrentText(mic.get("channel", ""))

    def get_data(self):
        mic = self.cfg["microphone"]
        mic.update(
            {
                "device": self.dev.currentText(),
                "channel": self.chan.currentText(),
                "sensitivity_mV_per_Pa": self.sens.value(),
                "microphone_id": self.mic_id.text(),
            }
        )
