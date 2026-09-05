import comtypes.client
import comtypes.gen.UIAutomationClient as UIA
import re
import time

_automation = None


def _get_automation():
    """Lazily created CUIAutomation object used for tree walking."""
    global _automation
    if _automation is None:
        _automation = comtypes.client.CreateObject(UIA.CUIAutomation)
    return _automation


def _get_raw_walker():
    """Raw-view tree walker.

    comtypes exposes RawViewWalker as a property on the CUIAutomation
    object (GetRawViewWalker is not available as a plain method), which
    older code here got wrong and silently swallowed.
    """
    try:
        return _get_automation().RawViewWalker
    except Exception:
        try:
            return _get_automation().GetRawViewWalker()
        except Exception:
            return None


def _get_current_value(el):
    """Read a control's current value through the Value pattern when possible.

    Qt providers often fail when the value is fetched through the element's
    shortcut property, but expose it fine via IUIAutomationValuePattern.
    """
    if el is None:
        return None
    try:
        pattern = el.GetCurrentPattern(UIA.UIA_ValuePatternId)
        value = pattern.QueryInterface(UIA.IUIAutomationValuePattern).CurrentValue
        if value:
            return str(value)
    except Exception:
        pass
    try:
        value = el.CurrentValue
        if value:
            return str(value)
    except Exception:
        pass
    return None


# Qt widget class name to human-readable description
QT_WIDGET_DESCRIPTIONS = {
    # Text editing
    "QLineEdit": "edit",
    "QTextEdit": "rich text edit",
    "QPlainTextEdit": "text edit",
    "QPlainTextDocumentLayout": "text edit",
    "QTextBrowser": "text browser",

    # Numeric input
    "QSpinBox": "spinner",
    "QDoubleSpinBox": "spinner",
    "QSlider": "slider",
    "QDial": "dial",

    # Boolean / selection
    "QCheckBox": "check box",
    "QRadioButton": "radio button",
    "QComboBox": "combo box",
    "QGroupBox": "group box",

    # Buttons
    "QPushButton": "button",
    "QToolButton": "tool button",
    "QCommandLinkButton": "command link button",
    "QDialogButtonBox": "button group",

    # Lists / trees / tables
    "QListView": "list",
    "QTreeView": "tree",
    "QTableView": "table",
    "QListWidget": "list",
    "QTreeWidget": "tree",
    "QTableWidget": "table",
    "QColumnView": "column view",

    # Tabs / toolboxes
    "QTabWidget": "tab group",
    "QTabBar": "tab bar",
    "QToolBox": "tool box",

    # Menus / toolbars
    "QMenuBar": "menu bar",
    "QMenu": "menu",
    "QToolBar": "tool bar",
    "QStatusBar": "status bar",

    # Containers
    "QSplitter": "splitter",
    "QScrollArea": "scroll area",
    "QDockWidget": "dock widget",
    "QMdiArea": "document area",
    "QMdiSubWindow": "sub window",
    "QStackedWidget": "stacked widget",

    # Dialogs
    "QDialog": "dialog",
    "QMessageBox": "message box",
    "QFileDialog": "file dialog",
    "QColorDialog": "color dialog",
    "QFontDialog": "font dialog",
    "QInputDialog": "input dialog",
    "QPrintDialog": "print dialog",
    "QProgressDialog": "progress dialog",
    "QWizard": "wizard",

    # Display
    "QLabel": "label",
    "QProgressBar": "progress bar",
    "QGraphicsView": "graphics view",
    "QGraphicsScene": "graphics scene",

    # Date / time
    "QCalendarWidget": "calendar",
    "QDateEdit": "date edit",
    "QTimeEdit": "time edit",
    "QDateTimeEdit": "date time edit",

    # Web
    "QWebEngineView": "web view",
    "QWebView": "web view",

    # System tray
    "QSystemTrayIcon": "system tray icon",
}

# Qt class names that are containers (need child traversal)
QT_CONTAINER_CLASSES = {
    "QGroupBox", "QTabWidget", "QToolBox", "QSplitter",
    "QScrollArea", "QDockWidget", "QMdiArea", "QMdiSubWindow",
    "QStackedWidget", "QDialogButtonBox", "QTabBar",
    "QColumnView",
}

