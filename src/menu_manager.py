"""TechReader's menu: a real wx.Menu popup.

The previous menu was a wx.Frame full of buttons, so to every other app
(including TechReader's own UIA announcers) it looked and behaved like a
window, not a menu. It is now a genuine popup wx.Menu with submenus:
Windows handles arrow navigation, Enter activation and Escape dismissal.
Because classic Win32 menus raise no UIA focus events, each highlighted
item is announced through the native WM_MENUSELECT notification
(EVT_MENU_HIGHLIGHT) instead.

Selected actions run after the popup is dismissed (menus must not stay
open while modal dialogs run). The dialog and speech-viewer
infrastructure below the menu code is unchanged from the previous
implementation.
"""

import os
import subprocess
import sys
import threading
import time
import winsound
import wx

import config
import settings

app = None
_speech_callback = None
_speech_manager = None
_owner_frame = None       # hidden frame that parents the popup menu and dialogs
_menu = None              # the currently open wx.Menu, or None while it shows
_last_closed_at = 0.0     # guard against a queued hotkey press reopening it
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
    global app, _owner_frame, _speech_manager
    set_speech_callback(speech_callback)
    _speech_manager = speech_manager
    app = wx.App(False)
    # A wx.Menu needs a parent window; a never-shown frame is the standard
    # parent. It is never displayed, so nothing ever announces it.
    _owner_frame = wx.Frame(None, title="TechReader",
                            style=wx.FRAME_NO_TASKBAR)
    # Position the (hidden) frame at the screen centre so the popup menu
    # opens there, like the old centred menu window did.
    try:
        scr = wx.GetClientDisplayRect()
        _owner_frame.SetPosition((scr.x + scr.width // 2,
                                  scr.y + scr.height // 2))
    except Exception:
        pass


def _bind_focus_speech(ctrl, text):
    """Speak a control's label when it receives keyboard focus.

    Used inside dialogs, where UIA focus events are not pumped while the
    dialog's modal loop is running.
    """
    try:
        ctrl.Bind(wx.EVT_SET_FOCUS, lambda e: _speak(text))
    except Exception:
        pass


def _menu_definition():
    """(label, [(label, action), ...]) submenus of the TechReader menu."""
    return [
        ("&Preferences", [
            ("&Settings...", lambda e: _open_settings()),
        ]),
        ("&Tools", [
            ("&View log", lambda e: _view_log()),
            ("&Speech viewer", lambda e: _toggle_speech()),
            ("&Restart screen reader", lambda e: _restart()),
        ]),
        ("&Help", [
            ("&User guide", lambda e: _speak("Opening user guide")),
            ("Commands &quick reference", lambda e: _speak("Opening commands quick reference")),
            ("&What's new", lambda e: _speak("Opening what's new")),
            ("&About TechReader", lambda e: _about()),
        ]),
    ]


class _MenuBuilder:
    """Builds the wx.Menu tree, announces highlighted items, and remembers
    the chosen action.

    Item announcements: classic Win32 menus do not raise UIA focus-changed
    events for item navigation, so arrowing through the menu would be
    silent if we relied on the focus pipeline. The native notification for
    keyboard navigation is WM_MENUSELECT, which wx delivers as
    EVT_MENU_HIGHLIGHT; the highlighted item is announced through it.

    Selected item actions do not run immediately: choosing an item closes
    the menu, and the action runs once show_menu() regains control after
    PopupMenu() returns. Dismissing without a selection (Escape or
    clicking away) leaves pending_action None, so nothing runs.
    """

    def __init__(self):
        self.pending_action = None
        self.item_info = {}  # item id -> (label without mnemonic, is submenu)

    def build(self):
        menu = wx.Menu()
        for label, items in _menu_definition():
            sub = self._build_sub(items)
            item = menu.AppendSubMenu(sub, label)
            self._register(item, label, is_submenu=True)
        menu.AppendSeparator()
        self._bind_item(menu, menu.Append(wx.ID_EXIT, "E&xit\tCtrl+Q"),
                        _do_exit)
        self._bind_item(menu, menu.Append(wx.ID_ANY, "&Close menu"),
                        _noop)
        return menu

    def _build_sub(self, items):
        sub = wx.Menu()
        for label, action in items:
            item = sub.Append(wx.ID_ANY, label)
            self._register(item, label, is_submenu=False)
            self._bind_item(sub, item, action)
        return sub

    def _register(self, wx_item, label, is_submenu):
        text = label.replace("&", "")
        if is_submenu:
            text += " submenu"
        self.item_info[wx_item.GetId()] = (text, is_submenu)

    def _bind_item(self, containing_menu, menu_item, action):
        def handler(_event):
            self.pending_action = action
        containing_menu.Bind(wx.EVT_MENU, handler, menu_item)

    def _on_highlight(self, event):
        info = self.item_info.get(event.GetMenuId())
        if info is not None:
            _speak(info[0])
        event.Skip()


def _noop(_event=None):
    pass


def _do_exit(_event=None):
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
    """Toggle the TechReader popup menu (the CapsLock+Space hotkey).

    Escape or clicking away also closes it. Arrowing through the menu is
    announced by the WM_MENUSELECT highlight handler; the menu itself is
    announced here.
    """
    global _menu, _last_closed_at
    if _owner_frame is None:
        return
    if _menu is not None:
        # The popup's native loop may or may not deliver queued hotkey
        # events while it runs; dismiss either way.
        hide_menu()
        return
    if time.monotonic() - _last_closed_at < 0.2:
        # Closed a fraction of a second ago: this press raced the close,
        # so it is the "toggle off" half of a double press, not a reopen.
        return
    _speak("TechReader menu")
    builder = _MenuBuilder()
    menu = builder.build()
    _menu = menu
    _make_owner_foreground()
    # WM_MENUSELECT for a popup menu is delivered to the owner window, so
    # item-highlight announcements must be bound on the owner frame (the
    # menu object itself never sees them). Unbound after closing so that
    # repeated opens do not stack duplicate handlers.
    highlight = builder._on_highlight
    _owner_frame.Bind(wx.EVT_MENU_HIGHLIGHT, highlight)
    try:
        try:
            _owner_frame.PopupMenu(menu, (0, 0))
        except Exception:
            _owner_frame.PopupMenu(menu)
    finally:
        try:
            _owner_frame.Unbind(wx.EVT_MENU_HIGHLIGHT, highlight)
        except Exception:
            pass
    # PopupMenu blocks until the menu is dismissed.
    _menu = None
    _last_closed_at = time.monotonic()
    menu.Destroy()
    action, builder.pending_action = builder.pending_action, None
    if action is not None:
        action(None)


def _make_owner_foreground():
    """Bring the hidden owner window to the foreground before popping up.

    Win32 ignores keyboard input for a popup menu whose owner is not the
    foreground window (the menu opens but arrows/Escape do nothing until
    it is clicked). TechReader may call SetForegroundWindow legitimately:
    the CapsLock+Space keystroke arrives through this process's own
    keyboard hook, so this is the process that received the last input.
    """
    try:
        import ctypes
        hwnd = _owner_frame.GetHandle()
        if not hwnd:
            return
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        fg = user32.GetForegroundWindow()
        our_thread = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        if fg and fg_thread and fg_thread != our_thread:
            # Borrow the foreground thread's input queue so Windows permits
            # the switch even when another app currently has focus.
            user32.AttachThreadInput(our_thread, fg_thread, True)
            try:
                user32.SetForegroundWindow(hwnd)
            finally:
                user32.AttachThreadInput(our_thread, fg_thread, False)
        else:
            user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def hide_menu():
    """Close the popup if it is open (the toggle-off half of the hotkey).

    Escape dismisses one menu level at a time (an open submenu first), so
    two are sent: a submenu closes, then the main menu. Extra Escapes with
    no menu left are harmless.
    """
    if _menu is None:
        return
    try:
        sim = wx.UIActionSimulator()
        sim.Char(wx.WXK_ESCAPE)
        time.sleep(0.12)
        sim.Char(wx.WXK_ESCAPE)
    except Exception:
        pass


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

def _open_settings():
    dlg = SettingsDialog(_owner_frame, _speech_manager)
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
    dlg = wx.Dialog(_owner_frame, title="Screenreader log", size=(640, 420))
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
        _owner_frame,
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


class SettingsDialog(wx.Dialog):
    """NVDA-style settings: one dialog, category list on the left, the
    selected category's options on the right.

    Categories exist only for settings TechReader actually has: Speech,
    Output (focus-description parts), Event announcements, and Keyboard.
    All panels are built once and shown/hidden on switch, so edits made
    in one category survive browsing to another. OK and Apply write every
    category at once; Cancel discards.
    """

    def __init__(self, parent, speech_manager):
        super().__init__(parent, title="TechReader Settings",
                         size=(620, 420))
        self.speech_manager = speech_manager
        _speak("TechReader settings")

        root = wx.BoxSizer(wx.HORIZONTAL)

        # Category list (left)
        self.cat_list = wx.ListBox(self, choices=["Speech", "Output",
                                                  "Event announcements",
                                                  "Keyboard"])
        self.cat_list.SetSelection(0)
        self.cat_list.Bind(wx.EVT_LISTBOX, self._on_category)
        self.cat_list.Bind(wx.EVT_SET_FOCUS,
                           lambda e: _speak(self.cat_list.GetStringSelection()))
        root.Add(self.cat_list, 0, wx.EXPAND | wx.ALL, 6)

        # Panel stack (right)
        self.panel_area = wx.Panel(self)
        area_sizer = wx.BoxSizer(wx.VERTICAL)
        self.panel_area.SetSizer(area_sizer)
        self.panels = {}
        for name, builder in (("Speech", self._make_speech_panel),
                              ("Output", self._make_output_panel),
                              ("Event announcements", self._make_events_panel),
                              ("Keyboard", self._make_keyboard_panel)):
            panel = builder(self.panel_area)
            panel.Hide()
            area_sizer.Add(panel, 1, wx.EXPAND | wx.ALL, 4)
            self.panels[name] = panel

        # Buttons
        btn_ok = wx.Button(self, wx.ID_OK, "&OK")
        btn_cancel = wx.Button(self, wx.ID_CANCEL, "&Cancel")
        btn_apply = wx.Button(self, wx.ID_APPLY, "&Apply")
        _bind_focus_speech(btn_ok, "OK")
        _bind_focus_speech(btn_cancel, "Cancel")
        _bind_focus_speech(btn_apply, "Apply")
        btn_ok.Bind(wx.EVT_BUTTON, lambda e: (self._apply(), self.EndModal(wx.ID_OK)))
        btn_cancel.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
        btn_apply.Bind(wx.EVT_BUTTON, lambda e: self._apply())
        btn_row = wx.BoxSizer(wx.HORIZONTAL)
        btn_row.Add(btn_ok, 0, wx.RIGHT, 6)
        btn_row.Add(btn_cancel, 0, wx.RIGHT, 6)
        btn_row.Add(btn_apply)

        outer = wx.BoxSizer(wx.VERTICAL)
        outer.Add(root, 1, wx.EXPAND)
        outer.Add(wx.StaticLine(self), 0, wx.EXPAND | wx.LEFT | wx.RIGHT, 6)
        outer.Add(btn_row, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
        self.SetSizer(outer)

        self._show_category("Speech")
        self.CentreOnParent()
        self.cat_list.SetFocus()

    # -- category switching ------------------------------------------

    def _show_category(self, name):
        for key, panel in self.panels.items():
            if key == name:
                panel.Show()
            else:
                panel.Hide()
        self.panel_area.Layout()
        self.Layout()

    def _on_category(self, event):
        name = event.GetString()
        self._show_category(name)
        _speak(name)
        event.Skip()

    # -- panel builders ----------------------------------------------

    def _make_speech_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        driver = getattr(self.speech_manager, "driver", None) if self.speech_manager else None

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

        btn_test = wx.Button(panel, label="&Test voice")
        _bind_focus_speech(btn_test, "Test voice")
        btn_test.Bind(wx.EVT_BUTTON, self._on_test)
        sizer.Add(btn_test, 0, wx.ALIGN_CENTER | wx.ALL, 6)

        panel.SetSizer(sizer)
        return panel

    def _make_output_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for label, attr in [
            ("Announce element roles", "speak_roles"),
            ("Announce element states", "speak_states"),
            ("Announce keyboard shortcuts", "speak_accelerators"),
            ("Announce password protection", "speak_password_state"),
            ("Announce position in list, x of y", "speak_position_in_set"),
            ("Announce table row and column", "speak_table_positions"),
            ("Announce help text", "speak_help_text"),
        ]:
            sizer.Add(self._make_check(panel, label, attr), 0, wx.ALL, 6)
        panel.SetSizer(sizer)
        return panel

    def _make_events_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        for label, attr in [
            ("Announce menus", "announce_menus"),
            ("Announce tooltips", "announce_tooltips"),
            ("Announce windows and dialogs", "announce_windows"),
            ("Announce notifications", "announce_notifications"),
        ]:
            sizer.Add(self._make_check(panel, label, attr), 0, wx.ALL, 6)
        panel.SetSizer(sizer)
        return panel

    def _make_keyboard_panel(self, parent):
        panel = wx.Panel(parent)
        sizer = wx.BoxSizer(wx.VERTICAL)
        sizer.Add(self._make_check(panel,
                                   "CapsLock+Space opens the menu",
                                   "menu_hotkey_enabled"), 0, wx.ALL, 6)
        panel.SetSizer(sizer)
        return panel

    def _make_check(self, panel, label, attr):
        cb = wx.CheckBox(panel, label=label)
        cb._trk_attr = attr  # read back in _apply()
        cb.SetValue(bool(getattr(settings, attr)))
        cb.Bind(wx.EVT_CHECKBOX,
                lambda e, c=cb: _speak("checked" if c.GetValue() else "unchecked"))
        _bind_focus_speech(cb, label)
        return cb

    # -- applying ------------------------------------------------------

    def _apply(self):
        updates = {}
        driver = getattr(self.speech_manager, "driver", None) if self.speech_manager else None
        if driver is not None:
            try:
                desc = self.voice_combo.GetValue()
                if desc:
                    driver.set_voice(desc)
                driver.set_rate(self.rate_slider.GetValue())
                driver.set_volume(self.volume_slider.GetValue())
                updates["voice"] = driver.get_voice()
                updates["rate"] = driver.get_rate()
                updates["volume"] = driver.get_volume()
            except Exception as e:
                print(f"Apply speech settings error: {e}")
        for panel in self.panels.values():
            for cb in panel.GetChildren():
                if isinstance(cb, wx.CheckBox):
                    # The label is the human text; map back via stored attr.
                    attr = getattr(cb, "_trk_attr", None)
                    if attr:
                        value = cb.GetValue()
                        setattr(settings, attr, value)
                        updates[attr] = value
        if updates:
            config.save(**updates)
        _speak("Settings applied")

    def _on_test(self, e):
        self._apply()
        if self.speech_manager is not None:
            self.speech_manager.speak("Testing one two three")