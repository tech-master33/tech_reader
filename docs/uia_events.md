# TechReader UIA core and event announcements

How TechReader's UI Automation layer works after the enhancement work: the
shared core (`src/uia_core.py`), the event announcers (`src/event_handler.py`),
the enriched focus descriptions (including grid positions), and the settings
that control all of it.

## Overview

Previously TechReader created one plain `IUIAutomation` object, used exactly
two event registrations (focus-changed, property-changed), and read every
property with a separate cross-process `Current*` COM call. A busy or hung
target app could freeze the whole reader for up to **three minutes** on a
single property read (the UIA default timeouts).

Now:

- One shared automation object is created from the `CUIAutomation8` coclass
  and used by `main.py`, `event_handler.py`, and `qt_handler.py`.
- Timeouts are set through `IUIAutomation2`: **2 s** connection,
  **20 s** transaction. A hung app can no longer freeze speech for minutes.
- Extended properties (accelerator, password, position-in-set, help text) are
  fetched in **one** cached COM round-trip per focus change.
- Five announcement types share one generic handler: menus, tooltips,
  windows/dialogs, UIA notifications, and (via the Qt value-change path)
  popup selection changes.

## Machine-specific typelib quirks (read before "fixing" the code)

The comtypes-generated typelib on the build machine deviates from the
official Microsoft signatures. All verified empirically:

| Task | Use | Why |
| --- | --- | --- |
| Event registration (`AddAutomationEventHandler`) | the **v1** `IUIAutomation` pointer | bindings are correct there |
| `AddPropertyChangedEventHandler` | v1 pointer, 5 args: `(element, scope, cacheRequest, handler, propertyArray)` | a NULL element is rejected with E_POINTER — subscribe at the desktop root |
| Notification events | the **v5** `IUIAutomation5` pointer | `AddNotificationEventHandler(element, scope, cacheRequest, handler)` |
| Timeouts | `IUIAutomation2` | via `QueryInterface` from the CUIAutomation8 object |
| Extended properties | generic `GetCachedPropertyValue` / `GetCurrentPropertyValue` | typed `CachedPositionInSet`/`CachedSizeOfSet` members are missing from the generated `IUIAutomationElement2` |
| Grid/table positions | typed `IUIAutomationGridItemPattern` / `IUIAutomationTableItemPattern` via `GetCurrentPattern` | work fine; only the raw `UIA_RowPropertyId`-style constants are missing from this typelib |
| **Never** | the `IUIAutomation6` pointer for registrations | its redeclared bindings drop the `element` parameter — calls raise TypeError/ArgumentError |

Also: one **fresh handler instance per registration** — reusing one COMObject
across two `Add*` calls fails with an interface QI error on this build.

## src/uia_core.py — the shared core

```python
uia   = uia_core.get_automation()   # v1 IUIAutomation: registrations, walking
root  = uia_core.get_root_element() # desktop root, cached
props = uia_core.get_element_properties(el, [UIA.UIA_NamePropertyId, ...])
```

- `get_automation()` — lazily creates `CUIAutomation8`, QueryInterfaces the
  v1/v2/v5/v6 pointers, sets timeouts via v2. Returns the **v1** pointer.
- `add_automation_event_handler(event_id, handler)` — desktop-rooted v1
  registration; raises on failure so callers can report and continue.
- `add_notification_event_handler(handler)` — v5 registration.
- `get_element_properties(element, property_ids)` — builds a cache request,
  fetches all properties in one `BuildUpdatedCache` call; falls back to
  per-property live reads for old providers. Returns `{property_id: value}`,
  missing properties simply absent.
- `CONNECTION_TIMEOUT_MS = 2000`, `TRANSACTION_TIMEOUT_MS = 20000`.

## src/event_handler.py — event announcements

Pure announcer functions (`element -> text or None`) keep the logic
unit-testable; the thin COM handler classes only dispatch and never let an
exception escape into the UIA event thread.

| Event | Announcer | Notes |
| --- | --- | --- |
| Menu opened | menu name, or first-item name for context menus | focus handler announces the item itself |
| Menu closed | "menu closed" | |
| Tooltip opened | tooltip text | falls back to first named child |
| Window opened | "name dialog"/"name window" | unnamed, offscreen, IME/shadow windows filtered |
| Window closed | "name closed" | |
| Notification | displayString | v5 events; activityId used only as last resort |

Noise control: a 0.4 s identical-text dedupe window suppresses provider event
echoes. `register_events(callback)` registers every event whose settings flag
is enabled, returns labels for the startup log, and treats per-event failures
as non-fatal. Live handlers are kept in `_active_handlers` so they stay alive
while registered.

## Focus description enrichment (src/focus_handler.py)

`_add_extended_info` fetches accelerator key, password flag, position/size of
set, help text and full description in one cached round-trip
(`uia_core.get_element_properties`) and appends each behind its own toggle:

- `"Alt+F"` (accelerator)
- `"password protected"`
- `"3 of 12"` (position in set)
- help text / full description (off by default — noisy on some apps)

`_add_table_position` adds grid coordinates for data items: `"row 2,
column 3"` from the GridItem pattern and `"column Name"` from the TableItem
column headers (up to 3, deduplicated). Silent for everything that is not a
grid item.

## Settings

All toggles live in `settings.py`, persist via `config.py`, and appear in
TechReader's **Preferences → Settings…** dialog (Output and
Event announcements categories).

| Setting | Default | Controls |
| --- | --- | --- |
| `speak_roles` / `speak_states` | on | role and state words on focus |
| `speak_accelerators` | on | accelerator keys on focus |
| `speak_password_state` | on | "password protected" |
| `speak_position_in_set` | on | "3 of 12" |
| `speak_table_positions` | on | grid row/column + headers |
| `speak_help_text` | **off** | help text / full description |
| `announce_menus` | on | menu open/close |
| `announce_tooltips` | on | tooltips |
| `announce_windows` | on | windows and dialogs |
| `announce_notifications` | on | UIA notification events |

## Verification performed

- All modules compile; existing keyboard suites still pass
  (C 29/29, Python bridge 15/15).
- Hermetic logic tests (23 checks): focus enrichment, event-to-text mapping,
  dedupe, settings round-trip, table-position logic.
- Live smoke test on this machine: 6/6 event registrations stable, cached
  property fetch through `get_element_properties` on the root element,
  clean `RemoveAllEventHandlers`.
- Startup prints which announcement groups are active; each group degrades
  independently if its registration fails.
