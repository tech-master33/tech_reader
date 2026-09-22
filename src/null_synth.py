"""The "No speech" engine: a selectable null synthesizer (NVDA-style).

Useful for sighted testers, kiosks, and for reading the speech viewer
without hearing anything.
"""
from synth_driver import SynthDriver, register_engine


@register_engine
class NullSynthDriver(SynthDriver):
    name = "No speech"

    def speak(self, text):
        pass

    def stop(self):
        pass
