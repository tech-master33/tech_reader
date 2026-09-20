"""Announcement handlers for UIA automation events.

Each event type gets a small pure function that maps a UIA element to the
text TechReader should speak (or None to stay silent). The COM handler
classes below are deliberately thin: receive event, describe, speak, and
never let an exception escape into the UIA event thread.

One handler instance is registered per event id -- comtypes COM objects
cannot be reused across multiple registrations (the second Add* call fails
with an interface QI error on this machine's typelib build).

Noise control:
* Window opened/closed events fire for every top-level window creation,
  including invisible IME helper windows; only named, visible windows are
  announced.
* A short-window duplicate filter suppresses the event echo some providers
  emit (same text twice within a fraction of a second).
"""

import os
import time

import comtypes
from comtypes import COMObject
import comtypes.gen.UIAutomationClient as UIA

import uia_core

# This comtypes build does not generate UIA_DialogControlTypeId; fall back
# to the well-known value (same pattern as the property-id fallbacks in
# focus_handler.py).
try:
    DIALOG_TYPE_ID = UIA.UIA_DialogControlTypeId
except AttributeError:
    DIALOG_TYPE_ID = 50027  # UIA_DialogControlTypeId

# Seconds within which an identical announcement is treated as an event echo.
_DEDUPE_WINDOW = 0.4

# Window class/name noise that must never be announced.
_WINDOW_NOISE_NAMES = {"Default IME", "MSCTFIME UI", "MSO_WAVELINE"}


def _is_own_process(element):
    """True when the element belongs to TechReader itself.

    TechReader's own menu frame, dialogs and the speech viewer already
    announce themselves explicitly ("TechReader menu", dialog titles, focus
    speech on the controls). The window announcer must stay silent for them:
    they are not other applications' windows, and the extra window
    announcement made the menu sound like a window instead of a menu.
    """
    try:
        return element.CurrentProcessId == os.getpid()
    except Exception:
        return False


def _should_speak(text, _state={"text": None, "time": 0.0}):
    now = time.monotonic()
    if text == _state["text"] and (now - _state["time"]) < _DEDUPE_WINDOW:
        return False
    _state["text"] = text
    _state["time"] = now
    return True


def _element_name(element):
    try:
        return (element.CurrentName or "").strip()
    except Exception:
        return ""


def _first_named_child(element):
    """Tooltips often carry their text on a child label, not the element."""
    try:
        walker = uia_core.get_automation().RawViewWalker
        child = walker.GetFirstChildElement(element)
        for _ in range(3):
            if child is None:
                break
            name = _element_name(child)
            if name:
                return name
            child = walker.GetNextSiblingElement(child)
    except Exception:
        pass
    return ""


def _element_role(element):
    """Short role word for the element, or empty for unknown/silent types."""
    from focus_handler import UIA_ROLES
    try:
        return UIA_ROLES.get(element.CurrentControlType, "")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Per-event announcer functions: element -> text to speak (or None)
# ---------------------------------------------------------------------------

def announce_menu_opened(element):
    name = _element_name(element)
    try:
        control_type = element.CurrentControlType
    except Exception:
        control_type = 0
    if control_type == UIA.UIA_MenuItemControlTypeId:
        # Context menus raise the event on their first item; the focus
        # handler announces the item itself, so only add the context here
        # when the focus event is not expected to fire.
        return f"{name} menu item" if name else None
    if not name:
        return None  # unnamed context menu; item focus speech takes over
    return f"{name} menu"


def announce_menu_closed(_element):
    return "menu closed"


def announce_tooltip_opened(element):
    name = _element_name(element) or _first_named_child(element)
    return name or None


def announce_window_opened(element):
    if _is_own_process(element):
        return None
    name = _element_name(element)
    if not name or name in _WINDOW_NOISE_NAMES:
        return None
    try:
        if name in _WINDOW_NOISE_NAMES or element.CurrentClassName in ("Ghost", "SysShadow"):
            return None
        if element.CurrentIsOffscreen:
            return None
        control_type = element.CurrentControlType
    except Exception:
        return None
    if control_type == DIALOG_TYPE_ID:
        return f"{name} dialog"
    return f"{name} window"


def announce_window_closed(element):
    if _is_own_process(element):
        return None
    name = _element_name(element)
    if not name or name in _WINDOW_NOISE_NAMES:
        return None
    return f"{name} closed"


# ---------------------------------------------------------------------------
# COM handler classes
# ---------------------------------------------------------------------------

class AutomationEventHandler(COMObject):
    """IUIAutomationEventHandler dispatching to one announcer function."""

    _com_interfaces_ = [UIA.IUIAutomationEventHandler]

    def __init__(self, callback, announce):
        super().__init__()
        self.callback = callback
        self._announce = announce

    def HandleAutomationEvent(self, sender, event_id):
        try:
            element = sender.QueryInterface(UIA.IUIAutomationElement)
            text = self._announce(element)
            if text and _should_speak(text):
                self.callback(text)
        except Exception:
            pass


class NotificationEventHandler(COMObject):
    """Speaks UIA notification events (the modern live-region mechanism).

    Applications push user-facing notifications here -- displayString holds
    the announced text, activityId a machine-readable identifier that some
    providers put useful context in (only used when the text is missing).
    """

    _com_interfaces_ = [UIA.IUIAutomationNotificationEventHandler]

    def __init__(self, callback):
        super().__init__()
        self.callback = callback

    def HandleNotificationEvent(self, sender, notification_kind,
                                notification_processing, display_string,
                                activity_id):
        try:
            text = (display_string or "").strip()
            if not text and activity_id:
                text = str(activity_id).strip()
            if text and _should_speak(text):
                self.callback(text)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# (event id, announcer, settings flag) for the generic automation events.
_ANNOUNCED_EVENTS = [
    (UIA.UIA_MenuOpenedEventId, announce_menu_opened, "announce_menus"),
    (UIA.UIA_MenuClosedEventId, announce_menu_closed, "announce_menus"),
    (UIA.UIA_ToolTipOpenedEventId, announce_tooltip_opened, "announce_tooltips"),
    (UIA.UIA_Window_WindowOpenedEventId, announce_window_opened, "announce_windows"),
    (UIA.UIA_Window_WindowClosedEventId, announce_window_closed, "announce_windows"),
]

# Module-level references so the COM objects stay alive while registered.
_active_handlers = []


def register_events(callback):
    """Register every announcement event whose settings flag is enabled.

    Returns a list of human-readable labels for what was registered, for
    the startup log. Failures are reported per feature and never fatal:
    the reader keeps running without that announcement type.
    """
    import settings

    registered = []
    for event_id, announcer, flag in _ANNOUNCED_EVENTS:
        if not getattr(settings, flag, True):
            continue
        try:
            handler = AutomationEventHandler(callback, announcer)
            uia_core.add_automation_event_handler(event_id, handler)
            _active_handlers.append(handler)
            registered.append(flag)
        except Exception as exc:
            print(f"Event announcements unavailable ({flag}): {exc}")
    if getattr(settings, "announce_notifications", True):
        try:
            handler = NotificationEventHandler(callback)
            uia_core.add_notification_event_handler(handler)
            _active_handlers.append(handler)
            registered.append("announce_notifications")
        except Exception as exc:
            print(f"Notification announcements unavailable: {exc}")
    return registered
