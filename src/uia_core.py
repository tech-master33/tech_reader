"""Central UIA access for TechReader.

Every UI Automation object and event registration goes through this module so
the whole reader shares one connection with sane timeouts, and so the
machine-specific comtypes quirks are handled in exactly one place.

Quirks of the comtypes typelib generation this project was built against
(verified empirically on this machine):

* ``CUIAutomation`` (the plain coclass) only supports interface version 1.
  The modern interfaces live on ``CUIAutomation8``.
* The v1 ``IUIAutomation`` bindings for the standard registration methods
  (``AddAutomationEventHandler``, ``AddPropertyChangedEventHandler``) are
  correct and take ``(element, scope, cacheRequest, handler[, ...])``.
* The ``IUIAutomation6`` interface *redeclares* those methods, but the
  generated bindings drop the ``element`` parameter -- calling them raises
  TypeError/ArgumentError. NEVER register events through the v6 pointer;
  use the v1 pointer (or v5 for notification handlers, whose bindings are
  correct there).
* Typed ``CachedPositionInSet``/``CachedSizeOfSet``/``CachedLevel`` members
  are missing from the generated ``IUIAutomationElement2``; the generic
  ``GetCachedPropertyValue``/``GetCurrentPropertyValue`` work fine and are
  the portable way to read extended properties.
"""

import comtypes.client
import comtypes.gen.UIAutomationClient as UIA

# Connection/transaction timeouts, in milliseconds. The UIA defaults are
# 3 minutes / 3 minutes: a busy or hung application would freeze the whole
# screen reader on a single property read. 2 s connection and 20 s
# transaction keep the reader responsive without breaking slow providers.
CONNECTION_TIMEOUT_MS = 2000
TRANSACTION_TIMEOUT_MS = 20000

_object = None       # raw CUIAutomation8 COM object
_automation = None   # IUIAutomation      (v1: registrations, cache requests)
_automation2 = None  # IUIAutomation2     (timeouts)
_automation5 = None  # IUIAutomation5     (notification event handlers)
_automation6 = None  # IUIAutomation6     (reserved; do not register through it)


def _get():
    """Lazily create the shared automation object and versioned pointers."""
    global _object, _automation, _automation2, _automation5, _automation6
    if _object is None:
        _object = comtypes.client.CreateObject(UIA.CUIAutomation8)
        _automation = _object.QueryInterface(UIA.IUIAutomation)
        try:
            _automation2 = _object.QueryInterface(UIA.IUIAutomation2)
            _automation2.ConnectionTimeout = CONNECTION_TIMEOUT_MS
            _automation2.TransactionTimeout = TRANSACTION_TIMEOUT_MS
        except Exception:
            _automation2 = None
        try:
            _automation5 = _object.QueryInterface(UIA.IUIAutomation5)
        except Exception:
            _automation5 = None
        try:
            _automation6 = _object.QueryInterface(UIA.IUIAutomation6)
        except Exception:
            _automation6 = None
    return _automation, _automation2, _automation5, _automation6


def get_automation():
    """The v1 IUIAutomation pointer: registrations and tree walking."""
    return _get()[0]


def get_automation5():
    """The v1 pointer (notifications are registered through IUIAutomation5)."""
    return _get()[2]


def get_root_element():
    """The desktop root element, used as subscription root for global events."""
    return get_automation().GetRootElement()


def add_automation_event_handler(event_id, handler, element=None, scope=None):
    """Register an IUIAutomationEventHandler for one event id.

    Returns the handler on success; raises on failure so callers can report
    and continue without the feature. A fresh handler instance must be used
    for every registration -- comtypes COM objects do not re-QI into a new
    registration cleanly (ArgumentError on the second use).
    """
    uia = get_automation()
    if element is None:
        element = get_root_element()
    if scope is None:
        scope = UIA.TreeScope_Subtree
    uia.AddAutomationEventHandler(event_id, element, scope, None, handler)
    return handler


def remove_automation_event_handler(event_id, handler, element=None):
    uia = get_automation()
    if element is None:
        element = get_root_element()
    uia.RemoveAutomationEventHandler(event_id, element, handler)


def add_notification_event_handler(handler, element=None, scope=None):
    """Register an IUIAutomationNotificationEventHandler (UIA v5 feature)."""
    uia5 = get_automation5()
    if uia5 is None:
        raise RuntimeError("IUIAutomation5 unavailable: notification events unsupported")
    if element is None:
        element = get_root_element()
    if scope is None:
        scope = UIA.TreeScope_Subtree
    uia5.AddNotificationEventHandler(element, scope, None, handler)
    return handler


def remove_notification_event_handler(handler, element=None):
    uia5 = get_automation5()
    if uia5 is None:
        return
    if element is None:
        element = get_root_element()
    try:
        uia5.RemoveNotificationEventHandler(element, handler)
    except Exception:
        pass


def is_offscreen_confirmed(element):
    """True when the element is genuinely not visible on any screen.

    Several providers report IsOffscreen=True for items that are plainly
    visible (notably items inside Qt item views), so the flag alone cannot
    be trusted. The flag is only believed when the bounding rectangle
    agrees: an empty rectangle, or one that lies entirely outside the
    virtual screen. A non-empty rectangle intersecting the virtual screen
    means the element is rendered, whatever the flag claims.
    """
    try:
        rect = element.CurrentBoundingRectangle
        left, top = int(rect.left), int(rect.top)
        right, bottom = int(rect.right), int(rect.bottom)
    except Exception:
        return True  # cannot verify; trust the provider's flag
    if right <= left or bottom <= top:
        return True  # zero size: nothing is rendered
    try:
        import ctypes
        user32 = ctypes.windll.user32
        vx = user32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
        vy = user32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
        vw = user32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
        vh = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if vw <= 0 or vh <= 0:
            return True
        return (right <= vx or left >= vx + vw
                or bottom <= vy or top >= vy + vh)
    except Exception:
        return False  # have a real rect but no screen info: assume visible


def get_element_properties(element, property_ids):
    """Fetch several properties in one COM round-trip via a cache request.

    Returns ``{property_id: value}``. Properties the provider cannot serve
    are simply absent. If the cache path fails entirely (very old providers),
    falls back to per-property live reads so callers still get best-effort
    values.
    """
    values = {}
    if element is None or not property_ids:
        return values
    try:
        request = get_automation().CreateCacheRequest()
        for pid in property_ids:
            request.AddProperty(pid)
        request.TreeScope = UIA.TreeScope_Element
        cached = element.BuildUpdatedCache(request)
        for pid in property_ids:
            try:
                values[pid] = cached.GetCachedPropertyValue(pid)
            except Exception:
                pass
        return values
    except Exception:
        pass
    for pid in property_ids:
        try:
            values[pid] = element.GetCurrentPropertyValue(pid)
        except Exception:
            pass
    return values
