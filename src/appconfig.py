"""Load/save config.json (kept in the project root, next to run.py)."""
from __future__ import annotations

import os
import json

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config.json")


def load():
    with open(CONFIG_PATH, encoding="utf-8") as f:
        return json.load(f)


def save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
