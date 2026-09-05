import threading
import queue
import pythoncom
from sapi5 import Sapi5SynthDriver

class SpeechManager:
    def __init__(self):
        self.driver = Sapi5SynthDriver()
        self.text_queue = queue.Queue()
        self._cancel_event = threading.Event()
        self._utterance_listener = None
        self._listener_lock = threading.Lock()
        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

    def _worker(self):
        try:
            pythoncom.CoInitialize()
        except Exception as e:
            print(f"CoInitialize failed in worker thread: {e}")
            return
        try:
            while True:
                text = self.text_queue.get()
                if text is None:
                    break
                # Check if cancel was requested before speaking
                if self._cancel_event.is_set():
                    self._cancel_event.clear()
                    self.text_queue.task_done()
                    continue
                self.driver.speak(text)
                self._notify_utterance(text)
                self.text_queue.task_done()
        finally:
            pythoncom.CoUninitialize()

    def speak(self, text):
        if not text:
            return
        self._cancel_event.clear()
        self.text_queue.put(text)

    def cancelSpeech(self):
        # Signal cancel
        self._cancel_event.set()
        # Stop current speech immediately
        self.driver.stop()
        # Clear any pending items in queue
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