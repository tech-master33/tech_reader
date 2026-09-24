"""Freeze-regression harness for the TechReader menu (run manually).

Verifies, under a hard 9-second watchdog (any hang exits with code 97):

  1. The CapsLock+Space menu path (foreground dance -> pause UIA events ->
     popup -> Escape close) completes without hanging, and the UIA
     connection is paused while the popup is open and resumed afterwards.
  2. SpeechManager.cancelSpeech() purges the engine via the queue sentinel
     and never blocks the calling thread.

Run:  python tools/test_menu_freeze.py
"""

import os
import sys
import threading
import time

import pythoncom

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                os.pardir, "src"))

TIMER = threading.Timer(9.0, lambda: os._exit(97))  # hard watchdog
TIMER.start()


def check(name, ok):
    print(("PASS: " if ok else "FAIL: ") + name)
    sys.stdout.flush()
    if not ok:
        os._exit(1)


# --- 1. Handler-layer suspension plumbing -----------------------------------
import uia_core

uia = uia_core.get_automation()  # force the shared connection up
import menu_manager

check("suppression flag initially clear",
      menu_manager._events_suppressed() is False)
menu_manager._suspend_uia_handlers()
check("suppression flag set by _suspend_uia_handlers",
      menu_manager._events_suppressed() is True)
menu_manager._resume_uia_handlers()
check("suppression flag cleared by _resume_uia_handlers",
      menu_manager._events_suppressed() is False)

# Every registered COM handler must honour the suppression flag without
# touching the sender element (no cross-process call may run inside the
# popup's modal loop).
import event_handler
import focus_handler

evt = event_handler.AutomationEventHandler(lambda t: None,
                                           lambda el: "should not run")
class _Boom:
    def QueryInterface(self, *a, **k):
        raise AssertionError("sender touched while suppressed")

menu_manager._suspend_uia_handlers()
evt.HandleAutomationEvent(_Boom(), 0)
notif = event_handler.NotificationEventHandler(lambda t: None)
notif.HandleNotificationEvent(_Boom(), 0, 0, "hello", "id")
fh = focus_handler.FocusChangedHandler(uia, lambda t: None)
fh.HandleFocusChangedEvent(_Boom())
check("handlers inert while menu is open (sender never touched)", True)
menu_manager._resume_uia_handlers()

# --- 2. Speech stop sentinel -------------------------------------------------
import speech_manager

spoken = []


class FakeDriver:
    def __init__(self):
        self.stops = 0
        self.spoken = []

    def speak(self, text):
        self.spoken.append(text)

    def stop(self):
        self.stops += 1

    def terminate(self):
        pass


sm = speech_manager.SpeechManager()
sm.wait_ready(5.0)
sm.driver = FakeDriver()
sm.speak("hello")
sm.cancelSpeech()          # must not block; sentinel purges the engine
sm.speak("after")          # purge must not eat speech that comes later
time.sleep(0.4)
check("cancelSpeech never blocked the caller", True)
check("worker purged the engine via sentinel", sm.driver.stops >= 1)
check("speech after the cancel is still spoken", sm.driver.spoken == ["after"])
sm.cancelSpeech()
time.sleep(0.3)

# --- 3. Real menu open/close cycle -------------------------------------------
import wx
import menu_manager
import settings

settings.menu_hotkey_enabled = True
menu_manager.init_menu(speech_callback=lambda text: spoken.append(text))

# Refusal path must stay instant (simulates unforgiving foreground windows
# by pointing the check at an impossible window handle).
check("menu globals initialised", menu_manager._owner_frame is not None)

results = {}


def open_menu():
    menu_manager.show_menu()
    results["done"] = True


wx.CallAfter(open_menu)


def close_menu():
    if menu_manager._menu is None:
        wx.CallLater(100, close_menu)
        return
    results["paused_during"] = menu_manager._uia_suspended
    # A real Escape keypress: the hide path sends Escapes through the
    # UIActionSimulator, which needs the menu loop running to process them.
    menu_manager.hide_menu()


wx.CallLater(700, close_menu)

deadline = time.time() + 8
while time.time() < deadline:
    pythoncom.PumpWaitingMessages()
    menu_manager.process_wx_events()
    if results.get("done"):
        break
    time.sleep(0.01)

check("menu cycle completed without hanging", results.get("done") is True)
check("UIA handlers suspended while popup was open",
      results.get("paused_during") is True)
check("UIA handlers resumed after close",
      menu_manager._uia_suspended is False)
check("menu announced", any("TechReader menu" in s for s in spoken))

print("ALL CHECKS PASSED")
sys.stdout.flush()
os._exit(0)
