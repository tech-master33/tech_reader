import time

import comtypes
from comtypes import COMObject
import comtypes.gen.UIAutomationClient as UIA
import settings
import uia_core
import web_handler
from qt_handler import (
    get_qt_label,
    get_qt_widget_description,
    get_qt_widget_states,
    get_teamtalk_description,
    is_qt_container,
    is_qt_item_view,
    is_qt_text_edit,
    get_qt_dialog_description,
    is_teamtalk_toolbar_item,
)

UIA_ROLES = {
    UIA.UIA_ButtonControlTypeId: "button",
    UIA.UIA_EditControlTypeId: "edit",
    UIA.UIA_CheckBoxControlTypeId: "check box",
    UIA.UIA_RadioButtonControlTypeId: "radio button",
    UIA.UIA_ComboBoxControlTypeId: "combo box",
    UIA.UIA_ListControlTypeId: "list",
    UIA.UIA_ListItemControlTypeId: "list item",
    UIA.UIA_TreeControlTypeId: "tree",
    UIA.UIA_TreeItemControlTypeId: "tree item",
    UIA.UIA_MenuItemControlTypeId: "menu item",
    UIA.UIA_MenuBarControlTypeId: "menu bar",
    UIA.UIA_ScrollBarControlTypeId: "scroll bar",
    UIA.UIA_SliderControlTypeId: "slider",
    UIA.UIA_SpinnerControlTypeId: "spinner",
    UIA.UIA_ProgressBarControlTypeId: "progress bar",
    UIA.UIA_TabControlTypeId: "tab",
    UIA.UIA_TabItemControlTypeId: "tab",
    UIA.UIA_ToolBarControlTypeId: "tool bar",
    UIA.UIA_ToolTipControlTypeId: "tool tip",
    UIA.UIA_DataGridControlTypeId: "data grid",
    UIA.UIA_DataItemControlTypeId: "data item",
    UIA.UIA_HeaderControlTypeId: "header",
    UIA.UIA_HeaderItemControlTypeId: "header item",
    UIA.UIA_HyperlinkControlTypeId: "link",
    UIA.UIA_ImageControlTypeId: "image",
    UIA.UIA_DocumentControlTypeId: "document",
    UIA.UIA_WindowControlTypeId: "window",
    UIA.UIA_PaneControlTypeId: "pane",
    UIA.UIA_GroupControlTypeId: "group",
    UIA.UIA_ThumbControlTypeId: "thumb",
    UIA.UIA_SplitButtonControlTypeId: "split button",
    UIA.UIA_MenuControlTypeId: "menu",
    UIA.UIA_AppBarControlTypeId: "app bar",
}

SILENT_ROLES_ON_FOCUS = {
    UIA.UIA_WindowControlTypeId,
    UIA.UIA_PaneControlTypeId,
    UIA.UIA_MenuControlTypeId,
    UIA.UIA_MenuBarControlTypeId,
    UIA.UIA_ToolBarControlTypeId,
    UIA.UIA_ScrollBarControlTypeId,
    UIA.UIA_GroupControlTypeId,
}

QT_CONTAINER_TYPES = {
    UIA.UIA_ListControlTypeId,
    UIA.UIA_TreeControlTypeId,
    UIA.UIA_MenuControlTypeId,
    UIA.UIA_MenuBarControlTypeId,
    UIA.UIA_ComboBoxControlTypeId,
    UIA.UIA_DataGridControlTypeId,
}

QT_CLASS_PREFIXES = ("Q", "Qt5", "Qt6")

# Property ids can be named UIA_ValueValuePropertyId or UIA_ValuePropertyId
# depending on the comtypes typelib version; resolve once, here.
try:
    VALUE_PROP_ID = UIA.UIA_ValueValuePropertyId
except AttributeError:
    VALUE_PROP_ID = UIA.UIA_ValuePropertyId
try:
    SELECTION_PROP_ID = UIA.UIA_SelectionItemIsSelectedPropertyId
except AttributeError:
    SELECTION_PROP_ID = 30079  # UIA_SelectionItemIsSelectedPropertyId

# Focus events with the same runtime id and text within this window are
# treated as provider duplicates (Qt re-emits focus for some elements) and
# not announced again.
_FOCUS_REPEAT_WINDOW_S = 0.3

