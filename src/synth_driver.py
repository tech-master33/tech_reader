from abc import ABC, abstractmethod

class SynthDriver(ABC):
    def __init__(self):
        pass

    @abstractmethod
    def speak(self, text):
        pass

    @abstractmethod
    def stop(self):
        pass
