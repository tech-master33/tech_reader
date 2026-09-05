import os
import subprocess
import sys
import threading
import winsound
import wx

import settings

app = None
_speech_callback = None
_speech_manager = None
_menu_frame = None
_last_sub = None
_speech_viewer_frame = None
_speech_viewer_text = None

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.dirname(os.path.abspath(__file__))


def set_speech_callback(callback):
    global _speech_callback
    _speech_callback = callback


def _speak(text):
    if text and _speech_callback:
        _speech_callback(text)


def init_menu(speech_callback=None, speech_manager=None):
    global app, _menu_frame, _speech_manager
    set_speech_callback(speech_callback)
    _speech_manager = speech_manager
    app = wx.App(False)
    _build_menu()


def _add_buttons(panel, sizer, items, on_navigate):
    """Add buttons to the menu panel.

    on_navigate is called before each button's handler runs; the main menu
    passes a no-op while submenus hide the menu so item actions (dialogs,
    restart, ...) are announced without the menu re-announcing itself.
    """
    for item in items:
        if item is None:
            sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 4)
        else:
            label, handler = item
            btn = wx.Button(panel, label=label)
            btn.Bind(wx.EVT_BUTTON, lambda e, h=handler: (on_navigate(), h(e)))
            sizer.Add(btn, 0, wx.EXPAND | wx.ALL, 2)


def _bind_focus_speech(ctrl, text):
    """Speak a control's label when it receives keyboard focus.

    Used inside dialogs, where UIA focus events are not pumped while the
    dialog's modal loop is running.
    """
    try:
        ctrl.Bind(wx.EVT_SET_FOCUS, lambda e: _speak(text))
    except Exception:
        pass


def _clear_panel(panel):
    for child in panel.GetChildren():
        child.Destroy()
    panel.GetSizer().Clear()


def _show_sub(title, items):
    global _last_sub
    _last_sub = title
    panel = _menu_frame.GetChildren()[0]
    _clear_panel(panel)
    sizer = panel.GetSizer()
    _add_buttons(panel, sizer, items, _close_menu_for_action)
    sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 4)
    btn_back = wx.Button(panel, label="Back")
    btn_back.Bind(wx.EVT_BUTTON, lambda e: _show_main())
    sizer.Add(btn_back, 0, wx.EXPAND | wx.ALL, 2)
    sizer.Layout()
    _menu_frame.SetTitle(f"TechReader - {title}")
    _speak(title)


def _show_main(speak=True):
    global _last_sub
    _last_sub = None
    panel = _menu_frame.GetChildren()[0]
    _clear_panel(panel)
    sizer = panel.GetSizer()

    def open_sub(title, items):
        def handler(e):
            _show_sub(title, items)
        return handler

    _add_buttons(panel, sizer, [
        ("&Preferences", open_sub("Preferences", [
            ("&Settings...", lambda e: _open_speech_settings()),
            ("&Voice settings...", lambda e: _open_speech_settings()),
            ("&Output settings...", lambda e: _open_output_settings()),
            ("&Keyboard settings...", lambda e: _open_keyboard_settings()),
            ("&Object presentation...", lambda e: _open_object_presentation()),
            ("&Mouse settings...", lambda e: _open_info(
                "Mouse settings", "Mouse settings are not implemented yet.")),
            ("&Review settings...", lambda e: _open_info(
                "Review settings", "Review settings are not implemented yet.")),
            ("Presentation &settings...", lambda e: _open_info(
                "Presentation settings", "Presentation settings are not implemented yet.")),
            ("Browse &mode settings...", lambda e: _open_info(
                "Browse mode settings", "Browse mode settings are not implemented yet.")),
            ("&Advanced settings...", lambda e: _open_info(
                "Advanced settings", "Advanced settings are not implemented yet.")),
        ])),
        ("&Tools", open_sub("Tools", [
            ("&View log", lambda e: _view_log()),
            ("&Speech viewer", lambda e: _toggle_speech()),
            ("&Restart screen reader", lambda e: _restart()),
        ])),
        ("&Help", open_sub("Help", [
            ("&User guide", lambda e: _speak("Opening user guide")),
            ("Commands &quick reference", lambda e: _speak("Opening commands quick reference")),
            ("&What's new", lambda e: _speak("Opening what's new")),
            ("&About TechReader", lambda e: _about()),
        ])),
        None,
        ("E&xit", lambda e: _do_exit()),
        ("Close", lambda e: _hide_menu()),
    ], lambda: None)

    sizer.Layout()
    _menu_frame.SetTitle("TechReader Menu")
    if speak and _menu_frame.IsShown():
        _speak("TechReader menu")


