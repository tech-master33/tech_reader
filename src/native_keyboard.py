"""Native keyboard bridge for TechReader.

Loads techreader_keyboard.dll (src/native) and turns its low-level keyboard
events into TechReader commands. This module is the ONLY place where native
keyboard events are interpreted; the C layer just detects and describes.

Contract (mirrors src/native/trk_keyboards.h):
  - The DLL calls our sink synchronously on its hook thread. The sink only
    copies the event and queues it -- it must never block or call UIA/wx,
    because Windows unbinds hooks that stall.
  - A pump thread drains the queue and performs the TechReader commands, so
    speech/UIA/wx work happens away from the hook thread.
  - Injected (synthetic) events are ignored for command purposes: they carry
    TRK_FLAG_INJECTED and must never trigger Ctrl interrupt or CapsLock+Space,
    which prevents feedback loops (TechReader's own or other tools' injected
    keys can never command TechReader).

Behavior parity with the python-keyboard implementation:
  - Ctrl (either Control key) down  -> speech interrupt (key repeat and
    re-press both re-trigger; key-up does nothing).
  - CapsLock + Space (Space key-down while Caps Lock is held) -> menu toggle
    (wx.CallAfter). Works whether Caps Lock is currently on or off; the
    Caps Lock toggle state is never changed.
  - No key is ever suppressed: the hook always passes events on, so normal
    typing is untouched.
"""

import ctypes
from ctypes import (c_void_p, c_int, c_uint32, c_uint64,
                    POINTER, Structure)
import os
import queue
import threading

# --- constants mirrored from trk_keyboards.h -------------------------------

TRK_OK = 0
TRK_ERR_ALREADY_RUNNING = -2

TRK_KEY_DOWN = 0
TRK_KEY_UP = 1
TRK_SYS_KEY_DOWN = 2
TRK_SYS_KEY_UP = 3

TRK_MOD_LCTRL = 1 << 0
TRK_MOD_RCTRL = 1 << 1
TRK_MOD_LSHIFT = 1 << 2
TRK_MOD_RSHIFT = 1 << 3
TRK_MOD_LALT = 1 << 4
TRK_MOD_RALT = 1 << 5
TRK_MOD_LWIN = 1 << 6
TRK_MOD_RWIN = 1 << 7
TRK_MOD_CAPS = 1 << 8      # Caps Lock key physically held
TRK_MOD_NUM = 1 << 9       # Num Lock key physically held
TRK_MOD_CAPS_ON = 1 << 10  # Caps Lock toggle lamp on
TRK_MOD_NUM_ON = 1 << 11   # Num Lock toggle lamp on

TRK_FLAG_EXTENDED = 1 << 0
TRK_FLAG_INJECTED = 1 << 1
TRK_FLAG_LOWER_IL_INJECTED = 1 << 2
TRK_FLAG_ALT_DOWN = 1 << 3
TRK_FLAG_TRANSITION = 1 << 4

VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_CONTROL = 0x11
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_SPACE = 0x20
VK_CAPITAL = 0x14

DLL_NAME = "techreader_keyboard.dll"


# --- ABI structures (layout must match trk_keyboards.h) ---------------------

class TrkKeyboardEvent(Structure):
    _fields_ = [
        ("event_type", c_uint32),
        ("vk", c_uint32),
        ("scan_code", c_uint32),
        ("flags", c_uint32),
        ("time_ms", c_uint64),
        ("modifier_state", c_uint32),
        ("reserved", c_uint32),
    ]


SINK_FUNC = ctypes.WINFUNCTYPE(
    c_int,                        # return (reserved; ignored by the DLL)
    POINTER(TrkKeyboardEvent),    # const TrkKeyboardEvent *
    c_void_p,                     # user context
)


def _dll_path():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "native", DLL_NAME)


def is_available():
    """True when the native keyboard DLL exists (whether or not it loads)."""
    return os.path.exists(_dll_path())


# --- command layer ----------------------------------------------------------
#
# The detector is deliberately data-driven and side-effect-free so it can be
# unit-tested without any hooks: _detect_command(event_dict) -> command or
# None. start()/stop() only manage the plumbing around it.

CTRL_KEYS = (VK_LCONTROL, VK_RCONTROL)


