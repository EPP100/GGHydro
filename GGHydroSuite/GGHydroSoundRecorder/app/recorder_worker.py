import threading
from pathlib import Path
from PySide6.QtCore import QObject, Signal
from nidaqmx.constants import LoggingOperation

from .models import MicConfig, RecordMeta, RecordResult
from .utils import iso_timestamp_seconds
from .ni_recorder import record_microphone_to_tdms

class RecorderWorker(QObject):
    status = Signal(str)
    finished = Signal(object)   # RecordResult
    error = Signal(str)

    def __init__(
        self,
        mic_cfg: MicConfig,
        record_meta: RecordMeta,
        stop_event: threading.Event,
        tdms_path: Path,
        logging_operation: LoggingOperation,
    ):
        super().__init__()
        self.mic_cfg = mic_cfg
        self.record_meta = record_meta
        self.stop_event = stop_event
        self.tdms_path = tdms_path
        self.logging_operation = logging_operation

    def run(self):
        try:
            self.status.emit("Recording")

            elapsed = record_microphone_to_tdms(
                physical_channel=self.mic_cfg.physical_channel,
                tdms_path=self.tdms_path,
                sensitivity_mV_per_Pa=self.mic_cfg.sensitivity_mV_per_Pa,
                duration_s=self.record_meta.duration_s,
                stop_event=self.stop_event,
                group_name="RawRecord",
                logging_operation=self.logging_operation,
            )

            result = RecordResult(
                tdms_path=str(self.tdms_path),
                duration_s=float(elapsed),
                timestamp_iso=iso_timestamp_seconds(),
                unit_state=self.record_meta.unit_state,
                location=self.record_meta.location,
            )

            self.status.emit("Idle")
            self.finished.emit(result)

        except Exception as e:
            self.status.emit("Idle")
            self.error.emit(str(e))