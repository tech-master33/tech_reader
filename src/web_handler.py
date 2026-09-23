"""Web (browser) content support for TechReader.

Chromium browsers -- Edge and Chrome, plus every Electron app (VS Code,
Slack, Discord) and WebView2 host -- keep their accessibility tree asleep
until an assistive technology performs the WM_GETOBJECT handshake on the
window that renders web content (class ``Chrome_RenderWidgetHostHWND``).
Without that handshake the whole page is invisible to UIA: the document
element exists but has no children, and TextPattern fails with
CONNECT_E_NOCONNECTION. Screen readers that ignore this appear to have
"no web support" at all.

This module:

* ``wake_web_content(element)`` -- called when focus lands inside a
  Chromium framework element. Walks to the owning top-level window and
  pokes its renderer windows exactly once per window (throttled; the
  handshake is a cached-no-op afterwards). The page's UIA tree then
  builds itself within a second or two.
* ``get_web_parts(element)`` -- web-specific announcement parts for the
  focus handler: heading levels ("heading, level 2") and landmark regions
  ("main landmark"). Chromium exposes both as element properties.

Detection note (verified live on Edge): web elements report
``FrameworkId == "Chrome"`` and the document element has no
``NativeWindowHandle``, so the waker walks raw-view parents up to the
first window-class ancestor and enumerates its renderer children.

All helpers fail soft: any error means "not web" or "no parts", so the
reader keeps working on non-web apps exactly as before.
"""

import ctypes
import time
from ctypes import wintypes

# Ids resolved lazily from the UIA typelib, with literal fallbacks so this
# module also imports in plain probes that never touch uia_core.
FRAMEWORK_PROP_ID = 30012          # UIA_FrameworkIdPropertyId
HEADING_LEVEL_PROP_ID = 30135      # UIA_HeadingLevelPropertyId
LOCALIZED_LANDMARK_PROP_ID = 30158  # UIA_LocalizedLandmarkTypePropertyId

_HEADING_LEVELS = {
    80051: "level 1",
    80052: "level 2",
    80053: "level 3",
    80054: "level 4",
    80055: "level 5",
    80056: "level 6",
    80057: "level 7",
    80058: "level 8",
    80059: "level 9",
}

# WM_GETOBJECT handshake machinery.
_OBJID_CLIENT = 0xFFFFFFFC          # OBJID_CLIENT
_IID_IACCESSIBLE = None             # resolved lazily
_user32 = ctypes.windll.user32
_oleacc = ctypes.windll.oleacc

# hwnd -> monotonic time of last poke. One poke per renderer window is
# enough for the lifetime of the window; re-poke at most every 5 minutes
# in case a window was destroyed and its handle reused.
_LAST_POKE = {}
_POKE_INTERVAL_S = 300.0


def _iid_iaccessible():
    global _IID_IACCESSIBLE
    if _IID_IACCESSIBLE is None:
        import comtypes
        _IID_IACCESSIBLE = comtypes.GUID(
            "{618736E0-3C3D-11CF-810C-00AA00389B71}")
    return _IID_IACCESSIBLE


def is_web_element(element):
    """True when the element comes from a Chromium-rendered page.

    Mirrors the NVDA detection pattern: UIA FrameworkId "Chrome" (covers
    Edge, Chrome, Electron and WebView2 hosts), with a fallback to the
    Chromium renderer window class when the element reports no framework
    (observed on freshly-woken Chromium pages).
    """
    try:
        framework = element.GetCurrentPropertyValue(FRAMEWORK_PROP_ID)
    except Exception:
        framework = None
    if framework:
        return framework.lower() == "chrome"
    # Fallback: an element with no framework id; check its hwnd chain
    # for a Chromium renderer window class.
    try:
        hwnd = element.CurrentNativeWindowHandle
    except Exception:
        hwnd = None
    if hwnd:
        return _is_chromium_hwnd(int(hwnd))
    try:
        import comtypes.gen.UIAutomationClient as UIA
        import uia_core
        parent = uia_core.get_automation().RawViewWalker.GetParentElement(element)
        if parent is None:
            return False
        framework = parent.GetCurrentPropertyValue(FRAMEWORK_PROP_ID)
    except Exception:
        return False
    return bool(framework) and framework.lower() == "chrome"


