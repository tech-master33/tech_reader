"""Persistent settings storage for TechReader.

Settings live in a small JSON file under %APPDATA%\\TechReader so they survive
restarts and work both when run from source and from the packaged exe.
"""

import json
import os

APP_NAME = "TechReader"
CONFIG_FILE = "techreader_config.json"


def _config_dir():
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def config_path():
    return os.path.join(_config_dir(), CONFIG_FILE)


def load():
    """Return the saved settings as a dict (empty dict when none exist)."""
    try:
        with open(config_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def get(key, default=None):
    return load().get(key, default)


def save(**values):
    """Merge values into the stored settings and write them to disk."""
    data = load()
    data.update({k: v for k, v in values.items() if v is not None})
    try:
        os.makedirs(_config_dir(), exist_ok=True)
        with open(config_path(), "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except OSError as e:
        print(f"Could not save settings: {e}")
        return False
    return True


def _try(callable_, *args):
    try:
        return callable_(*args)
    except Exception:
        return None


def apply_saved_speech(driver):
    """Apply the saved voice / rate / volume to a speech driver, if any."""
    data = load()
    if driver is None:
        return
    voice = data.get("voice")
    if voice:
        _try(driver.set_voice, voice)
    rate = data.get("rate")
    if isinstance(rate, int):
        _try(driver.set_rate, rate)
    volume = data.get("volume")
    if isinstance(volume, int):
        _try(driver.set_volume, volume)