# Control types that commonly get their name from a separate QLabel in Qt
LABELABLE_TYPES = {
    UIA.UIA_ButtonControlTypeId,
    UIA.UIA_CheckBoxControlTypeId,
    UIA.UIA_RadioButtonControlTypeId,
    UIA.UIA_ComboBoxControlTypeId,
    UIA.UIA_EditControlTypeId,
    UIA.UIA_SpinnerControlTypeId,
    UIA.UIA_SliderControlTypeId,
    UIA.UIA_ListItemControlTypeId,
    UIA.UIA_TreeItemControlTypeId,
    UIA.UIA_ListControlTypeId,
    UIA.UIA_TreeControlTypeId,
    UIA.UIA_DataItemControlTypeId,
}


def _is_qt_element(el):
    try:
        framework = el.CurrentFrameworkId
        if framework and framework.lower() == "qt":
            return True
    except Exception:
        pass
    try:
        class_name = el.CurrentClassName
        if class_name:
            for prefix in QT_CLASS_PREFIXES:
                if class_name.startswith(prefix):
                    return True
    except Exception:
        pass
    return False


def _find_focused_child(uia, container):
    try:
        walker = uia.RawViewWalker
    except Exception:
        try:
            walker = uia.GetRawViewWalker()
        except Exception:
            return None
    if walker is None:
        return None
    try:
        child = walker.GetFirstChildElement(container)
        while child:
            try:
                if child.CurrentHasKeyboardFocus:
                    return child
                try:
                    sel = child.GetCurrentPattern(UIA.UIA_SelectionItemPatternId)
                    sel_item = sel.QueryInterface(UIA.IUIAutomationSelectionItemPattern)
                    if sel_item.CurrentIsSelected:
                        return child
                except Exception:
                    pass
            except Exception:
                pass
            child = walker.GetNextSiblingElement(child)
    except Exception:
        pass
    return None


