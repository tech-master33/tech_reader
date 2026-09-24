# Changelog

All notable changes to TechReader are documented in this file.
The format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [unreleased]

### Fixed

- On some machines the whole computer could freeze right after the
  "TechReader menu" announcement. The cause: UI Automation delivers its
  events as window messages, and the popup menu's own message loop
  dispatched them -- so focus/menu/window event handlers with
  cross-process COM property reads ran inside the menu loop while the
  menu held the system-wide input capture. One slow or hung application
  (elevated apps, remote sessions, wedged Chromium renderers) stalled
  everything. TechReader now suspends all its UIA event handlers for
  the popup's lifetime and resumes them on close, so no cross-process
  work can run inside the menu loop. The Chromium WM_GETOBJECT web wake
  is also strictly bounded now: hung windows are skipped, only visible
  renderer windows are poked, and every poke carries a short timeout.
- Ctrl (speech interrupt) no longer touches the synthesizer from the
  keyboard thread: the purge now happens on the speech worker's own COM
  apartment via an internal stop sentinel, so a stuck synthesizer can
  never stall the keyboard pump or the reader.

## [0.2.0-alpha.2] - 2026-09-23

Second alpha. Same feature set as alpha.1 plus the fixes below.

### Added

- Tools -> Report a problem: packages the log with system info, uploads it
  keylessly (no account, auto-deleted after 7 days), and speaks the link
  once and copies it to the clipboard. Runs off the main thread so a slow
  network can never freeze the reader; if upload fails, a report zip is
  saved under %APPDATA%\TechReader to attach instead.

### Fixed

- The TechReader menu could freeze the whole reader on some machines: when
  the owner window could not be made foreground (remote sessions, elevated
  apps, security software), the popup opened deaf to keyboard input with
  the main thread blocked. The menu is now only opened when it can
  actually receive keys -- otherwise the user hears "Cannot open menu
  now". The foreground switch is also hang-proof: it never attaches the
  input queue to a hung application and briefly shows the owner frame as
  a last resort.

## [0.2.0-alpha.1] - 2026-09-23

First alpha of the 0.2 line, shipped as a portable zip pre-release.

### Added

- Web page support (Chromium browsers: Edge, Chrome, Electron and WebView2
  apps): TechReader now wakes Chromium's sleeping accessibility tree itself
  via the standard WM_GETOBJECT handshake when focus enters a web document
  -- no browser settings or flags needed. Web announcements include heading
  levels ("heading, level 2") and landmark regions ("main landmark"),
  individually toggleable in Output settings.
- Synthesizer engine system, NVDA-style: engines are pluggable drivers with a
  Synthesizer selector in Settings → Speech; switching is instant and Cancel
  reverts a previewed switch.
- Windows OneCore voices engine (modern system voices) and a silent
  No-speech engine.
- Per-engine voice, rate, and volume persistence; existing flat speech
  settings migrate automatically to SAPI 5.
- Automatic fallback to the best available engine when the configured engine
  is missing on the machine.
- Deterministic engine detection via registry checks (replaces flaky live
  COM probes that could pick the wrong engine on cold threads).

## [0.1.0] - 2026-09-21

First public release, shipped as a portable zip (`screenreader_portable.zip`).

### Added

- UIA focus-driven screen reader: announces the focused control with
  configurable role, state, keyboard shortcut, password, position-in-set,
  table position, and help text.
- Native C low-level keyboard layer (`src/native`) with a Python fallback:
  Ctrl stops speech, CapsLock+Space opens the TechReader menu; injected
  events are flagged and never announced back.
- TechReader popup menu — a real menu with native submenus
  (Preferences / Tools / Help), item announcements via WM_MENUSELECT, and the
  owner window foregrounded so it always receives keys.
- NVDA-style Settings dialog: one dialog, categories on the left (Speech /
  Output / Event announcements / Keyboard), options on the right.
- Voice preview rendered offline to a temporary WAV, so testing a voice never
  switches or saves the live one.
- SAPI 5 speech with configurable voice, rate, and volume, plus a
  Test voice button.
- Event announcements for menus, tooltips, windows/dialogs, and notifications.
- Settings persisted to `%APPDATA%\TechReader`; runtime logs written there
  instead of next to the program.
- Windows packaging: PyInstaller build with embedded version info and icon,
  a portable zip packaged by `tools/package_zip.py`, and bundled run
  instructions.

### Fixed

- Items falsely announced as "offscreen" in some apps (notably Qt views):
  UIA's IsOffscreen flag is only believed when the element's bounding
  rectangle agrees.
- TechReader menu announced twice and did not take focus when opened; it is
  now a genuine menu control.
- Silent event-handler failures that killed Qt combo-box announcements.

[unreleased]: https://github.com/tech-master33/tech_reader/compare/0.2.0-alpha.2...HEAD
[0.2.0-alpha.2]: https://github.com/tech-master33/tech_reader/compare/0.2.0-alpha.1...0.2.0-alpha.2
[0.2.0-alpha.1]: https://github.com/tech-master33/tech_reader/compare/0.1.0...0.2.0-alpha.1
[0.1.0]: https://github.com/tech-master33/tech_reader/releases/tag/0.1.0
