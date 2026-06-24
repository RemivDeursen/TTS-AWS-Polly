import ctypes


POLL_INTERVAL_MS = 25
VK_RETURN = 0x0D
VK_SCROLL = 0x91


def get_foreground_window_title():
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return ""

    length = user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""

    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def discord_is_foreground():
    return "discord" in get_foreground_window_title().lower()


def scroll_lock_is_on():
    return bool(ctypes.windll.user32.GetKeyState(VK_SCROLL) & 0x0001)


def return_key_is_down():
    return bool(ctypes.windll.user32.GetAsyncKeyState(VK_RETURN) & 0x8000)


def get_focused_uia_text():
    try:
        from pywinauto.controls.uiawrapper import UIAWrapper
        from pywinauto.uia_defines import get_elem_interface
        from pywinauto.uia_defines import IUIA
        from pywinauto.uia_element_info import UIAElementInfo
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: install pywinauto with "
            "`python -m pip install pywinauto`."
        ) from exc

    try:
        element = IUIA().get_focused_element()
    except Exception as exc:
        raise RuntimeError(
            "Could not read the focused Windows UI Automation element. "
            "Try focusing Discord's message box and enable Discord again."
        ) from exc

    candidates = []

    try:
        element_info = UIAElementInfo(element)
        wrapper = UIAWrapper(element_info)
    except Exception:
        wrapper = None

    if wrapper is not None:
        try:
            value = wrapper.iface_value.CurrentValue
            if value:
                candidates.append(value)
        except Exception:
            pass

        try:
            legacy_value = wrapper.legacy_properties().get("Value")
            if legacy_value:
                candidates.append(legacy_value)
        except Exception:
            pass

        try:
            text = wrapper.window_text()
            if text:
                candidates.append(text)
        except Exception:
            pass

    try:
        value = get_elem_interface(element, "Value").CurrentValue
        if value:
            candidates.append(value)
    except Exception:
        pass

    try:
        legacy_value = get_elem_interface(element, "LegacyIAccessible").CurrentValue
        if legacy_value:
            candidates.append(legacy_value)
    except Exception:
        pass

    try:
        text = get_elem_interface(element, "Text").DocumentRange.GetText(-1)
        if text:
            candidates.append(text)
    except Exception:
        pass

    try:
        name = element.CurrentName
        if name:
            candidates.append(name)
    except Exception:
        pass

    cleaned = [
        candidate.strip()
        for candidate in candidates
        if candidate and candidate.strip()
    ]
    cleaned = [
        candidate
        for candidate in cleaned
        if not candidate.lower().startswith(("message #", "message @"))
    ]

    return max(cleaned, key=len) if cleaned else ""
