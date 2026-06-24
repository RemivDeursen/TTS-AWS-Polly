import ctypes

from .discord_monitor import get_foreground_window_title


WOWLINK_POLL_INTERVAL_MS = 25
VK_BACK = 0x08
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_DELETE = 0x2E

IGNORED_KEYS = {
    VK_PRIOR,
    VK_NEXT,
    VK_END,
    VK_HOME,
    VK_LEFT,
    VK_UP,
    VK_RIGHT,
    VK_DOWN,
    VK_DELETE,
}

CHAT_COMMANDS = {
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "e",
    "em",
    "emote",
    "g",
    "guild",
    "i",
    "instance",
    "p",
    "party",
    "r",
    "raid",
    "rw",
    "s",
    "say",
    "w",
    "whisper",
    "y",
    "yell",
}


def wow_is_foreground():
    title = get_foreground_window_title().lower()
    return "world of warcraft" in title or title == "wow"


def key_is_down(virtual_key):
    return bool(ctypes.windll.user32.GetAsyncKeyState(virtual_key) & 0x8000)


def virtual_key_to_text(virtual_key):
    if virtual_key == VK_SPACE:
        return " "

    user32 = ctypes.windll.user32
    keyboard_state = (ctypes.c_ubyte * 256)()
    if not user32.GetKeyboardState(ctypes.byref(keyboard_state)):
        return ""

    scan_code = user32.MapVirtualKeyW(virtual_key, 0)
    buffer = ctypes.create_unicode_buffer(8)
    result = user32.ToUnicode(
        virtual_key,
        scan_code,
        keyboard_state,
        buffer,
        len(buffer),
        0,
    )

    if result <= 0:
        return ""

    return buffer.value[:result]


def parse_wow_chat_message(raw_message):
    message = raw_message.strip()
    if not message:
        return None

    if not message.startswith("/"):
        return message

    command_text = message[1:].strip()
    if not command_text:
        return None

    command, _, rest = command_text.partition(" ")
    command = command.lower()
    if command not in CHAT_COMMANDS:
        return None

    return rest.strip() or None


class WowKeyboardCapture:
    def __init__(self):
        self.chat_open = False
        self.buffer = []
        self.keys_down = set()

    def reset(self):
        self.chat_open = False
        self.buffer = []
        self.keys_down = set()

    def poll(self):
        pressed = []

        for virtual_key in range(1, 256):
            is_down = key_is_down(virtual_key)
            was_down = virtual_key in self.keys_down

            if is_down and not was_down:
                pressed.append(virtual_key)
                self.keys_down.add(virtual_key)
            elif not is_down and was_down:
                self.keys_down.remove(virtual_key)

        submitted = []
        for virtual_key in pressed:
            submitted_text = self.handle_key_press(virtual_key)
            if submitted_text:
                submitted.append(submitted_text)

        return submitted

    def handle_key_press(self, virtual_key):
        if virtual_key == VK_RETURN:
            if not self.chat_open:
                self.chat_open = True
                self.buffer = []
                return None

            text = parse_wow_chat_message("".join(self.buffer))
            self.chat_open = False
            self.buffer = []
            return text

        if not self.chat_open:
            return None

        if virtual_key == VK_ESCAPE:
            self.chat_open = False
            self.buffer = []
            return None

        if virtual_key == VK_BACK:
            if self.buffer:
                self.buffer.pop()
            return None

        if virtual_key in IGNORED_KEYS:
            return None

        text = virtual_key_to_text(virtual_key)
        if text and text.isprintable():
            self.buffer.append(text)

        return None
