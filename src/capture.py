"""Fast screen capture via mss, returning OpenCV-style BGR numpy arrays.

An mss instance is not thread-safe; create one ScreenCapture per thread.
"""
from __future__ import annotations

import numpy as np
import mss


class ScreenCapture:
    def __init__(self):
        self._sct = mss.mss()

    def reset(self):
        """Recreate the mss instance. A long-lived handle can silently return frozen
        frames after a display/session transition; recreating it recovers capture."""
        try:
            self._sct.close()
        except Exception:
            pass
        self._sct = mss.mss()

    def grab(self, box):
        """box = (left, top, width, height) in absolute screen pixels.

        Returns an HxWx3 BGR uint8 array. On a grab error, recreates mss once and retries.
        """
        left, top, width, height = box
        width = max(1, int(width))
        height = max(1, int(height))
        region = {"left": int(left), "top": int(top), "width": width, "height": height}
        try:
            raw = self._sct.grab(region)
        except Exception:
            self.reset()
            raw = self._sct.grab(region)
        img = np.asarray(raw)  # BGRA
        return np.ascontiguousarray(img[:, :, :3])  # -> BGR

    def grab_window(self, window):
        """Capture the full client area of a RobloxWindow."""
        return self.grab(window.client_rect())

    def close(self):
        try:
            self._sct.close()
        except Exception:
            pass
