import math
import time
from pathlib import Path

import nidaqmx
from nidaqmx.constants import (
    AcquisitionType,
    TerminalConfiguration,
    SoundPressureUnits,
    ExcitationSource,
    LoggingMode,
    LoggingOperation,
    Coupling,
)

SAMPLE_RATE = 25600  # Hz

def pa_to_db_spl(p_pa: float, pref: float = 20e-6) -> float:
    """Convert Pascals to dB SPL re 20 µPa."""
    p_pa = max(float(p_pa), 1e-12)
    return 20.0 * math.log10(p_pa / pref)

def estimate_max_spl_db(max_input_volts: float, sensitivity_mV_per_Pa: float) -> float:
    """
    max_snd_press_level is in dB SPL re 20 µPa (per NI docs).
    Pmax(Pa) = Vmax / (sens[V/Pa]), sens[V/Pa] = (mV/Pa)/1000.  SPL = 20*log10(P/20e-6).
    """
    sens_v_per_pa = float(sensitivity_mV_per_Pa) / 1000.0
    if sens_v_per_pa <= 0:
        return 140.0
    pmax_pa = float(max_input_volts) / sens_v_per_pa
    return pa_to_db_spl(pmax_pa)

def record_microphone_to_tdms(
    physical_channel: str,
    tdms_path: Path,
    sensitivity_mV_per_Pa: float,
    duration_s: float,
    stop_event=None,
    group_name: str = "RawRecord",
    max_input_volts_for_estimate: float = 5.0,
    logging_operation: LoggingOperation = LoggingOperation.CREATE_OR_REPLACE,
) -> float:
    """
    Records finite samples at 25600 Hz and logs directly to TDMS (native DAQmx logging).
    Returns actual elapsed seconds.
    """
    total_samples = int(round(SAMPLE_RATE * float(duration_s)))
    if total_samples <= 0:
        raise ValueError("Duration too small; total_samples <= 0")

    max_spl_db = estimate_max_spl_db(max_input_volts_for_estimate, sensitivity_mV_per_Pa)

    with nidaqmx.Task() as task:
        ch = task.ai_channels.add_ai_microphone_chan(
            physical_channel,
            name_to_assign_to_channel="Sound",
            terminal_config=TerminalConfiguration.DEFAULT,
            units=SoundPressureUnits.PA,
            max_snd_press_level=max_spl_db,
            current_excit_source=ExcitationSource.INTERNAL,
            current_excit_val=0.004,  # 4 mA IEPE
        )

        # Recommended with IEPE to remove DC offset
        ch.ai_coupling = Coupling.AC
        ch.ai_microphone_sensitivity = float(sensitivity_mV_per_Pa)

        task.timing.cfg_samp_clk_timing(
            rate=SAMPLE_RATE,
            sample_mode=AcquisitionType.FINITE,
            samps_per_chan=total_samples,
        )

        # Native TDMS logging (best perf in LOG mode; cannot read while logging)
        task.in_stream.configure_logging(
            str(tdms_path),
            LoggingMode.LOG,
            group_name=group_name,
            operation=logging_operation,
        )

        task.start()
        t0 = time.time()

        while True:
            if stop_event is not None and stop_event.is_set():
                try:
                    task.stop()
                finally:
                    break

            if task.is_task_done():
                break

            time.sleep(0.02)

        t1 = time.time()
        return (t1 - t0)