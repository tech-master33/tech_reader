"""Speech output management for TechReader.

SpeechManager owns the speech worker thread and the selected synthesizer
engine (NVDA-style: engines are pluggable SynthDriver implementations
registered in synth_driver). Per-engine settings are persisted to the
config as `synth_<name>_voice` etc. so switching engines and back
restores each engine's voice, rate, and volume.
"""
import queue
import threading

import config
from synth_driver import (get_engines, get_engine_class,
                          get_default_engine_name)

# Importing the driver modules registers their engines in synth_driver.
import null_synth  # noqa: F401
import onecore  # noqa: F401
import sapi5  # noqa: F401


def _engine_key(engine_name):
    """Config key suffix for an engine name: lowercase, alnum only."""
    return "".join(c for c in engine_name.lower() if c.isalnum())


class SpeechManager:
    def __init__(self):
        self.driver = None
        self.engine_name = None
        self.text_queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._utterance_listener = None
        self._listener_lock = threading.Lock()
        self._worker_ready = threading.Event()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    # ----- engine selection -----------------------------------------

    @staticmethod
    def available_engines():
        """Names of the engines that can run on this machine."""
        return list(get_engines())

    def switch_engine(self, engine_name):
        """Instantiate and select the named engine, applying its saved
        settings. Returns True on success (including staying on the
        current engine when asked to switch to it)."""
        cls = get_engine_class(engine_name)
        if cls is None:
            return False
        if engine_name == self.engine_name and self.driver is not None:
            return True
        try:
            new_driver = cls()
        except Exception as e:
            print(f"Could not start engine {engine_name!r}: {e}")
            return False
        old = self.driver
        self.driver = new_driver
        self.engine_name = engine_name
        self._apply_saved_engine_settings()
        if old is not None:
            try:
                old.stop()
                old.terminate()
            except Exception:
                pass
        return True

    def _apply_saved_engine_settings(self):
        """Apply the saved voice/rate/volume for the current engine."""
        if self.driver is None:
            return
        key = _engine_key(self.engine_name or "")
        data = config.load()
        voice = data.get(f"synth_{key}_voice")
        rate = data.get(f"synth_{key}_rate")
        volume = data.get(f"synth_{key}_volume")
        if key == "sapi5":
            # Migration: configs from before the engine system stored SAPI 5
            # settings under flat keys. They still apply to the SAPI 5
            # engine when no per-engine values have been saved yet.
            if not voice:
                voice = data.get("voice")
            if not isinstance(rate, int):
                rate = data.get("rate")
            if not isinstance(volume, int):
                volume = data.get("volume")
        if voice:
            try:
                self.driver.set_voice(voice)
            except Exception:
                pass
        if isinstance(rate, int):
            try:
                self.driver.set_rate(rate)
            except Exception:
                pass
        if isinstance(volume, int):
            try:
                self.driver.set_volume(volume)
            except Exception:
                pass

    def save_engine_settings(self, voice=None, rate=None, volume=None):
        """Persist the given settings under the current engine's keys."""
        key = _engine_key(self.engine_name or "")
        values = {}
        if voice:
            values[f"synth_{key}_voice"] = voice
        if isinstance(rate, int):
            values[f"synth_{key}_rate"] = rate
        if isinstance(volume, int):
            values[f"synth_{key}_volume"] = volume
        values["synth"] = self.engine_name
        if values:
            config.save(**values)

    # ----- speech plumbing ------------------------------------------

    def _worker(self):
        try:
            import pythoncom
            pythoncom.CoInitialize()
        except Exception as e:
            print(f"CoInitialize failed in speech worker: {e}")
            self._worker_ready.set()
            return
        try:
            # COM is initialized on this thread; drivers may now be used
            # from here. Start the initial engine inside the worker so its
            # COM objects are created in a COM apartment that stays alive.
            if self.driver is None:
                name = config.get("synth") or get_default_engine_name()
                if not self.switch_engine(name):
                    # Fall back to whatever is available; never stay mute
                    # just because the configured engine is gone.
                    fallback = get_default_engine_name()
                    if fallback and fallback != name:
                        self.switch_engine(fallback)
        finally:
            self._worker_ready.set()
        while True:
            text = self.text_queue.get()
            if text is None:
                break
            if self._cancel_event.is_set():
                self._cancel_event.clear()
                self.text_queue.task_done()
                continue
            if self.driver is not None:
                self.driver.speak(text)
            self._notify_utterance(text)
            self.text_queue.task_done()

    def wait_ready(self, timeout=10.0):
        """Wait until the worker has initialized COM and the engine."""
        self._worker_ready.wait(timeout)

    def speak(self, text):
        if not text:
            return
        self._cancel_event.clear()
        self.text_queue.put(text)

    def cancelSpeech(self):
        self._cancel_event.set()
        driver = self.driver
        if driver is not None:
            try:
                driver.stop()
            except Exception:
                pass
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
                self.text_queue.task_done()
            except queue.Empty:
                break

    def set_utterance_listener(self, callback):
        """Register a callback invoked (worker thread) after each utterance.

        Used by the speech viewer. Pass None to unregister.
        """
        with self._listener_lock:
            self._utterance_listener = callback

    def _notify_utterance(self, text):
        with self._listener_lock:
            callback = self._utterance_listener
        if callback is None:
            return
        try:
            callback(text)
        except Exception:
            pass
