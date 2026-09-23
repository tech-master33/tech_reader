# Changelog

All notable changes to TechReader are documented in this file.
The format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [0.2.0] - unreleased

Development version — nothing here has been released yet.

### Added

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

[0.2.0]: https://github.com/tech-master33/tech_reader/compare/0.1.0...HEAD
[0.1.0]: https://github.com/tech-master33/tech_reader/releases/tag/0.1.0
