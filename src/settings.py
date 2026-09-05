# Runtime settings for TechReader, persisted to %APPDATA%\TechReader so they
# survive restarts. Values here are the defaults; saved values override them.

import config

# Announce element roles ("button", "edit", ...) on focus change.
speak_roles = bool(config.get("speak_roles", True))

# Announce element states ("checked", "selected", "expanded", ...) on focus change.
speak_states = bool(config.get("speak_states", True))

# CapsLock+Space opens the TechReader menu.
menu_hotkey_enabled = bool(config.get("menu_hotkey_enabled", True))