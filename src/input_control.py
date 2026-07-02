"""Low-level mouse/keyboard input for the Roblox client via Windows SendInput.

SendInput delivers hardware-style events, which is what the game actually reads
(PostMessage is ignored for gameplay). Keys go out as scancodes rather than
virtual keys; UI clicks go out as absolute moves plus button events.
"""
from __future__ import annotations

import time
import ctypes
from ctypes import wintypes

import win32api

user32 = ctypes.WinDLL("user32", use_last_error=True)
user32.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
SendInput = user32.SendInput

# ---- ctypes SendInput plumbing ------------------------------------------
ULONG_PTR = ctypes.POINTER(ctypes.c_ulong)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long),
                ("mouseData", ctypes.c_ulong), ("dwFlags", ctypes.c_ulong),
                ("time", ctypes.c_ulong), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort),
                ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong),
                ("dwExtraInfo", ULONG_PTR)]


class _INPUTunion(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", ctypes.c_ulong), ("u", _INPUTunion)]


INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_EXTENDEDKEY = 0x0001

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000


def _norm(x, y):
    """Normalize screen pixels to 0..65535 over the whole virtual desktop."""
    vx = win32api.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    vy = win32api.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    vw = win32api.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    vh = win32api.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
    return (int(round((x - vx) * 65535.0 / max(1, vw - 1))),
            int(round((y - vy) * 65535.0 / max(1, vh - 1))))


def _abs_move(x, y):
    """Move the cursor with a real SendInput absolute move (generates the
    WM_MOUSEMOVE that Roblox's UI needs to register hover) — multi-monitor safe."""
    nx, ny = _norm(x, y)
    _send(_mouse(dx=nx, dy=ny,
                 flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK))


def _abs_button(x, y, btn_flag):
    """Send a button down/up event that also carries the absolute position, so
    the press/release is unambiguously at the target pixel."""
    nx, ny = _norm(x, y)
    _send(_mouse(dx=nx, dy=ny,
                 flags=MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK | btn_flag))

# Set-1 scancodes (make codes)
SCAN = {
    "w": 0x11, "a": 0x1E, "s": 0x1F, "d": 0x20, "e": 0x12,
    "q": 0x10, "space": 0x39, "esc": 0x01, "1": 0x02, "2": 0x03, "3": 0x04,
}


class InputBlockedError(OSError):
    pass


def _send(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))
    if sent == 0:
        err = ctypes.get_last_error()
        raise InputBlockedError(
            err,
            f"Windows blocked input into Roblox (code {err}). This usually means "
            "the Roblox window is not active, or Roblox is running as administrator — "
            "in that case run the bot as administrator too.")


def _mouse(dx=0, dy=0, flags=0, data=0):
    return INPUT(type=INPUT_MOUSE,
                 u=_INPUTunion(mi=MOUSEINPUT(dx, dy, data, flags, 0, None)))


def _key(scan, flags):
    return INPUT(type=INPUT_KEYBOARD,
                 u=_INPUTunion(ki=KEYBDINPUT(0, scan, flags | KEYEVENTF_SCANCODE,
                                             0, None)))


class InputController:
    # ---- mouse: UI ----------------------------------------------------
    def move(self, x: int, y: int):
        # SendInput absolute move (not SetCursorPos) so Roblox actually sees the
        # mouse move and updates button hover state before we click.
        _abs_move(int(x), int(y))

    def glide_to(self, x: int, y: int, steps: int = 12):
        """Move the cursor to (x,y) in small steps with a tiny jiggle at the end.
        Roblox only registers hover from movement into a button — an instant
        cursor teleport leaves it un-hovered and the click is ignored."""
        x, y = int(x), int(y)
        try:
            cx, cy = win32api.GetCursorPos()
        except Exception:
            cx, cy = x - 40, y - 40
        dist = max(abs(x - cx), abs(y - cy))
        n = max(4, min(steps, dist if dist > 0 else 4))
        for i in range(1, n + 1):
            ix = int(round(cx + (x - cx) * i / n))
            iy = int(round(cy + (y - cy) * i / n))
            _abs_move(ix, iy)
            time.sleep(0.012)
        _abs_move(x + 2, y + 2)   # jiggle so hover-enter definitely fires
        time.sleep(0.02)
        _abs_move(x, y)
        time.sleep(0.02)

    def click(self, x: int, y: int, delay: float = 0.12, double: bool = False):
        x, y = int(x), int(y)
        self.glide_to(x, y)
        time.sleep(0.22)  # let hover register before pressing
        _abs_button(x, y, MOUSEEVENTF_LEFTDOWN)
        time.sleep(delay)
        _abs_button(x, y, MOUSEEVENTF_LEFTUP)
        if double:
            time.sleep(0.06)
            _abs_button(x, y, MOUSEEVENTF_LEFTDOWN)
            time.sleep(delay)
            _abs_button(x, y, MOUSEEVENTF_LEFTUP)
        time.sleep(0.16)

    def scroll(self, clicks: int):
        # positive = up, negative = down
        _send(_mouse(flags=MOUSEEVENTF_WHEEL, data=int(clicks) * 120))
        time.sleep(0.03)

    # ---- keyboard -----------------------------------------------------
    @staticmethod
    def _scan(name: str):
        sc = SCAN.get(name)
        if sc is None:
            raise ValueError(f"Unknown key: {name!r}")
        return sc

    def key_down(self, name: str):
        _send(_key(self._scan(name), 0))

    def key_up(self, name: str):
        _send(_key(self._scan(name), KEYEVENTF_KEYUP))

    def tap(self, name: str, hold: float = 0.05):
        self.key_down(name)
        time.sleep(hold)
        self.key_up(name)
        time.sleep(0.03)

    def hold_key(self, name: str, seconds: float):
        self.key_down(name)
        time.sleep(seconds)
        self.key_up(name)
        time.sleep(0.03)
