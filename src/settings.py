# Runtime settings for TechReader, persisted to %APPDATA%\TechReader so they
# survive restarts. Values here are the defaults; saved values override them.

import config

# Announce element roles ("button", "edit", ...) on focus change.
speak_roles = bool(config.get("speak_roles", True))

# Announce element states ("checked", "selected", "expanded", ...) on focus change.
speak_states = bool(config.get("speak_states", True))

# Announce keyboard shortcuts ("Alt+F") on focus change.
speak_accelerators = bool(config.get("speak_accelerators", True))

# Announce "password protected" for password edit fields on focus change.
speak_password_state = bool(config.get("speak_password_state", True))

# Announce "3 of 12" set position for list/tree items on focus change.
speak_position_in_set = bool(config.get("speak_position_in_set", True))

# Announce help text / full description on focus change (noisy on some apps).
speak_help_text = bool(config.get("speak_help_text", False))

# Announce "row 2, column 3" and column/row headers for data items in
# grids and tables (via the GridItem/TableItem patterns).
speak_table_positions = bool(config.get("speak_table_positions", True))

# Announce heading levels ("heading, level 2") for web/document content.
speak_heading_levels = bool(config.get("speak_heading_levels", True))

# Announce landmark regions ("main landmark", "navigation") for web content.
speak_landmarks = bool(config.get("speak_landmarks", True))

# --- Event announcements (registered at startup; see event_handler.py) ---

# Announce menu open/close ("File menu", "menu closed").
announce_menus = bool(config.get("announce_menus", True))

# Announce tooltips as they appear.
announce_tooltips = bool(config.get("announce_tooltips", True))

# Announce new windows and dialogs ("Settings dialog").
announce_windows = bool(config.get("announce_windows", True))

# Announce UIA notification events (modern live-region mechanism).
announce_notifications = bool(config.get("announce_notifications", True))

# CapsLock+Space opens the TechReader menu.
menu_hotkey_enabled = bool(config.get("menu_hotkey_enabled", True))