def _build_menu():
    global _menu_frame
    _menu_frame = wx.Frame(None, title="TechReader Menu",
                           style=wx.DEFAULT_FRAME_STYLE & ~(wx.MAXIMIZE_BOX | wx.MINIMIZE_BOX))
    panel = wx.Panel(_menu_frame)
    sizer = wx.BoxSizer(wx.VERTICAL)
    panel.SetSizer(sizer)
    _menu_frame.Bind(wx.EVT_CHAR_HOOK, _on_menu_key)
    _show_main()
    _menu_frame.Fit()
    _menu_frame.Centre()


def _get_nav_buttons():
    """Visible buttons of the current menu view, in on-screen order."""
    if _menu_frame is None:
        return []
    panel = _menu_frame.GetChildren()[0]
    return [c for c in panel.GetChildren()
            if isinstance(c, wx.Button) and c.IsShown()]


def _focused_button_index(buttons):
    for i, btn in enumerate(buttons):
        if btn.HasFocus():
            return i
    return None


def _move_menu_focus(step):
    """Move keyboard focus between menu buttons (wrapping).

    Only focus is moved: the item is announced by the app's normal UIA
    focus-changed pipeline, exactly as when navigating with Tab.
    """
    buttons = _get_nav_buttons()
    if not buttons:
        return
    count = len(buttons)
    current = _focused_button_index(buttons)
    if current is None:
        target = 0  # nothing focused yet: start at the top item
    else:
        target = (current + step) % count
    buttons[target].SetFocus()


def _on_menu_key(event):
    """Arrow keys navigate the menu; all other keys behave as usual.

    Enter/Space keep activating the focused button and Tab keeps cycling
    because those events are passed through with Skip().
    """
    code = event.GetKeyCode()
    if code in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_LEFT, wx.WXK_RIGHT):
        step = -1 if code in (wx.WXK_UP, wx.WXK_LEFT) else 1
        _move_menu_focus(step)
        return  # consumed: the focus change itself announces the item
    event.Skip()


def _close_menu_for_action():
    """Reset the menu to the main view and hide it silently (before actions).

    The panel is rebuilt so reopening the menu shows the main menu, not the
    stale submenu the action was launched from.
    """
    if _menu_frame is not None:
        _show_main(speak=False)
        _menu_frame.Hide()


def _hide_menu():
    _menu_frame.Hide()


def _do_exit():
    _speak("Exiting TechReader")
    print("Exiting...")
    _play_sound("exit.wav")
    sys.exit()


def _play_sound(name):
    try:
        winsound.PlaySound(os.path.join(SRC_DIR, name), winsound.SND_FILENAME)
    except Exception:
        pass


def show_menu():
    if _menu_frame is None:
        return
    if _menu_frame.IsShown():
        _hide_menu()
        return
    if _last_sub is not None:
        _show_main()
    _menu_frame.Show()
    _menu_frame.Raise()
    _menu_frame.SetFocus()
    _speak("TechReader menu")


def process_wx_events():
    wx.Yield()


# ---------------------------------------------------------------------------
# Speech viewer
# ---------------------------------------------------------------------------

def _toggle_speech():
    global _speech_viewer_frame, _speech_viewer_text
    if _speech_viewer_frame is not None and _speech_viewer_frame.IsShown():
        _speech_viewer_frame.Hide()
        _set_viewer_listener(None)
        _speak("Speech viewer disabled")
        return
    if _speech_viewer_frame is None:
        _speech_viewer_frame = wx.Frame(None, title="Speech viewer", size=(520, 360))
        _speech_viewer_text = wx.TextCtrl(_speech_viewer_frame,
                                          style=wx.TE_MULTILINE | wx.TE_READONLY)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(_speech_viewer_text, 1, wx.EXPAND)
        _speech_viewer_frame.SetSizer(sizer)
    _speech_viewer_frame.Show()
    _speech_viewer_frame.Raise()
    _set_viewer_listener(_on_utterance)
    _speak("Speech viewer enabled")


def _set_viewer_listener(callback):
    if _speech_manager is not None:
        _speech_manager.set_utterance_listener(callback)


def _on_utterance(text):
    """Called from the speech worker thread; marshal to the wx main thread."""
    wx.CallAfter(_append_viewer_text, text)


def _append_viewer_text(text):
    if _speech_viewer_text is None:
        return
    _speech_viewer_text.AppendText(text + "\n")


# ---------------------------------------------------------------------------
# Preferences dialogs
# ---------------------------------------------------------------------------

def _open_speech_settings():
    dlg = SpeechSettingsDialog(_menu_frame, _speech_manager)
    dlg.ShowModal()
    dlg.Destroy()