class FocusChangedHandler(COMObject):
    _com_interfaces_ = [UIA.IUIAutomationFocusChangedEventHandler]

    def __init__(self, uia, callback):
        super().__init__()
        self.uia = uia
        self.callback = callback
        self._last_focused = None
        self._last_announcement = (None, "", 0.0)

    def HandleFocusChangedEvent(self, sender):
        try:
            element = sender.QueryInterface(UIA.IUIAutomationElement)

            try:
                element_name = element.CurrentName
                element_type = element.CurrentControlType
            except Exception:
                element_name = ""
                element_type = 0

            is_qt = _is_qt_element(element)

            # Chromium pages keep their accessibility tree asleep until an
            # AT performs the WM_GETOBJECT handshake -- do it on the first
            # focus inside a web document (throttled; no-op afterwards).
            if web_handler.is_web_element(element):
                web_handler.wake_web_content(element)

            if is_qt:
                # Qt workaround: containers may not expose focused child
                if element_type in QT_CONTAINER_TYPES:
                    focused_child = _find_focused_child(self.uia, element)
                    if focused_child:
                        element = focused_child
                        try:
                            element_name = focused_child.CurrentName
                            element_type = focused_child.CurrentControlType
                        except Exception:
                            pass

                # Qt workaround: suppress duplicate menu focus events
                try:
                    if element_type == UIA.UIA_MenuItemControlTypeId:
                        if self._last_focused == element_name:
                            return
                        self._last_focused = element_name
                    else:
                        self._last_focused = None
                except Exception:
                    pass

            full_description = self._get_element_desc(element, is_qt)

            # If it's a list or tree and name is empty, try to get the selected item
            control_type_id = element.CurrentControlType
            if not full_description and control_type_id in (UIA.UIA_ListControlTypeId, UIA.UIA_TreeControlTypeId):
                try:
                    selection_pattern = element.GetCurrentPattern(UIA.UIA_SelectionPatternId).QueryInterface(UIA.IUIAutomationSelectionPattern)
                    selected_items = selection_pattern.CurrentSelection
                    if selected_items.Length > 0:
                        selected_item = selected_items.GetElement(0)
                        full_description = self._get_element_desc(selected_item, is_qt)
                except Exception:
                    pass

            if full_description:
                if self._is_repeat(element, full_description):
                    return
                self.callback(full_description)
        except Exception:
            pass

    def _is_repeat(self, element, description):
        """True when the same element just produced the same description.

        Some providers (notably Qt) emit the focus-changed event twice for
        one focus change; announcing both makes everything sound doubled.
        Compares the UIA runtime id, so two different items that happen to
        describe identically still both get announced.
        """
        try:
            runtime_id = tuple(element.GetRuntimeId())
        except Exception:
            runtime_id = None
        now = time.monotonic()
        last_id, last_text, last_time = self._last_announcement
        self._last_announcement = (runtime_id, description, now)
        return (runtime_id is not None and runtime_id == last_id
                and description == last_text
                and (now - last_time) < _FOCUS_REPEAT_WINDOW_S)

    def _get_element_desc(self, el, is_qt=False):
        try:
            name = el.CurrentName
            control_type_id = el.CurrentControlType
            auto_id = el.CurrentAutomationId

            # TeamTalk5 specific: try TeamTalk description first
            if is_qt:
                tt_desc = get_teamtalk_description(el)
                if tt_desc:
                    return tt_desc

            parts = []

            # Qt-specific: get widget description from class name
            qt_widget_desc = None
            qt_class_name = None
            if is_qt:
                try:
                    qt_class_name = el.CurrentClassName
                except Exception:
                    qt_class_name = None
                qt_widget_desc = get_qt_widget_description(el) if qt_class_name else None

            # Use name if available; otherwise try to borrow the text of a
            # nearby QLabel (Qt leaves many controls without accessible names)
            if name:
                parts.append(name)
            elif is_qt and control_type_id in LABELABLE_TYPES:
                label_text = get_qt_label(el)
                if label_text:
                    parts.append(label_text)

            # Web content (Chromium): heading level and landmark parts,
            # plus a "heading" role override for heading elements.
            web_role = None
            web_parts = []
            if web_handler.is_web_element(el):
                try:
                    web_role, web_parts = web_handler.get_web_parts(el)
                except Exception:
                    web_parts = []

            # Determine role: prefer Qt widget desc, then web heading,
            # then UIA role map, then localized
            if settings.speak_roles:
                if qt_widget_desc:
                    parts.append(qt_widget_desc)
                elif web_role:
                    parts.append(web_role)
                elif control_type_id not in SILENT_ROLES_ON_FOCUS:
                    role = UIA_ROLES.get(control_type_id, "")
                    localized_role = el.CurrentLocalizedControlType
                    if role:
                        parts.append(role)
                    elif localized_role:
                        parts.append(localized_role)

            # Web heading levels and landmarks, individually gated
            if web_parts:
                heading_parts = [p for p in web_parts if p.startswith("level ")]
                landmark_parts = [p for p in web_parts if p not in heading_parts]
                if settings.speak_heading_levels:
                    parts.extend(heading_parts)
                if settings.speak_landmarks:
                    parts.extend(landmark_parts)

            # States — Qt-specific states first, then generic
            if settings.speak_states:
                if is_qt:
                    qt_states = get_qt_widget_states(el)
                    parts.extend(qt_states)

                # Generic states
                generic_states = self._get_generic_states(el)
                parts.extend(generic_states)

            # Extended properties fetched in one cached round-trip:
            # keyboard shortcut, password flag, position in set, help text.
            self._add_extended_info(el, parts)

            # Grid coordinates for data items via GridItem/TableItem:
            # "row 2" plus the column once (header name or index).
            self._add_table_position(el, parts)

            # Qt dialog description
            if is_qt and qt_class_name:
                try:
                    from qt_handler import is_qt_dialog
                    if is_qt_dialog(qt_class_name):
                        dialog_desc = get_qt_dialog_description(el)
                        if dialog_desc and dialog_desc not in " ".join(parts):
                            parts.append(dialog_desc)
                except Exception:
                    pass

            # Qt exposes automation IDs like "QApplication.QInputDialog.QComboBox"
            # (a full class path) which is useless noise; skip those.
            if auto_id and (not is_qt or "." not in auto_id):
                parts.append(f"({auto_id})")

            return " ".join(parts)
        except Exception:
            return ""

    # Extended property ids fetched together through one cache request.
    _EXTENDED_PROP_IDS = (
        UIA.UIA_AcceleratorKeyPropertyId,
        UIA.UIA_IsPasswordPropertyId,
        UIA.UIA_PositionInSetPropertyId,
        UIA.UIA_SizeOfSetPropertyId,
        UIA.UIA_HelpTextPropertyId,
        UIA.UIA_FullDescriptionPropertyId,
    )

    def _add_extended_info(self, el, parts):
        """Announce accelerators, password state, set position, help text.

        Each part is individually enabled in Output settings and everything
        is fetched in a single COM round-trip (uia_core.get_element_properties)
        to keep focus announcements fast.
        """
        try:
            props = uia_core.get_element_properties(el, self._EXTENDED_PROP_IDS)
        except Exception:
            return
        if settings.speak_accelerators:
            accelerator = str(props.get(UIA.UIA_AcceleratorKeyPropertyId) or "").strip()
            if accelerator:
                parts.append(accelerator)
        if settings.speak_password_state and props.get(UIA.UIA_IsPasswordPropertyId):
            parts.append("password protected")
        if settings.speak_position_in_set:
            try:
                position = int(props.get(UIA.UIA_PositionInSetPropertyId) or 0)
                size = int(props.get(UIA.UIA_SizeOfSetPropertyId) or 0)
            except (TypeError, ValueError):
                position = size = 0
            if position > 0 and size >= position:
                parts.append(f"{position} of {size}")
        if settings.speak_help_text:
            for text in (props.get(UIA.UIA_HelpTextPropertyId),
                         props.get(UIA.UIA_FullDescriptionPropertyId)):
                text = str(text or "").strip()
                if text and text not in parts:
                    parts.append(text)

    def _add_table_position(self, el, parts):
        """Announce grid coordinates for items inside tables/grids.

        "row R" comes from the GridItem pattern. The column is spoken once:
        the column header name via TableItem when the provider has one
        ("column Name"), otherwise the 1-based index ("column 3"). Announcing
        both forms made grid items sound like columns were announced twice.
        Silent for everything that is not a grid item.
        """
        if not settings.speak_table_positions:
            return
        try:
            grid_item = el.GetCurrentPattern(UIA.UIA_GridItemPatternId).QueryInterface(
                UIA.IUIAutomationGridItemPattern)
            row = grid_item.CurrentRow
            column = grid_item.CurrentColumn
        except Exception:
            return
        try:
            parts.append(f"row {row + 1}")
        except Exception:
            return
        header = self._grid_column_header(el)
        if header:
            parts.append(f"column {header}")
        else:
            try:
                parts.append(f"column {column + 1}")
            except Exception:
                pass

    def _grid_column_header(self, el):
        """The item's first named column header, or empty if unavailable."""
        try:
            table_item = el.GetCurrentPattern(UIA.UIA_TableItemPatternId).QueryInterface(
                UIA.IUIAutomationTableItemPattern)
            headers = table_item.GetCurrentColumnHeaderItems()
            for i in range(headers.Length):
                try:
                    name = (headers.GetElement(i).CurrentName or "").strip()
                except Exception:
                    continue
                if name:
                    return name
        except Exception:
            pass
        return ""

    def _get_generic_states(self, el):
        states = []

        try:
            if el.CurrentIsEnabled == False:
                states.append("unavailable")
        except Exception:
            pass

        try:
            if el.CurrentIsOffscreen == True and uia_core.is_offscreen_confirmed(el):
                states.append("offscreen")
        except Exception:
            pass

        # Toggle pattern — check boxes, toggle buttons
        try:
            toggle = el.GetCurrentPattern(UIA.UIA_TogglePatternId).QueryInterface(UIA.IUIAutomationTogglePattern)
            state = toggle.CurrentToggleState
            toggle_states = {0: "unchecked", 1: "checked", 2: "half checked"}
            if state in toggle_states:
                states.append(toggle_states[state])
        except Exception:
            pass

        # Selection item pattern — list items, combo items
        try:
            sel_item = el.GetCurrentPattern(UIA.UIA_SelectionItemPatternId).QueryInterface(UIA.IUIAutomationSelectionItemPattern)
            if sel_item.CurrentIsSelected:
                states.append("selected")
            else:
                states.append("not selected")
        except Exception:
            pass

        # Expand/collapse pattern — tree items, combo boxes
        try:
            expand = el.GetCurrentPattern(UIA.UIA_ExpandCollapsePatternId).QueryInterface(UIA.IUIAutomationExpandCollapsePattern)
            state = expand.CurrentExpandCollapseState
            if state == UIA.UIA_ExpandCollapseState_Expanded:
                states.append("expanded")
            elif state == UIA.UIA_ExpandCollapseState_Collapsed:
                states.append("collapsed")
        except Exception:
            pass

        return states


