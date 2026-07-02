"""Tiny status channel between the running bot and the launcher overlay.

The bot writes logs/status.json (merged on write, so counters persist across
writes); the launcher overlay polls read(). Best-effort.
"""
from __future__ import annotations

import os
import json
import time

from src import appconfig

PATH = os.path.join(appconfig.ROOT, "logs", "status.json")


def write(state: str, action: str, **extra) -> None:
    try:
        d = read() or {}
        d.update({"ts": int(time.time()), "state": state, "action": action})
        d.update(extra)
        os.makedirs(os.path.dirname(PATH), exist_ok=True)
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, PATH)
    except Exception:
        pass


def read() -> dict | None:
    try:
        with open(PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def clear() -> None:
    try:
        os.remove(PATH)
    except OSError:
        pass
