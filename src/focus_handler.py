import comtypes
from comtypes import COMObject
import comtypes.gen.UIAutomationClient as UIA
import settings
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


def _find_focused_child(self, container):
    try:
        walker = self.uia.RawViewWalker
    except Exception:
        try:
            walker = self.uia.GetRawViewWalker()
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

            if is_qt:
                # Qt workaround: containers may not expose focused child
                if element_type in QT_CONTAINER_TYPES:
                    focused_child = self._find_focused_child(element)
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
                self.callback(full_description)
        except Exception:
            pass

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

            # Determine role: prefer Qt widget desc, then UIA role map, then localized
            if settings.speak_roles:
                if qt_widget_desc:
                    parts.append(qt_widget_desc)
                elif control_type_id not in SILENT_ROLES_ON_FOCUS:
                    role = UIA_ROLES.get(control_type_id, "")
                    localized_role = el.CurrentLocalizedControlType
                    if role:
                        parts.append(role)
                    elif localized_role:
                        parts.append(localized_role)

            # States — Qt-specific states first, then generic
            if settings.speak_states:
                if is_qt:
                    qt_states = get_qt_widget_states(el)
                    parts.extend(qt_states)

                # Generic states
                generic_states = self._get_generic_states(el)
                parts.extend(generic_states)

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

    def _get_generic_states(self, el):
        states = []

        try:
            if el.CurrentIsEnabled == False:
                states.append("unavailable")
        except Exception:
            pass

        try:
            if el.CurrentIsOffscreen == True:
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