class ValueChangedHandler(COMObject):
    """Speaks QComboBox selection changes made with the keyboard.

    A Qt QComboBox changes its current item when Up/Down is pressed while it
    has keyboard focus -- no need to open the popup with Alt+Down first -- and
    Qt does not move input focus while doing so, so the focus-changed handler
    never fires and the screen reader stays silent. Qt instead raises UIA
    property-changed events: the combo's Value property for the whole-control
    change, and the items' selection state while a popup list is open. This
    handler announces those, so arrowing through the list reads each item.
    """

    _com_interfaces_ = [UIA.IUIAutomationPropertyChangedEventHandler]

    # Qt widgets whose value changes with the keyboard and should be spoken
    # (spin boxes, sliders, date/time edits). Edit boxes are deliberately
    # absent -- typing there must not echo the whole text on every key.
    _VALUED_QT_CLASSES = ("QComboBox", "QSpinBox", "QDoubleSpinBox",
                          "QSlider", "QDateTimeEdit", "QDateEdit", "QTimeEdit")

    def __init__(self, uia, callback):
        super().__init__()
        self.uia = uia
        self.callback = callback
        self._last_spoken = ""

    def HandlePropertyChangedEvent(self, sender, property_id, new_value):
        try:
            if new_value is None:
                return
            element = sender.QueryInterface(UIA.IUIAutomationElement)
            if property_id == VALUE_PROP_ID:
                text = str(new_value).strip()
                if text:
                    self._announce_value_change(element, text)
            elif property_id == SELECTION_PROP_ID:
                if new_value is True or new_value == 1:
                    self._announce_item_selected(element)
        except Exception:
            pass

    def _announce_value_change(self, element, text):
        # Whole-combo events arrive on the combo element itself. Only Qt
        # combos need this path -- native ones move focus on arrows and are
        # already announced by the focus handler.
        try:
            if element.CurrentControlType == UIA.UIA_ComboBoxControlTypeId:
                if _is_qt_element(element):
                    self._announce(text, element)
                return
        except Exception:
            return
        # Spinners/sliders/date edits also change value via keyboard while
        # focused; announce those too (real Qt widgets only, not edits).
        try:
            class_name = element.CurrentClassName or ""
        except Exception:
            return
        if any(token in class_name for token in self._VALUED_QT_CLASSES):
            self._announce(text, element)

    def _announce_item_selected(self, element):
        # A popup item became selected while the list is open.
        try:
            text = (element.CurrentName or "").strip()
        except Exception:
            return
        if text and _is_qt_element(element):
            self._announce(text, element)

    def _announce(self, text, element):
        # Qt often raises both a value event and an item-selection event for
        # the same change -- don't speak the same text twice in a row.
        if not text or text == self._last_spoken:
            return
        try:
            focused = element.CurrentHasKeyboardFocus
        except Exception:
            focused = False
        # Only announce when the element is focused (arrows on the closed
        # combo) or lives inside an open combo popup. This keeps list/tree
        # selections elsewhere from being announced out of context.
        if not focused and not self._inside_qt_combo(element):
            return
        self._last_spoken = text
        self.callback(text)

    def _inside_qt_combo(self, element):
        """True when element hangs off a Qt combo box in the UIA tree."""
        try:
            walker = self.uia.RawViewWalker
        except Exception:
            return False
        try:
            current = walker.GetParentElement(element)
        except Exception:
            return False
        depth = 0
        while current is not None and depth < 8:
            try:
                if current.CurrentControlType == UIA.UIA_ComboBoxControlTypeId:
                    return True
                class_name = current.CurrentClassName or ""
                if "QComboBox" in class_name:
                    return True
            except Exception:
                pass
            try:
                current = walker.GetParentElement(current)
            except Exception:
                return False
            depth += 1
        return False
