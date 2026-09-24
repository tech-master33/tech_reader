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
if sys.stdout is None or sys.stderr is None:
    if getattr(sys, "frozen", False):
        # Packaged exe: keep the app's prints in a log under
        # %APPDATA%\TechReader so problems on other machines can be
        # diagnosed remotely without writing anything into the program
        # folder.
        try:
            import config as _config
            _log = open(_config.log_path(), "a", buffering=1,
                        encoding="utf-8", errors="replace")
            sys.stdout = sys.stdout or _log
            sys.stderr = _log
        except Exception:
            pass
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
import comtypes.gen.UIAutomationClient as UIA

import config
import event_handler
import menu_manager
import native_keyboard
import settings
import uia_core
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

    # Initialize UIA through the shared core (CUIAutomation8, sane timeouts,
    # registration helpers that paper over this machine's comtypes quirks).
    uia = uia_core.get_automation()

    speech_manager = SpeechManager()
    # The speech worker thread picks the configured engine (or the best
    # available one) and applies that engine's saved voice/rate/volume.
    # Speech needs to be ready before the menu or announcements use it.
    speech_manager.wait_ready()
    menu_manager.init_menu(speech_callback=speech_manager.speak,
                           speech_manager=speech_manager)

    # Keyboard: prefer the native low-level hook (techreader_keyboard.dll),
    # fall back to python-keyboard. Both paths deliver the same two commands:
    # Ctrl interrupts speech, CapsLock+Space toggles the menu.
    def dispatch_keyboard_command(command):
        # Runs on the keyboard pump thread (native path only).
        if command == "interrupt":
            speech_manager.cancelSpeech()
        elif command == "menu":
            if settings.menu_hotkey_enabled:
                wx.CallAfter(menu_manager.show_menu)

    def start_keyboard():
        if native_keyboard.is_available():
            kb = native_keyboard.NativeKeyboard(
                on_command=dispatch_keyboard_command,
                on_error=lambda exc: print(f"Keyboard error: {exc}"))
            if kb.start():
                print("Keyboard: native low-level hook active (techreader_keyboard.dll).")
                print("Commands: Ctrl to stop, CapsLock+Space for menu.")
                return kb
            print("Keyboard: native hook failed to start; using python-keyboard fallback.")
        else:
            print("Keyboard: native DLL not found; using python-keyboard fallback.")
        keyboard.add_hotkey('ctrl', speech_manager.cancelSpeech, suppress=False)
        keyboard.add_hotkey('caps lock+space',
                            lambda: settings.menu_hotkey_enabled and wx.CallAfter(menu_manager.show_menu),
                            suppress=False)
        print("Hotkeys registered: Ctrl to stop, CapsLock+Space for menu.")
        return None

    try:
        native_kb = start_keyboard()
    except Exception as exc:
        print(f"Keyboard setup failed: {exc}")
        native_kb = None

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
    # This comtypes build's IUIAutomation.AddPropertyChangedEventHandler takes
    # (element, scope, cacheRequest, handler, propertyArray); a NULL element
    # is rejected (E_POINTER), so the subscription is rooted at the desktop
    # root element and follows the whole tree from there.
    value_handler = ValueChangedHandler(uia, speech_manager.speak)
    try:
        root_element = uia.GetRootElement()
        uia.AddPropertyChangedEventHandler(
            root_element, UIA.TreeScope_Subtree, None, value_handler,
            [VALUE_PROP_ID, SELECTION_PROP_ID])
        print("Monitoring Qt value changes...")
    except Exception as exc:
        print(f"Value-change monitoring unavailable: {exc}")

    # Menu, tooltip, window and notification announcements (each toggleable
    # in the menu under Preferences -> Event announcements).
    try:
        registered = event_handler.register_events(speech_manager.speak)
        if registered:
            print("Event announcements active:", ", ".join(sorted(registered)))
        else:
            print("Event announcements: all disabled in settings.")
    except Exception as exc:
        print(f"Event announcements unavailable: {exc}")

    print("Monitoring focus events...")

    # Keep the thread running to process events
    try:
        while True:
            pythoncom.PumpWaitingMessages()
            menu_manager.process_wx_events()
            time.sleep(0.005)
    except KeyboardInterrupt:
        pass
    finally:
        if native_kb is not None:
            native_kb.stop()
        keyboard.unhook_all()
        uia.RemoveAllEventHandlers()
        pythoncom.CoUninitialize()


if __name__ == "__main__":
    main()