def _open_output_settings():
    _open_toggle_dialog("Output settings", [
        ("Announce element roles", "speak_roles"),
        ("Announce element states", "speak_states"),
    ])


def _open_object_presentation():
    _open_toggle_dialog("Object presentation", [
        ("Announce element roles", "speak_roles"),
        ("Announce element states", "speak_states"),
    ])


def _open_keyboard_settings():
    _open_toggle_dialog("Keyboard settings", [
        ("CapsLock+Space opens the menu", "menu_hotkey_enabled"),
    ])


def _open_toggle_dialog(title, options):
    _speak(title)
    dlg = wx.Dialog(_menu_frame, title=title)
    panel = wx.Panel(dlg)
    sizer = wx.BoxSizer(wx.VERTICAL)
    checks = []
    for label, attr in options:
        cb = wx.CheckBox(panel, label=label)
        cb.SetValue(bool(getattr(settings, attr)))
        cb.Bind(wx.EVT_CHECKBOX,
                lambda e, c=cb: _speak("checked" if c.GetValue() else "unchecked"))
        _bind_focus_speech(cb, label)
        checks.append((cb, attr))
        sizer.Add(cb, 0, wx.ALL, 6)
    sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 6)
    btn_ok = wx.Button(panel, wx.ID_OK, "&OK")
    btn_cancel = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
    _bind_focus_speech(btn_ok, "OK")
    _bind_focus_speech(btn_cancel, "Cancel")
    btn_ok.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_OK))
    btn_cancel.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_CANCEL))
    row = wx.BoxSizer(wx.HORIZONTAL)
    row.Add(btn_ok, 0, wx.RIGHT, 8)
    row.Add(btn_cancel)
    sizer.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)
    panel.SetSizer(sizer)
    dlg.Fit()
    if dlg.ShowModal() == wx.ID_OK:
        for cb, attr in checks:
            setattr(settings, attr, cb.GetValue())
        _speak("Settings applied")
    dlg.Destroy()


def _open_info(title, description):
    _speak(title)
    dlg = wx.Dialog(_menu_frame, title=title)
    panel = wx.Panel(dlg)
    sizer = wx.BoxSizer(wx.VERTICAL)
    sizer.Add(wx.StaticText(panel, label=description), 0, wx.ALL, 8)
    btn_ok = wx.Button(panel, wx.ID_OK, "&OK")
    _bind_focus_speech(btn_ok, "OK")
    btn_ok.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_OK))
    sizer.Add(btn_ok, 0, wx.ALIGN_CENTER | wx.ALL, 8)
    panel.SetSizer(sizer)
    dlg.Fit()
    dlg.ShowModal()
    dlg.Destroy()


def _view_log():
    log_path = os.path.join(SRC_DIR, "runtime.log")
    if not os.path.exists(log_path):
        _speak("No log file found")
        return
    try:
        with open(log_path, "rb") as f:
            raw = f.read()
        if raw.startswith(b"\xff\xfe") or b"\x00" in raw[:128]:
            text = raw.decode("utf-16-le", errors="replace")
        else:
            text = raw.decode("utf-8", errors="replace")
    except Exception:
        text = "Unable to read log file"
    _speak("Log viewer")
    dlg = wx.Dialog(_menu_frame, title="Screenreader log", size=(640, 420))
    panel = wx.Panel(dlg)
    sizer = wx.BoxSizer(wx.VERTICAL)
    tc = wx.TextCtrl(panel, style=wx.TE_MULTILINE | wx.TE_READONLY, value=text)
    sizer.Add(tc, 1, wx.EXPAND | wx.ALL, 6)
    btn_ok = wx.Button(panel, wx.ID_OK, "&Close")
    _bind_focus_speech(btn_ok, "Close")
    btn_ok.Bind(wx.EVT_BUTTON, lambda e: dlg.EndModal(wx.ID_OK))
    sizer.Add(btn_ok, 0, wx.ALIGN_CENTER | wx.ALL, 6)
    panel.SetSizer(sizer)
    dlg.ShowModal()
    dlg.Destroy()


def _about():
    _speak("About TechReader")
    dlg = wx.MessageDialog(
        _menu_frame,
        "TechReader\n\nA screen reader for Windows with support for Qt and "
        "TeamTalk 5.\nPress Ctrl to interrupt speech.\nPress CapsLock+Space "
        "to open this menu.",
        "About TechReader", wx.OK)
    dlg.ShowModal()
    dlg.Destroy()


