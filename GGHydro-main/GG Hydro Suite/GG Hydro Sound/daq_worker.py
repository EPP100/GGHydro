import os
import nidaqmx
from nidaqmx.constants import (
    AcquisitionType,
    LoggingMode,
    LoggingOperation,
    ExcitationSource,
    SoundPressureUnits,
    TerminalConfiguration,
)
from PySide6.QtCore import QThread, Signal
from pathlib import Path


class DAQWorker(QThread):
    elapsed_signal = Signal(float)
    finished_signal = Signal(dict)

    SAMPLE_RATE = 25600

    def __init__(self, project_path, cfg, duration, filename):
        super().__init__()
        self.cfg = cfg
        self.duration_sec = duration
        self.project_path = Path(project_path)
        self.filename = filename
        self.running = True

    def run(self):
        mic = self.cfg["microphone"]
        total_samples = int(self.duration_sec * self.SAMPLE_RATE)

        rec_dir = os.path.join(self.project_path, "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        filepath = os.path.join(rec_dir, self.filename)

        with nidaqmx.Task() as task:
            ch = task.ai_channels.add_ai_microphone_chan(
                mic["channel"],
                name_to_assign_to_channel="Sound",
                terminal_config=TerminalConfiguration.DEFAULT,
                units=SoundPressureUnits.PA,
                max_snd_press_level=5 / mic["sensitivity_mV_per_Pa"],
                current_excit_source=ExcitationSource.INTERNAL,
                current_excit_val=0.004,
            )

            # NI Device CONFIGURATION
            ch.ai_coupling = nidaqmx.constants.Coupling.AC
            ch.ai_microphone_sensitivity = mic["sensitivity_mV_per_Pa"]

            # Configure Sampling rate
            task.timing.cfg_samp_clk_timing(
                rate=self.SAMPLE_RATE,
                sample_mode=AcquisitionType.FINITE,
                samps_per_chan=total_samples,
            )

            # TDMS NATIVE LOGGING
            task.in_stream.configure_logging(
                filepath,
                LoggingMode.LOG,
                group_name="RawRecord",
                operation=LoggingOperation.CREATE_OR_REPLACE,  # Open or create. if file exist, it will append the data
            )

            # TDMS METADATA (Pascal scaling info)
            # task.in_stream.add_metadata("MicrophoneID", mic["microphone_id"])
            # task.in_stream.add_metadata(
            #     "Sensitivity_Pa_per_V", mic["sensitivity_pa_per_v"]
            # )
            # task.in_stream.add_metadata("EngineeringUnit", "Pascal")

            # task.in_stream.write_properties(
            #     {
            #         "Project": self.cfg["project_name"],
            #         "Unit": self.cfg["unit_number"],
            #         "Unit State": self.cfg["recording"]["unit_state"],
            #         "Location": self.cfg["recording"]["location"],
            #         "Sample Rate (Hz)": 25600,
            #         "Engineering Units": "Pa",
            #     }
            # )

            task.start()

            while not task.is_task_done() and self.running:
                self.elapsed_signal.emit(
                    task.in_stream.total_samp_per_chan_acquired / self.SAMPLE_RATE
                )
                self.msleep(50)

            task.wait_until_done(timeout=self.duration_sec + 2)

            self.elapsed_signal.emit(
                task.in_stream.total_samp_per_chan_acquired / self.SAMPLE_RATE
            )

        self.finished_signal.emit({"filename": self.filename})

    def stop(self):
        self.running = False
