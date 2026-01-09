import json, os


def default_config():
    return {
        "project_name": "",
        "unit_number": "",
        "microphone": {
            "device": "",
            "channel": "",
            "sensitivity_mV_per_Pa": 50.0,
            "microphone_id": "",
        },
        "recordings": [],
    }


def load_config(path):
    if not os.path.exists(path):
        return default_config()
    with open(path, "r") as f:
        return json.load(f)


def save_config(path, cfg):
    with open(path, "w") as f:
        json.dump(cfg, f, indent=2)
