
from dataclasses import dataclass

@dataclass
class MicConfig:
    physical_channel: str            # e.g. "cDAQ1Mod1/ai0"
    sensitivity_mV_per_Pa: float     # e.g. 45.60
    microphone_id: str = ""          # optional label

@dataclass
class RecordMeta:
    unit: str
    unit_state: str
    location: str
    duration_s: float

@dataclass
class RecordResult:
    tdms_path: str
    duration_s: float
    timestamp_iso: str
    unit_state: str
    location: str