# Qt class names that are item views (need selection handling)
QT_ITEM_VIEW_CLASSES = {
    "QListView", "QTreeView", "QTableView",
    "QListWidget", "QTreeWidget", "QTableWidget",
    "QColumnView",
}

# Qt class names for numeric input (need value reading)
QT_NUMERIC_CLASSES = {
    "QSpinBox", "QDoubleSpinBox", "QSlider", "QDial",
}

# Qt class names for text editing
QT_TEXT_EDIT_CLASSES = {
    "QLineEdit", "QTextEdit", "QPlainTextEdit",
    "QPlainTextDocumentLayout", "QTextBrowser",
}

# Qt class names for progress
QT_PROGRESS_CLASSES = {
    "QProgressBar",
}

# Qt class names for date/time
QT_DATE_TIME_CLASSES = {
    "QCalendarWidget", "QDateEdit", "QTimeEdit", "QDateTimeEdit",
}

# TeamTalk5 specific: toolbar checkbox names and their spoken labels
TEAMTALK_TOOLBAR_ITEMS = {
    "Push To Talk": "push to talk",
    "Voice Activation": "voice activation",
    "Video": "video",
    "Desktop": "desktop sharing",
    "Stream": "stream to channel",
    "Mute All": "mute all",
    "Record": "record conversations",
    "Question Mode": "question mode",
}

# TeamTalk5: volume control slider names and their spoken labels
TEAMTALK_VOLUME_CONTROLS = {
    "Master Volume": "master volume",
    "volume": "volume",
    "Microphone Gain": "microphone gain",
    "Mic Gain": "microphone gain",
    "Voice Activation Level": "voice activation level",
    "Voice Activation": "voice activation level",
}

# TeamTalk5: tab names and their spoken labels
TEAMTALK_TAB_NAMES = {
    "Chat": "chat",
    "Video": "video",
    "Desktop": "desktops",
    "Desktops": "desktops",
    "Files": "files",
}

# TeamTalk5: regex pattern for chat timestamps (e.g., "[12:34:56]" or "12:34:56" or "2024-01-15 12:34:56")
TEAMTALK_TIMESTAMP_PATTERNS = [
    re.compile(r'^\[\d{1,2}:\d{2}:\d{2}\]\s*'),
    re.compile(r'^\d{1,2}:\d{2}:\d{2}\s+'),
    re.compile(r'^\d{4}-\d{2}-\d{2}\s+\d{1,2}:\d{2}:\d{2}\s+'),
    re.compile(r'^\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}:\d{2}\s+'),
]

# TeamTalk5: duplicate name detection state
_last_announced_name = None
_last_announced_time = 0


def get_qt_label(el):
    """Find text in a QLabel that labels the given control.

    Qt apps routinely leave a control's accessible name empty and put the
    label text in a separate QLabel next to the control (for example the
    "Select profile" QLabel beside the QComboBox in TeamTalk's New Client
    Instance dialog). Look among the control's siblings for a QLabel above
    it (or to its left) and return its text.
    """
    try:
        walker = _get_raw_walker()
        if walker is None:
            return None
        parent = walker.GetParentElement(el)
        if not parent:
            return None
        rect = el.CurrentBoundingRectangle
        c_cx = (rect.left + rect.right) / 2.0
        c_w = max(1, rect.right - rect.left)
        best = None
        best_score = None
        sib = walker.GetFirstChildElement(parent)
        while sib:
            try:
                if (sib.CurrentClassName or "") != "QLabel":
                    sib = walker.GetNextSiblingElement(sib)
                    continue
                text = (sib.CurrentName or "").strip()
                if not text:
                    sib = walker.GetNextSiblingElement(sib)
                    continue
                srect = sib.CurrentBoundingRectangle
                score = None
                gap_y = rect.top - srect.bottom  # label sits above the control
                if -8 <= gap_y <= 120:
                    s_cx = (srect.left + srect.right) / 2.0
                    hoff = abs(s_cx - c_cx) / c_w
                    if hoff <= 1.5:
                        score = gap_y + hoff * 100
                if score is None:
                    gap_x = rect.left - srect.right  # label sits to the left
                    if -8 <= gap_x <= 160 and (srect.bottom - 4) >= rect.top and (srect.top + 4) <= rect.bottom:
                        score = 200 + gap_x
                if score is None:
                    # last resort: nearest sibling label by centre distance
                    s_cx = (srect.left + srect.right) / 2.0
                    s_cy = (srect.top + srect.bottom) / 2.0
                    c_cy = (rect.top + rect.bottom) / 2.0
                    score = 1000 + abs(s_cx - c_cx) + abs(s_cy - c_cy)
                if best_score is None or score < best_score:
                    best_score = score
                    best = text
            except Exception:
                pass
            sib = walker.GetNextSiblingElement(sib)
        return best
    except Exception:
        return None


