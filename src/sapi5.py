import comtypes.client
from comtypes import COMError
from synth_driver import SynthDriver
import threading

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