def _restart():
    _speak("Restarting screen reader")
    _play_sound("exit.wav")
    if getattr(sys, "frozen", False):
        cmd = [sys.executable]
    else:
        cmd = [sys.executable, os.path.join(SRC_DIR, "main.py")]
    try:
        subprocess.Popen(cmd, cwd=PROJECT_ROOT, close_fds=True)
    except Exception as e:
        print(f"Restart failed: {e}")
        _speak("Restart failed")
        return
    # Give the restart message a moment to be spoken, then exit for real.
    threading.Timer(0.6, lambda: os._exit(0)).start()


class SpeechSettingsDialog(wx.Dialog):
    def __init__(self, parent, speech_manager):
        super().__init__(parent, title="Speech settings")
        self.speech_manager = speech_manager
        driver = getattr(speech_manager, "driver", None) if speech_manager else None

        panel = wx.Panel(self)
        sizer = wx.BoxSizer(wx.VERTICAL)

        # Voice
        row_voice = wx.BoxSizer(wx.HORIZONTAL)
        lbl_voice = wx.StaticText(panel, label="&Voice:")
        self.voice_combo = wx.ComboBox(panel, style=wx.CB_READONLY)
        voices = []
        current = None
        if driver is not None:
            try:
                voices = driver.list_voices() or []
            except Exception:
                voices = []
            try:
                current = driver.get_voice()
            except Exception:
                current = None
        self.voice_combo.SetItems(voices)
        if current in voices:
            self.voice_combo.SetValue(current)
        elif voices:
            self.voice_combo.SetValue(voices[0])
        self.voice_combo.Bind(wx.EVT_COMBOBOX,
                              lambda e: _speak(self.voice_combo.GetValue()))
        _bind_focus_speech(self.voice_combo, "Voice selection")
        row_voice.Add(lbl_voice, 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 6)
        row_voice.Add(self.voice_combo, 1, wx.ALL, 6)
        sizer.Add(row_voice, 0, wx.EXPAND)

        # Rate (-10 .. 10)
        sizer.Add(wx.StaticText(panel, label="&Rate:"), 0, wx.ALL, 6)
        self.rate_slider = wx.Slider(panel, minValue=-10, maxValue=10)
        try:
            self.rate_slider.SetValue(driver.get_rate() if driver else 0)
        except Exception:
            pass
        self.rate_slider.Bind(wx.EVT_SLIDER,
                              lambda e: _speak(f"Rate {self.rate_slider.GetValue()}"))
        _bind_focus_speech(self.rate_slider, "Rate slider")
        sizer.Add(self.rate_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Volume (0 .. 100)
        sizer.Add(wx.StaticText(panel, label="&Volume:"), 0, wx.ALL, 6)
        self.volume_slider = wx.Slider(panel, minValue=0, maxValue=100)
        try:
            self.volume_slider.SetValue(driver.get_volume() if driver else 100)
        except Exception:
            pass
        self.volume_slider.Bind(wx.EVT_SLIDER,
                                lambda e: _speak(f"Volume {self.volume_slider.GetValue()}"))
        _bind_focus_speech(self.volume_slider, "Volume slider")
        sizer.Add(self.volume_slider, 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)

        # Buttons
        sizer.Add(wx.StaticLine(panel), 0, wx.EXPAND | wx.ALL, 6)
        btn_test = wx.Button(panel, label="&Test voice")
        btn_ok = wx.Button(panel, wx.ID_OK, "&OK")
        btn_cancel = wx.Button(panel, wx.ID_CANCEL, "&Cancel")
        _bind_focus_speech(btn_test, "Test voice")
        _bind_focus_speech(btn_ok, "OK")
        _bind_focus_speech(btn_cancel, "Cancel")
        btn_test.Bind(wx.EVT_BUTTON, self._on_test)
        btn_ok.Bind(wx.EVT_BUTTON, lambda e: (self._apply(), self.EndModal(wx.ID_OK)))
        btn_cancel.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        row = wx.BoxSizer(wx.HORIZONTAL)
        row.Add(btn_test, 0, wx.RIGHT, 8)
        row.Add(btn_ok, 0, wx.RIGHT, 8)
        row.Add(btn_cancel)
        sizer.Add(row, 0, wx.ALIGN_CENTER | wx.ALL, 6)

        panel.SetSizer(sizer)
        sizer.Fit(self)
        self.CentreOnParent()
        _speak("Speech settings dialog")

    def _apply(self):
        driver = getattr(self.speech_manager, "driver", None) if self.speech_manager else None
        if driver is None:
            return
        try:
            desc = self.voice_combo.GetValue()
            if desc:
                driver.set_voice(desc)
            driver.set_rate(self.rate_slider.GetValue())
            driver.set_volume(self.volume_slider.GetValue())
        except Exception as e:
            print(f"Apply speech settings error: {e}")

    def _on_test(self, e):
        self._apply()
        if self.speech_manager is not None:
            self.speech_manager.speak("Testing one two three")