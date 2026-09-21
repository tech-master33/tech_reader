import os
import tempfile
import threading

import comtypes.client
from comtypes import COMError
import pythoncom

from synth_driver import SynthDriver
class Sapi5SynthDriver(SynthDriver):
    def __init__(self):
        super().__init__()
        self.voice = None
        self._lock = threading.Lock()
        self._init_engine()

    def _init_engine(self):
        try:
            self.voice = comtypes.client.CreateObject("SAPI.SpVoice")
        except Exception as e:
            print(f"Error initializing SAPI5: {e}")
            self.voice = None

    def speak(self, text):
        if not text:
            return
        with self._lock:
            if not self.voice:
                return
            try:
                # SVSFlagsAsync = 1, SVSFPurgeBeforeSpeak = 2
                flags = 1 | 2
                self.voice.Speak(text, flags)
            except COMError as e:
                print(f"SAPI5 Speak error: {e}")
                self._init_engine()

    def stop(self):
        with self._lock:
            if not self.voice:
                return
            try:
                # Purge pending speech
                self.voice.Speak("", 2)
            except COMError as e:
                print(f"SAPI5 Stop error: {e}")
                self._init_engine()

    # ----- speech settings -----

    def list_voices(self):
        with self._lock:
            if not self.voice:
                return []
            try:
                tokens = self.voice.GetVoices()
                return [tokens.Item(i).GetDescription() for i in range(tokens.Count)]
            except COMError as e:
                print(f"SAPI5 list voices error: {e}")
                return []

    def get_voice(self):
        with self._lock:
            if not self.voice:
                return None
            try:
                return self.voice.Voice.GetDescription()
            except COMError as e:
                print(f"SAPI5 get voice error: {e}")
                return None

    def set_voice(self, description):
        with self._lock:
            if not self.voice or not description:
                return False
            try:
                tokens = self.voice.GetVoices()
                for i in range(tokens.Count):
                    if tokens.Item(i).GetDescription() == description:
                        self.voice.Voice = tokens.Item(i)
                        return True
            except COMError as e:
                print(f"SAPI5 set voice error: {e}")
            return False

    def get_rate(self):
        with self._lock:
            if not self.voice:
                return 0
            try:
                return int(self.voice.Rate)
            except COMError as e:
                print(f"SAPI5 get rate error: {e}")
                return 0

    def set_rate(self, rate):
        with self._lock:
            if not self.voice:
                return
            try:
                self.voice.Rate = max(-10, min(10, int(rate)))
            except COMError as e:
                print(f"SAPI5 set rate error: {e}")

    def get_volume(self):
        with self._lock:
            if not self.voice:
                return 100
            try:
                return int(self.voice.Volume)
            except COMError as e:
                print(f"SAPI5 get volume error: {e}")
                return 100

    def set_volume(self, volume):
        with self._lock:
            if not self.voice:
                return
            try:
                self.voice.Volume = max(0, min(100, int(volume)))
            except COMError as e:
                print(f"SAPI5 set volume error: {e}")

    # ----- offline helpers -----

    def render_to_wav(self, text, voice_description=None, rate=None,
                      volume=None, path=None):
        """Render text to a WAV file using a separate SAPI engine.

        The live engine (voice, rate, volume) is never touched, so a
        preview cannot switch the current voice. An SpAudioFormat/SpFileStream
        renders the audio to disk; a fresh SpVoice with the requested
        settings speaks into that stream synchronously.

        Returns the path of the written file, or None on failure.
        """
        if not text:
            return None
        engine = None
        stream = None
        try:
            # SAPI is COM: this helper may be called from a non-main thread.
            pythoncom.CoInitialize()
            stream = comtypes.client.CreateObject("SAPI.SpFileStream")
            fmt = comtypes.client.CreateObject("SAPI.SpAudioFormat")
            fmt.Type = SAFT22kHz16BitMono
            stream.Format = fmt
            if path is None:
                fd, path = tempfile.mkstemp(prefix="techreader_test_", suffix=".wav")
                os.close(fd)
            # Open's second parameter is the mode; 3 = create + overwrite.
            # (This machine's comtypes wrapper exposes Open, not OpenStream.)
            stream.Open(path, 3)
            engine = comtypes.client.CreateObject("SAPI.SpVoice")
            if voice_description:
                tokens = engine.GetVoices()
                for i in range(tokens.Count):
                    if tokens.Item(i).GetDescription() == voice_description:
                        engine.Voice = tokens.Item(i)
                        break
            if rate is not None:
                engine.Rate = max(-10, min(10, int(rate)))
            if volume is not None:
                engine.Volume = max(0, min(100, int(volume)))
            engine.AudioOutputStream = stream
            engine.Speak(text, 0)  # synchronous render into the stream
            return path
        except Exception as e:
            print(f"SAPI5 render_to_wav error: {e}")
            return None
        finally:
            for obj in (engine, stream):
                try:
                    if obj is not None:
                        del obj
                except Exception:
                    pass
            pythoncom.CoUninitialize()


SAFT22kHz16BitMono = 22


def play_wav_file(path):
    """Play a WAV file on the default audio device without blocking.

    Returns the thread so a caller can wait for playback if it wants to.
    The file is deleted once playback finishes.
    """
    def _play():
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_NODEFAULT)
        except Exception as e:
            print(f"WAV playback error: {e}")
        finally:
            try:
                os.remove(path)
            except OSError:
                pass

    t = threading.Thread(target=_play, daemon=True)
    t.start()
    return t