def get_qt_widget_description(el):
    """Get a description for a Qt widget based on its class name."""
    try:
        class_name = el.CurrentClassName
        if not class_name:
            return None

        # Direct lookup
        if class_name in QT_WIDGET_DESCRIPTIONS:
            return QT_WIDGET_DESCRIPTIONS[class_name]

        # Check parent class patterns (e.g., subclasses)
        for qt_class, desc in QT_WIDGET_DESCRIPTIONS.items():
            if qt_class in class_name:
                return desc
    except Exception:
        pass
    return None


def get_qt_widget_states(el):
    """Read states specific to Qt widgets."""
    states = []
    try:
        class_name = el.CurrentClassName
        if not class_name:
            return states

        # Line edit / text edit — read-only check
        if class_name in QT_TEXT_EDIT_CLASSES:
            try:
                if el.CurrentIsReadOnly:
                    states.append("read only")
            except Exception:
                pass

        # Spin box — read value
        if class_name in ("QSpinBox", "QDoubleSpinBox"):
            val = _get_current_value(el)
            if val:
                states.append(f"value: {val}")

        # Slider — read value (TeamTalk user volume)
        if class_name == "QSlider":
            val = _get_current_value(el)
            if val:
                states.append(f"value: {val}")

        # Progress bar — read value
        if class_name == "QProgressBar":
            val = _get_current_value(el)
            if val:
                states.append(val)

        # Date/time edit — read value
        if class_name in QT_DATE_TIME_CLASSES:
            val = _get_current_value(el)
            if val:
                states.append(f"value: {val}")

        # Combo box — read the selected item (match by substring so custom
        # QComboBox subclasses and Qt5-prefixed classes are found too)
        if "QComboBox" in class_name:
            val = _get_current_value(el)
            if val:
                states.append(val)

        # Group box — read title
        if class_name == "QGroupBox":
            val = _get_current_value(el)
            if val:
                states.append(f"title: {val}")

    except Exception:
        pass
    return states


