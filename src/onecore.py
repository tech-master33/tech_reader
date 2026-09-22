"""Windows OneCore voices engine for TechReader.

Windows 10/11 ships modern OneCore voices (the Settings > Time & language
> Speech voices) that are separate from the classic SAPI 5 desktop voices.
They are enumerated through SpObjectTokenCategory under the OneCore
registry location and spoken through SAPI's SpVoice, which accepts those
tokens on current Windows builds.
"""
import os
import tempfile
import threading

import comtypes.client
from comtypes import COMError
import pythoncom

from synth_driver import SynthDriver, register_engine

_ONECORE_VOICES_KEY = (r"HKEY_LOCAL_MACHINE"
                       r"\SOFTWARE\Microsoft\Speech_OneCore\Voices")

SAFT22kHz16BitMono = 22


def _new_engine():
    """Create an SpVoice COM object (COM must be initialized on the thread)."""
    return comtypes.client.CreateObject("SAPI.SpVoice")


def _list_onecore_tokens():
    """Return the OneCore voice tokens, [] when the category is missing."""
    try:
        cat = comtypes.client.CreateObject("SAPI.SpObjectTokenCategory")
        cat.SetId(_ONECORE_VOICES_KEY, False)
        tokens = cat.EnumerateTokens()
        return [tokens.Item(i) for i in range(tokens.Count)]
    except Exception:
        return []


@register_engine
class OneCoreSynthDriver(SynthDriver):
    name = "Windows OneCore voices"

    def __init__(self):
        super().__init__()
        self.voice = None
        self._lock = threading.Lock()
        self._init_engine()

    @classmethod
    def is_supported(cls):
        # Registry check (deterministic, no COM): at least one OneCore
        # voice token installed.
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"Software\Microsoft"
                                              r"\Speech_OneCore\Voices"
                                              r"\Tokens") as key:
                        if winreg.QueryInfoKey(key)[0] > 0:
                            return True
                except OSError:
                    continue
        except Exception:
            pass
        return False

    def _init_engine(self):
        try:
            self.voice = _new_engine()
        except Exception as e:
            print(f"Error initializing OneCore engine: {e}")
            self.voice = None

    def speak(self, text):
        if not text:
            return
        with self._lock:
            if not self.voice:
                return
            try:
                # SVSFlagsAsync = 1, SVSFPurgeBeforeSpeak = 2
                self.voice.Speak(text, 1 | 2)
            except COMError as e:
                print(f"OneCore Speak error: {e}")
                self._init_engine()

    def stop(self):
        with self._lock:
            if not self.voice:
                return
            try:
                self.voice.Speak("", 2)
            except COMError as e:
                print(f"OneCore Stop error: {e}")
                self._init_engine()

    # ----- speech settings -----

    def list_voices(self):
        with self._lock:
            if not self.voice:
                return []
            try:
                return [t.GetDescription(0) for t in _list_onecore_tokens()]
            except COMError as e:
                print(f"OneCore list voices error: {e}")
                return []

    def get_voice(self):
        with self._lock:
            if not self.voice:
                return None
            try:
                return self.voice.Voice.GetDescription(0)
            except COMError as e:
                print(f"OneCore get voice error: {e}")
                return None

    def set_voice(self, description):
        with self._lock:
            if not self.voice or not description:
                return False
            try:
                for t in _list_onecore_tokens():
                    if t.GetDescription(0) == description:
                        self.voice.Voice = t
                        return True
            except COMError as e:
                print(f"OneCore set voice error: {e}")
            return False

    def get_rate(self):
        with self._lock:
            if not self.voice:
                return 0
            try:
                return int(self.voice.Rate)
            except COMError as e:
                print(f"OneCore get rate error: {e}")
                return 0

    def set_rate(self, rate):
        with self._lock:
            if not self.voice:
                return
            try:
                self.voice.Rate = max(-10, min(10, int(rate)))
            except COMError as e:
                print(f"OneCore set rate error: {e}")

    def get_volume(self):
        with self._lock:
            if not self.voice:
                return 100
            try:
                return int(self.voice.Volume)
            except COMError as e:
                print(f"OneCore get volume error: {e}")
                return 100

    def set_volume(self, volume):
        with self._lock:
            if not self.voice:
                return
            try:
                self.voice.Volume = max(0, min(100, int(volume)))
            except COMError as e:
                print(f"OneCore set volume error: {e}")

    # ----- offline helpers -----

    def render_to_wav(self, text, voice_description=None, rate=None,
                      volume=None, path=None):
        """Render to a WAV file with a separate throwaway engine; the live
        voice is never touched. OneCore tokens are assigned to the render
        engine the same way as to the live engine."""
        if not text:
            return None
        engine = None
        stream = None
        try:
            pythoncom.CoInitialize()
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
            fmt.Type = SAFT22kHz16BitMono
            stream.Format = fmt
            if path is None:
                fd, path = tempfile.mkstemp(prefix="techreader_test_",
                                            suffix=".wav")
                os.close(fd)
            # Open's second parameter is the mode; 3 = create + overwrite.
            stream.Open(path, 3)
            engine = _new_engine()
            if voice_description:
                for t in _list_onecore_tokens():
                    if t.GetDescription(0) == voice_description:
                        engine.Voice = t
                        break
            if rate is not None:
                engine.Rate = max(-10, min(10, int(rate)))
            if volume is not None:
                engine.Volume = max(0, min(100, int(volume)))
            engine.AudioOutputStream = stream
            engine.Speak(text, 0)  # synchronous render into the stream
            return path
        except Exception as e:
            print(f"OneCore render_to_wav error: {e}")
            return None
        finally:
            for obj in (engine, stream):
                try:
                    if obj is not None:
                        del obj
                except Exception:
                    pass
            pythoncom.CoUninitialize()
