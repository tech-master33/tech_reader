import os
import sys
import time
import winsound

# Protect against console problems that would otherwise silence the app:
# - under pythonw / the packaged exe there is no console, so sys.stdout is
#   None and any print() raises AttributeError (killing speech, since the
#   focus callback printed *before* speaking);
# - the default console encoding (cp1252) cannot print characters like
#   emoji, which raised UnicodeEncodeError for TeamTalk chat messages.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import keyboard
import pythoncom
import wx
from comtypes import client
import comtypes.gen.UIAutomationClient as UIA

import config
import menu_manager
import settings
from focus_handler import (FocusChangedHandler, ValueChangedHandler,
                           VALUE_PROP_ID, SELECTION_PROP_ID)
from speech_manager import SpeechManager

SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def main():
    print("Screenreader starting...")
    try:
        winsound.PlaySound(os.path.join(SRC_DIR, 'start.wav'), winsound.SND_FILENAME)
    except Exception:
        pass
    pythoncom.CoInitialize()

    # Initialize UIA COM object
    uia = client.CreateObject(UIA.CUIAutomation)

    speech_manager = SpeechManager()
    # Restore voice, rate and volume saved in the Speech settings dialog.
    try:
        config.apply_saved_speech(speech_manager.driver)
    except Exception:
        pass
    menu_manager.init_menu(speech_callback=speech_manager.speak,
                           speech_manager=speech_manager)

    # Set up interruption hotkey (Ctrl to stop speech)
    keyboard.add_hotkey('ctrl', speech_manager.cancelSpeech, suppress=False)
    # Set up menu hotkey (CapsLock + Space)
    keyboard.add_hotkey('caps lock+space',
                        lambda: settings.menu_hotkey_enabled and wx.CallAfter(menu_manager.show_menu),
                        suppress=False)
    print("Hotkeys registered: Ctrl to stop, CapsLock+Space for menu.")

    def on_focus_changed(name):
        # Speak first: a console/encoding problem must never silence speech.
        speech_manager.speak(name)
        try:
            print(f"Focused element changed to: {name}")
            sys.stdout.flush()
        except Exception:
            pass

    # Register event handler
    handler = FocusChangedHandler(uia, on_focus_changed)
    uia.AddFocusChangedEventHandler(None, handler)

    # Announce Qt combo box selection changes (arrow keys without Alt+Down):
    # Qt raises property-changed events, not focus events, for those.
    value_handler = ValueChangedHandler(uia, speech_manager.speak)
    try:
        uia.AddPropertyChangedEventHandler(
            None, UIA.TreeScope_Subtree, value_handler,
            [VALUE_PROP_ID, SELECTION_PROP_ID])
        print("Monitoring Qt value changes...")
    except Exception as exc:
        print(f"Value-change monitoring unavailable: {exc}")

    print("Monitoring focus events...")

    # Keep the thread running to process events
    try:
        while True:
            pythoncom.PumpWaitingMessages()
            menu_manager.process_wx_events()
            time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        keyboard.unhook_all()
        uia.RemoveAllEventHandlers()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()