def get_teamtalk_description(el):
    """Get TeamTalk5 specific description for an element."""
    try:
        name = el.CurrentName
        class_name = el.CurrentClassName
        control_type = el.CurrentControlType

        # Volume control sliders — announce name and value (handle even without Name)
        if class_name == "QSlider" or control_type == UIA.UIA_SliderControlTypeId:
            return _get_volume_slider_description(el, name)

        # If no name, can't do much more
        if not name:
            return None

        # Toolbar checkboxes — add state (checked/unchecked)
        if control_type == UIA.UIA_ToolBarControlTypeId or class_name == "QToolBar":
            for tt_name, spoken_name in TEAMTALK_TOOLBAR_ITEMS.items():
                if tt_name.lower() in name.lower():
                    try:
                        toggle = el.GetCurrentPattern(UIA.UIA_TogglePatternId)
                        toggle_pattern = toggle.QueryInterface(UIA.IUIAutomationTogglePattern)
                        state = toggle_pattern.CurrentToggleState
                        checked = "enabled" if state == 1 else "disabled"
                        return f"{spoken_name} {checked}"
                    except Exception:
                        return spoken_name

        # Tool buttons that are toolbar checkboxes
        if class_name == "QToolButton":
            for tt_name, spoken_name in TEAMTALK_TOOLBAR_ITEMS.items():
                if tt_name.lower() in name.lower():
                    try:
                        toggle = el.GetCurrentPattern(UIA.UIA_TogglePatternId)
                        toggle_pattern = toggle.QueryInterface(UIA.IUIAutomationTogglePattern)
                        state = toggle_pattern.CurrentToggleState
                        checked = "enabled" if state == 1 else "disabled"
                        return f"{spoken_name} {checked}"
                    except Exception:
                        return spoken_name

        # Tab items — announce tab name
        if class_name == "QTabBar" or control_type == UIA.UIA_TabControlTypeId:
            return _get_tab_description(el, name)

        # Tab items (individual tabs)
        if control_type == UIA.UIA_TabItemControlTypeId:
            for tt_name, spoken_name in TEAMTALK_TAB_NAMES.items():
                if tt_name.lower() in name.lower():
                    return f"{spoken_name} tab"
            return f"{name} tab"

        # Channel tree items — add tree level
        if class_name in ("QTreeView", "QTreeWidget") or control_type == UIA.UIA_TreeControlTypeId:
            return _get_tree_item_description(el)

        # Chat history — suppress timestamps if needed
        if class_name in ("QTextEdit", "QPlainTextEdit", "QPlainTextDocumentLayout", "QListView"):
            return _get_chat_history_description(el, name)

        # Spin boxes in settings
        if class_name in ("QSpinBox", "QDoubleSpinBox"):
            try:
                val = el.CurrentValue
                if val:
                    return f"{name} spinner value: {val}"
            except Exception:
                pass

        # Status bar
        if class_name == "QStatusBar" or control_type == UIA.UIA_StatusBarControlTypeId:
            return f"status: {name}"

        # Splitter — announce as splitter
        if class_name == "QSplitter":
            return f"splitter {name}" if name else "splitter"

    except Exception:
        pass
    return None


def _get_volume_slider_description(el, name):
    """Build description for TeamTalk5 volume control sliders."""
    try:
        # Try to get value from Value pattern first, then RangeValue pattern
        value = None
        try:
            val = el.CurrentValue
            if val:
                value = str(val)
        except Exception:
            pass

        # Try RangeValue pattern for sliders
        if not value:
            try:
                range_pattern = el.GetCurrentPattern(UIA.UIA_RangeValuePatternId)
                range_val = range_pattern.QueryInterface(UIA.IUIAutomationRangeValuePattern)
                value = str(int(range_val.CurrentValue))
            except Exception:
                pass

        # Try to infer slider name from parent or sibling labels
        if not name:
            name = _guess_slider_name(el)

        if name:
            # Match known volume control names
            for tt_name, spoken_name in TEAMTALK_VOLUME_CONTROLS.items():
                if tt_name.lower() in name.lower():
                    if value:
                        return f"{spoken_name} slider value: {value}"
                    return f"{spoken_name} slider"

            if value:
                return f"{name} slider value: {value}"
            return f"{name} slider"

        # No name but has value
        if value:
            return f"slider value: {value}"

        return "slider"
    except Exception:
        return "slider"


def _guess_slider_name(el):
    """Try to guess slider name from nearby labels or tooltips."""
    try:
        # Try to get help text / tooltip
        help_text = el.CurrentHelpText
        if help_text:
            return help_text

        # Try to get automation ID
        auto_id = el.CurrentAutomationId
        if auto_id:
            # Common automation IDs for TeamTalk sliders
            auto_id_lower = auto_id.lower()
            if "volume" in auto_id_lower or "master" in auto_id_lower:
                return "Master Volume"
            elif "mic" in auto_id_lower or "gain" in auto_id_lower:
                return "Microphone Gain"
            elif "voice" in auto_id_lower or "activation" in auto_id_lower:
                return "Voice Activation Level"

        # Try to get name from parent container
        try:
            walker = _get_raw_walker()
            if walker is None:
                return None
            parent = walker.GetParentElement(el)
            if parent:
                parent_name = parent.CurrentName
                if parent_name:
                    return parent_name
        except Exception:
            pass

    except Exception:
        pass
    return None


