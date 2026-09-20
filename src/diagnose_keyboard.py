"""Keyboard diagnostic for TechReader.

Shows live keyboard events from the native hook layer so you can verify
what TechReader sees: key down/up, virtual-key, scan code, flags
(injected, extended, alt), and the modifier bitmask.

Usage:
    python src/diagnose_keyboard.py [seconds]

Runs for 15 seconds by default (or press Ctrl+C to stop earlier). Nothing
is suppressed or changed: every key still reaches your applications, and
injected events are shown with the [injected] marker.

Interpreter also reports whether the native DLL was found and whether the
python-keyboard fallback would be used.
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import native_keyboard as nk

VK_NAMES = {
    0x01: "LeftButton", 0x02: "RightButton", 0x04: "MiddleButton",
    0x08: "Back", 0x09: "Tab", 0x0D: "Return", 0x10: "Shift",
    0x11: "Control", 0x12: "Menu", 0x13: "Pause", 0x14: "Capital",
    0x1B: "Escape", 0x20: "Space", 0x21: "Prior", 0x22: "Next",
    0x23: "End", 0x24: "Home", 0x25: "Left", 0x26: "Up", 0x27: "Right",
    0x28: "Down", 0x2D: "Insert", 0x2E: "Delete",
    0x5B: "LWin", 0x5C: "RWin", 0x5D: "Apps",
    0x60: "Num0", 0x61: "Num1", 0x62: "Num2", 0x63: "Num3", 0x64: "Num4",
    0x65: "Num5", 0x66: "Num6", 0x67: "Num7", 0x68: "Num8", 0x69: "Num9",
    0x6A: "Multiply", 0x6B: "Add", 0x6D: "Subtract", 0x6E: "Decimal",
    0x6F: "Divide", 0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4",
    0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8", 0x78: "F9",
    0x79: "F10", 0x7A: "F11", 0x7B: "F12", 0x87: "F24",
    0xA0: "LShift", 0xA1: "RShift", 0xA2: "LControl", 0xA3: "RControl",
    0xA4: "LMenu", 0xA5: "RMenu", 0x90: "NumLock", 0x91: "Scroll",
}

TYPE_NAMES = {0: "down", 1: "up", 2: "sys down", 3: "sys up"}

MOD_NAMES = [
    ("LCtrl", nk.TRK_MOD_LCTRL), ("RCtrl", nk.TRK_MOD_RCTRL),
    ("LShift", nk.TRK_MOD_LSHIFT), ("RShift", nk.TRK_MOD_RSHIFT),
    ("LAlt", nk.TRK_MOD_LALT), ("RAlt", nk.TRK_MOD_RALT),
    ("LWin", nk.TRK_MOD_LWIN), ("RWin", nk.TRK_MOD_RWIN),
    ("Caps", nk.TRK_MOD_CAPS), ("Num", nk.TRK_MOD_NUM),
    ("CapsOn", nk.TRK_MOD_CAPS_ON), ("NumOn", nk.TRK_MOD_NUM_ON),
]


def describe_mods(mask):
    names = [name for name, bit in MOD_NAMES if mask & bit]
    return "+".join(names) if names else "-"


def main():
    seconds = 15
    if len(sys.argv) > 1:
        try:
            seconds = max(3, int(sys.argv[1]))
        except ValueError:
            print(f"ignoring non-numeric argument: {sys.argv[1]!r}")

    print("TechReader keyboard diagnostic")
    print("-" * 60)
    print(f"native DLL present: {nk.is_available()}")
    try:
        import keyboard  # noqa: F401
        print("python-keyboard importable: True (fallback available)")
    except Exception as exc:
        print(f"python-keyboard importable: False ({exc})")
    print("-" * 60)

    commands = []
    kb = nk.NativeKeyboard(
        on_command=lambda cmd: commands.append(cmd),
        on_error=lambda exc: print(f"keyboard error: {exc}"))

    if not kb.start():
        print("FAILED to start the native hook (is another debugger or"
              " security software blocking low-level hooks?)")
        return 1
    print(f"native hook running: {kb.running}")
    print(f"press keys now; showing events for {seconds} s "
          "(Ctrl+C stops early)\n")

    deadline = time.time() + seconds
    count = 0
    try:
        while time.time() < deadline:
            try:
                ev = kb._queue.get(timeout=0.2)
            except Exception:
                continue
            count += 1
            vk = ev["vk"]
            name = VK_NAMES.get(vk, f"0x{vk:02X}")
            marks = []
            if ev["flags"] & nk.TRK_FLAG_INJECTED:
                marks.append("injected")
            if ev["flags"] & nk.TRK_FLAG_EXTENDED:
                marks.append("ext")
            mark = (" [" + ",".join(marks) + "]") if marks else ""
            cmd = nk.detect_command(ev)
            cmd_note = f"  -> command: {cmd}" if cmd else ""
            print(f"{ev['time_ms'] % 100000:7d}  {TYPE_NAMES[ev['event_type']]:8s}"
                  f" {name:12s} scan={ev['scan_code']:<3d}"
                  f" mods={describe_mods(ev['modifier_state'])}{mark}{cmd_note}")
    except KeyboardInterrupt:
        print("\nstopped early")
    finally:
        kb.stop()

    print("-" * 60)
    print(f"{count} events seen, {len(commands)} commands produced: "
          f"{commands if commands else '(none)'}")
    print("expected commands: Ctrl down -> 'interrupt',"
          " CapsLock+Space -> 'menu'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