def _is_chromium_hwnd(hwnd):
    """True when the window (or its ancestor chain) is Chromium renderer."""
    buf = ctypes.create_unicode_buffer(64)
    check = hwnd
    for _ in range(4):
        _user32.GetClassNameW(check, buf, 64)
        if buf.value.startswith("Chrome_"):
            return True
        check = _user32.GetAncestor(check, 1)  # GA_PARENT
        if not check:
            return False
    return False


def wake_web_content(element):
    """Perform the Chromium WM_GETOBJECT handshake for element's window.

    Safe to call on every focus event: non-Chromium elements return
    immediately, and each renderer window is poked at most once. The
    handshake makes the page's accessibility tree (and UIA TextPattern)
    available a second or two later.
    """
    try:
        hwnd = _owning_toplevel_hwnd(element)
        if hwnd is None:
            return
        now = time.monotonic()
        last = _LAST_POKE.get(hwnd)
        if last is not None and (now - last) < _POKE_INTERVAL_S:
            return
        _LAST_POKE[hwnd] = now
        _poke_renderers(hwnd)
    except Exception:
        pass


def _owning_toplevel_hwnd(element):
    """The top-level hwnd hosting element's document, or None.

    The document element itself has no native window handle, so walk the
    raw-view parents to the first ancestor that does.
    """
    import comtypes.gen.UIAutomationClient as UIA
    import uia_core
    walker = uia_core.get_automation().RawViewWalker
    current = element
    for _ in range(16):  # safety depth limit
        try:
            hwnd = current.CurrentNativeWindowHandle
            if hwnd:
                return int(hwnd)
        except Exception:
            pass
        try:
            current = walker.GetParentElement(current)
        except Exception:
            return None
        if current is None:
            return None
    return None


def _poke_renderers(toplevel_hwnd):
    """Send the WM_GETOBJECT handshake to renderer windows under hwnd.

    Both handshake flavors are performed on every renderer window (a
    browser window hosts several, one per WebContents, and the visible
    tab is not necessarily the first): the MSAA flavor
    (AccessibleObjectFromWindow/OBJID_CLIENT) and the UIA flavor
    (ElementFromHandle). The discarded results are the point -- the call
    itself tells Chromium an assistive technology is attached, and it
    then builds the page's accessibility tree (full fidelity once a
    persistent UIA client like TechReader is attached).
    """
    found = []

    @ctypes.WINFUNCTYPE(ctypes.c_int, wintypes.HWND, wintypes.LPARAM)
    def child_cb(hwnd, lparam):
        buf = ctypes.create_unicode_buffer(64)
        _user32.GetClassNameW(hwnd, buf, 64)
        if buf.value == "Chrome_RenderWidgetHostHWND":
            found.append(hwnd)
        return 1

    _user32.EnumChildWindows(toplevel_hwnd, child_cb, 0)
    iid = ctypes.byref(_iid_iaccessible())
    uia = None
    for hwnd in found:
        try:
            punk = ctypes.c_void_p()
            _oleacc.AccessibleObjectFromWindow(hwnd, _OBJID_CLIENT,
                                               iid, ctypes.byref(punk))
        except Exception:
            pass
        try:
            if uia is None:
                import uia_core
                uia = uia_core.get_automation()
            uia.ElementFromHandle(hwnd)
        except Exception:
            continue


def get_web_parts(element):
    """(role_override, parts) for a web element.

    role_override is "heading" for heading elements (the caller speaks it
    instead of the generic "text" role); parts contains the heading level
    ("level 2") and landmark ("main landmark") strings. Ordered so callers
    can place the parts after the element name and role.
    """
    role = None
    parts = []
    try:
        heading = element.GetCurrentPropertyValue(HEADING_LEVEL_PROP_ID)
    except Exception:
        heading = None
    if heading in _HEADING_LEVELS:
        role = "heading"
        parts.append(_HEADING_LEVELS[heading])

    try:
        landmark = element.GetCurrentPropertyValue(
            LOCALIZED_LANDMARK_PROP_ID)
    except Exception:
        landmark = None
    if landmark and isinstance(landmark, str) and landmark.strip():
        parts.append(landmark.strip() + " landmark")
    return role, parts
