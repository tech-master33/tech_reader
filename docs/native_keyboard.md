# TechReader native keyboard layer

This document explains how TechReader's native (C) keyboard layer works, how
it communicates with Python, and how it relates to the old python-keyboard
implementation.

## Overview

TechReader needs exactly two keyboard commands today:

| Keys | Command | Effect |
| --- | --- | --- |
| `Ctrl` (either key, key-down) | `interrupt` | Stop current speech |
| `CapsLock` + `Space` (Space key-down while Caps Lock is held) | `menu` | Toggle the TechReader menu |

The **native layer** (C, `techreader_keyboard.dll`) receives raw keyboard
events from Windows through a low-level hook, describes them in a small
struct, and hands each one to Python. All **command logic lives in Python**
(`src/native_keyboard.py`): the C layer only detects and describes.

The previous python-keyboard implementation is kept as a **fallback** in
`src/main.py` and is used automatically when the DLL is missing or fails to
start. Nothing is removed until the native path has proven itself in
everyday use.

## Architecture

```
Windows keyboard input (hardware or injected)
        │
        ▼
techreader_keyboard.dll  (src/native/trk_keyboard.c)
  WH_KEYBOARD_LL hook on a dedicated thread
  - maps each event into TrkKeyboardEvent
  - flags injected events (LLKHF_INJECTED)
  - never swallows keys (always CallNextHookEx)
        │  sink callback (__stdcall, on hook thread)
        ▼
native_keyboard.py
  - ctypes sink copies the event into a queue (fast, never blocks)
  - pump thread drains the queue
  - detect_command() decides: interrupt / menu / nothing
        │  on_command()
        ▼
main.py  dispatch_keyboard_command()
  - interrupt -> speech_manager.cancelSpeech()
  - menu      -> wx.CallAfter(menu_manager.show_menu) if enabled
```

### Threading model

- **Hook thread** (owned by the DLL): runs the message loop that keeps the
  `WH_KEYBOARD_LL` hook alive, and calls the Python sink synchronously for
  every event. The sink must be fast: Windows silently unbinds hooks whose
  handlers stall. The sink only copies the event and enqueues it.
- **Pump thread** (Python, `native_keyboard.py`): drains the queue and runs
  `detect_command()`, then invokes the command callback. All slower work
  (speech, wx) happens here or later, never on the hook thread.
- **wx main loop**: menu opening is marshalled with `wx.CallAfter`, exactly
  as the old implementation did.

### The event struct (stable ABI)

`TrkKeyboardEvent` (defined in `src/native/trk_keyboards.h`, mirrored with
ctypes in `src/native_keyboard.py`):

| Field | Type | Meaning |
| --- | --- | --- |
| `event_type` | uint32 | `TRK_KEY_DOWN` / `TRK_KEY_UP` / `TRK_SYS_KEY_DOWN` / `TRK_SYS_KEY_UP` |
| `vk` | uint32 | virtual-key code |
| `scan_code` | uint32 | scan code |
| `flags` | uint32 | extended, injected, lower-IL injected, alt-down, transition |
| `time_ms` | uint64 | ms since boot (`GetTickCount64`) |
| `modifier_state` | uint32 | bitmask: L/R Ctrl, Shift, Alt, Win held; Caps/Num held; Caps/Num toggle on |
| `reserved` | uint32 | zero; keeps the layout stable for future fields |

`TRK_MOD_*` values are in `src/native/trk_keyboards.h`; the Python side
mirrors them as module constants.

### Feedback-loop protection

Any event injected with `SendInput` (or other synthetic means) carries
`LLKHF_INJECTED`; the C layer maps that to `TRK_FLAG_INJECTED` and the
Python command detector **ignores injected events entirely**. TechReader
cannot trigger its own commands by injecting keys, and other tools'
injected keys cannot command TechReader either. Events are flagged, not
dropped: diagnostics can still see them.

The hook itself never suppresses or alters keys, so normal typing always
reaches applications unchanged.

### Why the sink is a callback (not a polled queue)

The DLL calls the registered Python sink directly on its hook thread and
the sink only queues. This gives the lowest latency and the simplest
lifecycle (start/stop). A DLL-side queue with polling was considered and
rejected: it adds latency and a second synchronization surface without
removing the requirement that hook-side work stays trivial. The interface
(`trk_keyboards.h`) is plain C with a stable struct, so a future C++ layer
can be added alongside without redesigning the keyboard interface.

## Building

Requires gcc (MinGW-w64) in `PATH`. From the project root:

```bat
scripts\build_native.bat
```

This compiles `src\native\techreader_keyboard.dll` and
`src\native\trk_keyboard_test.exe`, then runs the C self-test (29 checks:
synthetic event mapping, live hook delivery, injected flag, stop/restart,
no delivery after stop).

The DLL is a build artifact and is not committed (`*.dll` is ignored);
build it once after cloning.

## Diagnostics

```bat
python src\diagnose_keyboard.py 15
```

Prints every keyboard event the native layer sees for 15 seconds — key
name, down/up, scan code, modifier bitmask, `[injected]`/`[ext]` markers —
plus any command it would produce (`Ctrl` → `interrupt`,
`CapsLock+Space` → `menu`). Use it to confirm the hook is alive and
commands fire before switching TechReader's daily driver.

## Fallback behavior

`src/main.py` chooses at startup:

1. If `src/native/techreader_keyboard.dll` exists and the hook starts →
   **native layer** (log line: `Keyboard: native low-level hook active`).
2. Otherwise → **python-keyboard fallback** with the identical commands
   (log line: `Keyboard: ... using python-keyboard fallback`), and the
   original `add_hotkey` calls.

The old implementation stays in the tree until the native path has been
demonstrated to reproduce existing behavior in daily use; removal is a
separate, deliberate step.

## Future work (out of scope here)

- A separate `techreader.dll` controller/client API (NVDA-style remote
  control) is planned but deliberately **not** part of this keyboard layer.
- Later C++ additions (lower-level Windows or UIA functionality Python
  cannot reach well) should extend the same `src/native/` component with
  the same interface style: plain C ABI, callback sinks, no command logic
  in the native layer.