def detect_command(ev):
    """Map one described keyboard event to a TechReader command name.

    ev is a plain dict with the fields of TrkKeyboardEvent. Returns a string
    command name or None. Pure function: no I/O, no state.

    Rules:
      - Injected events never produce commands (feedback-loop guard).
      - Control key DOWN -> 'interrupt' (repeat/re-press re-trigger;
        key-up does nothing).
      - Space key DOWN with Caps Lock held -> 'menu' (CapsLock+Space).
        Works whether the Caps Lock lamp is on or off; the Win keys are
        explicitly not required.
    """
    if ev.get("flags", 0) & TRK_FLAG_INJECTED:
        return None

    event_type = ev.get("event_type", 0)
    if event_type not in (TRK_KEY_DOWN, TRK_SYS_KEY_DOWN):
        return None
    vk = ev.get("vk", 0)
    mods = ev.get("modifier_state", 0)

    if vk in CTRL_KEYS:
        return "interrupt"

    if vk == VK_SPACE and (mods & TRK_MOD_CAPS):
        return "menu"

    return None


class NativeKeyboard:
    """Owns the native hook and turns its events into TechReader commands.

    Commands are dispatched as on_command(command_name) calls on a pump
    thread (never on the hook thread). on_error(exception) is called if the
    hook thread bridge fails; it is safe to pass None.
    """

    def __init__(self, on_command, on_error=None):
        self._on_command = on_command
        self._on_error = on_error
        self._dll = None
        self._sink = None            # keep the ctypes callback alive
        self._queue = queue.Queue()
        self._pump = None
        self._running = False
        self._user_context_id = id(self)

    # -- sink (hook thread) --------------------------------------------------

    def _sink_impl(self, event_ptr, user_context):
        """Runs on the DLL's hook thread. Copy and queue; never block."""
        try:
            ev = event_ptr[0]
            # Copy into immutable data so the pump never touches the
            # (transient) native memory.
            item = {
                "event_type": ev.event_type,
                "vk": ev.vk,
                "scan_code": ev.scan_code,
                "flags": ev.flags,
                "time_ms": ev.time_ms,
                "modifier_state": ev.modifier_state,
            }
            self._queue.put_nowait(item)
        except Exception:
            # Never raise across the C boundary and never stall the hook.
            pass
        return 0

    # -- pump thread ---------------------------------------------------------

    def _pump_loop(self):
        while self._running:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                command = detect_command(item)
                if command is not None:
                    self._on_command(command)
            except Exception as exc:
                if self._on_error is not None:
                    try:
                        self._on_error(exc)
                    except Exception:
                        pass

    # -- lifecycle -----------------------------------------------------------

    def start(self):
        """Load the DLL and install the hook. Returns True on success.

        On any failure the object is left fully stopped, so the caller can
        fall back to the python-keyboard implementation.
        """
        if self._running:
            return True
        try:
            dll = ctypes.WinDLL(_dll_path())
            dll.trk_keyboard_start.argtypes = [SINK_FUNC, c_void_p]
            dll.trk_keyboard_start.restype = c_int
            dll.trk_keyboard_stop.argtypes = []
            dll.trk_keyboard_stop.restype = None
            dll.trk_keyboard_is_running.argtypes = []
            dll.trk_keyboard_is_running.restype = c_int

            self._sink = SINK_FUNC(self._sink_impl)
            rc = dll.trk_keyboard_start(self._sink, None)
            if rc != TRK_OK:
                self._sink = None
                return False
            self._dll = dll
            self._running = True
            self._pump = threading.Thread(target=self._pump_loop,
                                          name="trk-keyboard-pump",
                                          daemon=True)
            self._pump.start()
            return True
        except Exception:
            self._sink = None
            self._dll = None
            return False

    def stop(self):
        """Uninstall the hook and join the pump thread."""
        self._running = False
        if self._dll is not None:
            try:
                self._dll.trk_keyboard_stop()
            except Exception:
                pass
            self._dll = None
        self._sink = None
        if self._pump is not None and self._pump is not threading.current_thread():
            self._pump.join(timeout=2.0)
        self._pump = None

    @property
    def running(self):
        if self._dll is None or not self._running:
            return False
        try:
            return bool(self._dll.trk_keyboard_is_running())
        except Exception:
            return False
