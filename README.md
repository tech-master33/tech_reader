# TechReader (Screenreader)

A Python screen reader for Windows that speaks what you focus with your keyboard.
It watches **UI Automation (UIA) focus-changed events** and turns them into speech
through SAPI5, with extra handling for **Qt applications** and the
**[TeamTalk 5](https://www.bearware.dk/)** client.

> This project is an independent assistive tool. It is not affiliated with or
> endorsed by BearWare / TeamTalk.

## Features

- **Focus-based reading** — announces the focused control's name, type and state
  as you Tab and arrow through any application, via the Windows UIA API.
- **Qt-aware descriptions** — maps Qt widget class names (`QLineEdit`, `QComboBox`,
  `QTreeView`, …) to spoken roles, reads current values (combos, sliders, spin
  boxes, progress bars), and borrows a neighbouring `QLabel`'s text when a control
  has no accessible name (common in Qt dialogs).
- **TeamTalk 5 support** — toolbar toggle states ("push to talk disabled"),
  volume sliders with values, tab naming, channel-tree levels, chat duplicate
  suppression, and a "New Client Instance" profile dialog fix.
- **TechReader menu** (NVDA-style) — open with `CapsLock+Space`:
  - navigate with the **arrow keys** and activate with **Enter**
  - **Speech viewer** window that shows every utterance in real time
  - **Settings** dialog in Preferences — one NVDA-style dialog with
    categories (Speech, Output, Event announcements, Keyboard), voice,
    rate, volume and every announcement toggle
  - **View log**, **Restart**, **About**
- **Interrupt speech** instantly with **Ctrl**.
- **Persistent preferences** — the roles/states toggles, the menu hotkey and
  the speech voice/rate/volume are saved to
  `%APPDATA%\TechReader\techreader_config.json` and restored on the next start.
- Runs from **Python 3.10 – 3.14** on Windows 10/11.

## Requirements

- Windows 10 or 11
- Python 3.10 – 3.14 ([python.org](https://www.python.org/downloads/))
- At least one installed SAPI5 voice

## Getting started

Double-click **`run_screenreader.bat`**, or run it from a terminal:

```bat
run_screenreader.bat
```

The launcher:

1. uses `.venv` if one exists, otherwise falls back to your system Python;
2. checks the version is 3.10 – 3.14;
3. checks each dependency (`wxPython`, `comtypes`, `keyboard`, `pywin32`) and
   **asks whether to install** anything that's missing;
4. starts the app windowless with `pythonw` and writes output to
   `screenreader.log`.

To set up a virtual environment by hand:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
pythonw src\main.py
```

## Usage

| Keys | Action |
| --- | --- |
| `Ctrl` | Interrupt current speech |
| `CapsLock` + `Space` | Open / close the TechReader menu |
| `↑` / `↓` / `←` / `→` | Move between menu items (wraps) |
| `Enter` / `Space` | Activate the focused menu item |
| `Tab` | Normal focus navigation anywhere |

The **TechReader menu** contains:

- **Preferences → Settings…** — a single NVDA-style dialog: pick a category
  (Speech, Output, Event announcements, Keyboard) on the left, change the
  options on the right, then OK / Apply / Cancel
  - Speech — SAPI5 voice, rate, volume, test
  - Output — announce roles, states, shortcuts, passwords, position,
    table row/column, help text
  - Event announcements — menus, tooltips, windows/dialogs, notifications
  - Keyboard — enable/disable the `CapsLock+Space` menu hotkey
- **Tools**
  - Speech viewer — a window listing everything that is spoken
  - View log — opens `src/runtime.log` in a window
  - Restart screen reader
- **Help** — About TechReader

## Project layout

| Path | Description |
| --- | --- |
| `src/main.py` | Entry point: COM pump loop, keyboard layer selection, console-safe logging |
| `src/focus_handler.py` | UIA focus-changed event handler → spoken descriptions |
| `src/qt_handler.py` | Qt widget & TeamTalk descriptions, label lookup, value reading |
| `src/speech_manager.py` | Speech queue with a worker thread and cancel support |
| `src/sapi5.py` / `src/synth_driver.py` | SAPI5 engine and the speech-driver interface |
| `src/menu_manager.py` | wxPython menu, dialogs, speech viewer, restart |
| `src/native_keyboard.py` | Native keyboard bridge: DLL events → commands (Ctrl interrupt, CapsLock+Space) |
| `src/native/` | C keyboard layer: `techreader_keyboard.dll` hook source, self-test, public header |
| `scripts/build_native.bat` | Compiles the native keyboard DLL with gcc |
| `src/diagnose_keyboard.py` | Prints live native keyboard events and detected commands |
| `src/uia_core.py` | Shared UIA core: one automation object, timeouts, cache-request reads |
| `src/event_handler.py` | Event announcements: menus, tooltips, windows, notifications |
| `src/settings.py` | Runtime toggles loaded from the saved config (roles/states, event announcements, menu hotkey) |
| `src/config.py` | Reads/writes the persistent JSON config under `%APPDATA%\TechReader` |
| `src/start.wav`, `src/exit.wav` | Startup / exit sounds |
| `src/test_uia.py`, `src/test_comtypes_uia.py` | Development diagnostics |
| `run_screenreader.bat` | One-click launcher |

## Building a standalone `.exe`

```bat
python -m pip install pyinstaller
python -m PyInstaller screenreader.spec --noconfirm --clean
```

The ready-to-send app is written to `dist\screenreader\` (about 70 MB with
wxPython included; the build takes well under a minute). Zip that folder and
send it — it contains the exe, the native keyboard DLL and the UI sounds.
The `.zip` is `screenreader_portable.zip` if you build it with the helper
snippet in the repo history. Keep the folder layout intact when unzipping.

Notes:
- `screenreader.spec` is tracked in git and bundles
  `techreader_keyboard.dll` (into `_internal\native\`) plus `start.wav` /
  `exit.wav` automatically.
- A `screenreader.log` appears next to the exe while it runs — ask your
  friend to send it back if something does not work.
- No Python installation is needed on the target machine.

## Native keyboard layer (optional, recommended)

TechReader can use a small compiled C component for keyboard handling
instead of the `keyboard` Python package. It uses a Windows low-level
keyboard hook and offers the same commands (`Ctrl` interrupt,
`CapsLock+Space` menu) with lower overhead and explicit injected-key
protection. Python still contains all command logic; the C layer only
reports events.

```bat
scripts\build_native.bat
```

Builds `src\native\techreader_keyboard.dll` (requires
[gcc / MinGW-w64](https://winlibs.com/) in `PATH`), runs its self-test, and
TechReader picks it up automatically on the next start. Without the DLL the
app falls back to the python-keyboard implementation unchanged. See
[docs/native_keyboard.md](docs/native_keyboard.md) for the architecture.

## UIA core and event announcements

All UI Automation goes through one shared object with 2s/20s connection/
transaction timeouts (a hung app can no longer freeze the reader), cached
multi-property reads for fast focus descriptions, and extra announcements:
menus, tooltips, windows/dialogs, UIA notifications, keyboard accelerators,
password state, position-in-set and grid row/column for data items. Every
category is toggleable in the menu (Output settings / Event announcements).
See [docs/uia_events.md](docs/uia_events.md) for the architecture, including
the comtypes typelib quirks the code works around.

## How the speech pipeline works

```
UIA focus-changed event
        │  (comtypes COM event handler)
        ▼
focus_handler.py  ── builds a spoken description
        │
        ▼
speech_manager.py ── worker thread queue (Ctrl cancels)
        │
        ▼
sapi5.py          ── SAPI5 SpVoice (async, purge before speak)
```

## License

See [LICENSE](LICENSE).
