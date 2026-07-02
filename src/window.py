"""Locate, focus, and map coordinates for the Roblox client window.

Button/region coordinates in config are fractions (0..1) of the window's
client area, so they survive window moves and resolution changes. This module
converts them to absolute screen pixels on demand.
"""
from __future__ import annotations

import time
import ctypes

import win32gui
import win32con
import win32api
import win32process

user32 = ctypes.windll.user32
user32.SetActiveWindow.argtypes = [ctypes.c_void_p]  # HWND is pointer-sized on x64
user32.SetActiveWindow.restype = ctypes.c_void_p


class RobloxWindowError(RuntimeError):
    pass


class RobloxWindow:
    def __init__(self, title_contains: str = "Roblox", class_name: str = "WINDOWSCLIENT"):
        self.title_contains = (title_contains or "").lower()
        self.class_name = class_name or ""
        self.hwnd = None

    # ---- discovery -------------------------------------------------------
    def find(self):
        """Find the Roblox client window handle. Raises if not found."""
        matches = []

        def _cb(hwnd, _):
            if not win32gui.IsWindowVisible(hwnd):
                return True
            try:
                title = win32gui.GetWindowText(hwnd)
                cls = win32gui.GetClassName(hwnd)
            except Exception:
                return True
            cls_ok = self.class_name and cls == self.class_name
            title_ok = self.title_contains and self.title_contains in title.lower()
            if cls_ok or (title_ok and title.strip()):
                # ignore zero-size windows
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                if (r - l) > 200 and (b - t) > 200:
                    matches.append((hwnd, title, cls))
            return True

        win32gui.EnumWindows(_cb, None)

        # prefer an exact class match, otherwise the largest matching window
        best = None
        for hwnd, title, cls in matches:
            if self.class_name and cls == self.class_name:
                best = hwnd
                break
        if best is None and matches:
            best = max(matches, key=lambda m: self._area(m[0]))[0]

        if best is None:
            raise RobloxWindowError(
                "Roblox window not found. Start the game and make sure the window is open."
            )
        self.hwnd = best
        return best

    @staticmethod
    def _area(hwnd):
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        return (r - l) * (b - t)

    def ensure(self):
        if self.hwnd is None or not win32gui.IsWindow(self.hwnd):
            self.find()
        return self.hwnd

    # ---- geometry --------------------------------------------------------
    def client_rect(self):
        """(left, top, width, height) of the client area in screen pixels."""
        self.ensure()
        l, t, r, b = win32gui.GetClientRect(self.hwnd)
        sx, sy = win32gui.ClientToScreen(self.hwnd, (l, t))
        ex, ey = win32gui.ClientToScreen(self.hwnd, (r, b))
        return sx, sy, ex - sx, ey - sy

    def to_screen(self, fx: float, fy: float):
        """Fractional client coord (0..1) -> absolute screen pixel (x, y)."""
        x, y, w, h = self.client_rect()
        return int(round(x + fx * w)), int(round(y + fy * h))

    def from_screen(self, px: int, py: int):
        """Absolute screen pixel -> fractional client coord (0..1)."""
        x, y, w, h = self.client_rect()
        if w == 0 or h == 0:
            return 0.0, 0.0
        return (px - x) / w, (py - y) / h

    def region_px(self, frac):
        """[fx, fy, fw, fh] fractional region -> (left, top, width, height) px."""
        x, y, w, h = self.client_rect()
        fx, fy, fw, fh = frac
        return (
            int(round(x + fx * w)),
            int(round(y + fy * h)),
            int(round(fw * w)),
            int(round(fh * h)),
        )

    def center_px(self):
        x, y, w, h = self.client_rect()
        return x + w // 2, y + h // 2

    # ---- focus -----------------------------------------------------------
    def is_foreground(self) -> bool:
        self.ensure()
        return win32gui.GetForegroundWindow() == self.hwnd

    def focus(self, retries: int = 5):
        """Bring the Roblox window to the foreground (best effort)."""
        self.ensure()
        hwnd = self.hwnd
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)

        for _ in range(retries):
            if self.is_foreground():
                return True
            try:
                # Windows blocks SetForegroundWindow unless the caller owns the
                # foreground; tap ALT and attach to the foreground thread to get past that.
                self._send_alt()
                fg = win32gui.GetForegroundWindow()
                cur_t = win32api.GetCurrentThreadId()
                fg_t, _ = win32process.GetWindowThreadProcessId(fg)
                tgt_t, _ = win32process.GetWindowThreadProcessId(hwnd)
                attached = []
                for a, b in ((cur_t, fg_t), (cur_t, tgt_t)):
                    if a != b:
                        try:
                            win32process.AttachThreadInput(a, b, True)
                            attached.append((a, b))
                        except Exception:
                            pass
                try:
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                    user32.SetActiveWindow(hwnd)
                finally:
                    for a, b in attached:
                        try:
                            win32process.AttachThreadInput(a, b, False)
                        except Exception:
                            pass
            except Exception:
                pass
            time.sleep(0.12)
        return self.is_foreground()

    @staticmethod
    def _send_alt():
        # tap ALT to satisfy the foreground-lock timeout
        win32api.keybd_event(win32con.VK_MENU, 0, 0, 0)
        win32api.keybd_event(win32con.VK_MENU, 0, win32con.KEYEVENTF_KEYUP, 0)


if __name__ == "__main__":
    w = RobloxWindow()
    w.find()
    print("hwnd:", w.hwnd)
    print("title:", win32gui.GetWindowText(w.hwnd))
    print("client_rect (l,t,w,h):", w.client_rect())
    print("focused:", w.focus())
