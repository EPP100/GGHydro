
import re
from datetime import datetime
from pathlib import Path

def sanitize_token(text: str, max_len: int = 60) -> str:
    text = (text or "").strip()
    text = re.sub(r"\s+", " ", text)
    # remove characters that are problematic in Windows paths
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "", text)
    text = text.strip()
    return (text[:max_len] if text else "NA")

def today_yyyy_mm_dd() -> str:
    return datetime.now().strftime("%Y-%m-%d")

def iso_timestamp_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")

def build_tdms_filename(project: str, unit: str, unit_state: str, location: str) -> str:
    """
    Template required:
    YYYY-MM-DD - PROJECT - UNIT - UNITSTATE - LOCATION.tdms
    """
    date_str = today_yyyy_mm_dd()
    return f"{date_str} - {project} - {unit} - {unit_state} - {location}.tdms"

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def increment_path(path: Path) -> Path:
    """
    Return a new path with ' (2)', ' (3)' ... appended if needed.
    """
    if not path.exists():
        return path

    stem, suffix = path.stem, path.suffix
    n = 2
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1