def _get_tab_description(el, name):
    """Build description for TeamTalk5 tab control."""
    try:
        # Match known tab names
        for tt_name, spoken_name in TEAMTALK_TAB_NAMES.items():
            if tt_name.lower() in name.lower():
                return f"{spoken_name} tab group"

        return f"{name} tab group"
    except Exception:
        return None


def _get_tree_item_description(el):
    """Build description for tree items with level reporting."""
    try:
        name = el.CurrentName
        if not name:
            return None

        parts = [name]

        # Try to get tree level by walking parents
        try:
            walker = _get_raw_walker()
            if walker is None:
                return None
            level = 0
            parent = walker.GetParentElement(el)
            while parent:
                parent_type = parent.CurrentControlType
                if parent_type in (UIA.UIA_TreeControlTypeId, UIA.UIA_TreeItemControlTypeId):
                    level += 1
                parent = walker.GetParentElement(parent)
            if level > 0:
                parts.append(f"level {level}")
        except Exception:
            pass

        # Expand/collapse state
        try:
            expand = el.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId)
            expand_pattern = expand.QueryInterface(UIA.IUIAutomationExpandCollapsePattern)
            state = expand_pattern.CurrentExpandCollapseState
            if state == UIA.UIA_ExpandCollapseState_Expanded:
                parts.append("expanded")
            elif state == UIA.UIA_ExpandCollapseState_Collapsed:
                parts.append("collapsed")
        except Exception:
            pass

        # Selection state
        try:
            sel = el.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
            sel_pattern = sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern)
            if sel_pattern.CurrentIsSelected:
                parts.append("selected")
        except Exception:
            pass

        return " ".join(parts)
    except Exception:
        return None


def _get_chat_history_description(el, name):
    """Handle chat history with optional timestamp suppression."""
    global _last_announced_name, _last_announced_time

    # Check for duplicate announcements (Qt fires focus events on status changes)
    now = time.time()
    if name == _last_announced_name and (now - _last_announced_time) < 0.5:
        return None
    _last_announced_name = name
    _last_announced_time = now

    return name


def strip_teamtalk_timestamp(text):
    """Remove TeamTalk timestamp from chat text for cleaner reading."""
    if not text:
        return text
    for pattern in TEAMTALK_TIMESTAMP_PATTERNS:
        text = pattern.sub('', text)
    return text.strip()


def is_teamtalk_toolbar_item(name):
    """Check if a name matches a TeamTalk toolbar item."""
    if not name:
        return False
    for tt_name in TEAMTALK_TOOLBAR_ITEMS:
        if tt_name.lower() in name.lower():
            return True
    return False


def is_qt_container(class_name):
    """Check if a Qt class name is a container type."""
    if not class_name:
        return False
    for qt_class in QT_CONTAINER_CLASSES:
        if qt_class in class_name:
            return True
    return False


def is_qt_item_view(class_name):
    """Check if a Qt class name is an item view type."""
    if not class_name:
        return False
    for qt_class in QT_ITEM_VIEW_CLASSES:
        if qt_class in class_name:
            return True
    return False


def is_qt_dialog(class_name):
    """Check if a Qt class name is a dialog type."""
    if not class_name:
        return False
    dialog_classes = ("QDialog", "QMessageBox", "QFileDialog",
                      "QColorDialog", "QFontDialog", "QInputDialog",
                      "QPrintDialog", "QProgressDialog", "QWizard")
    for qt_class in dialog_classes:
        if qt_class in class_name:
            return True
    return False


def is_qt_text_edit(class_name):
    """Check if a Qt class name is a text edit type."""
    if not class_name:
        return False
    for qt_class in QT_TEXT_EDIT_CLASSES:
        if qt_class in class_name:
            return True
    return False


def get_qt_dialog_description(el):
    """Try to build a description for a Qt dialog by reading its children."""
    parts = []
    try:
        class_name = el.CurrentClassName
        name = el.CurrentName
        if name:
            parts.append(name)

        # Add dialog type
        desc = get_qt_widget_description(el)
        if desc:
            parts.append(desc)
    except Exception:
        pass
    return " ".join(parts) if parts else None
