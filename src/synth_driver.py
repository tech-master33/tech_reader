"""Synthesizer driver base class and engine registry.

TechReader supports several speech engines (NVDA-style). Each engine is a
SynthDriver subclass registered here; SpeechManager instantiates the
selected one and the Settings dialog lists whatever is available.

Drivers only produce speech and describe/apply their own settings.
Anything TechReader-specific (queueing, cancel, the speech viewer) lives
in SpeechManager; command logic never enters the drivers.
"""
from abc import ABC, abstractmethod

# Registry: engine name -> driver class.
_ENGINES = {}


class SynthDriverError(Exception):
    """Raised when a synthesizer cannot do what was asked."""


class SynthDriver(ABC):
    """Base class for all speech engines.

    Subclasses must set `name` (the user-facing engine name used in the
    settings UI and config) and implement speak() and stop(). Everything
    else has safe defaults so engines can implement just what they can.
    """

    name = "unnamed"

    def __init__(self):
        pass

    @classmethod
    def is_supported(cls):
        """Return True when this engine can run on this machine."""
        return True

    @abstractmethod
    def speak(self, text):
        """Speak text (interrupting current speech per driver policy)."""

    @abstractmethod
    def stop(self):
        """Stop speech and discard pending output."""

    # ----- speech settings (optional capabilities) -----

    def list_voices(self):
        """Return the human-readable voice names offered by this engine."""
        return []

    def get_voice(self):
        """Return the current voice name, or None if not applicable."""
        return None

    def set_voice(self, description):
        """Select a voice by name. Returns True on success."""
        return False

    def get_rate(self):
        return 0

    def set_rate(self, rate):
        pass

    def get_volume(self):
        return 100

    def set_volume(self, volume):
        pass

    def render_to_wav(self, text, voice_description=None, rate=None,
                      volume=None, path=None):
        """Render text to a WAV file without touching the live engine.

        Returns the path of the written file, or None when the engine
        cannot render offline.
        """
        return None

    def terminate(self):
        """Release resources. The driver must not be used afterwards."""
        pass


def register_engine(cls):
    """Class decorator: add a SynthDriver subclass to the registry."""
    _ENGINES[cls.name] = cls
    return cls


def get_engines():
    """Return {name: driver class} for engines supported on this machine."""
    available = {}
    for name, cls in _ENGINES.items():
        try:
            if cls.is_supported():
                available[name] = cls
        except Exception:
            continue
    return available


def get_engine_class(name):
    return get_engines().get(name)


def get_default_engine_name():
    """The engine to use when nothing is configured (SAPI 5 first: it is
    the classic engine with the widest voice choice)."""
    engines = get_engines()
    for preferred in ("SAPI 5", "Windows OneCore voices"):
        if preferred in engines:
            return preferred
    return next(iter(engines), None)
