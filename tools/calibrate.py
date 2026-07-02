"""Interactive calibration. Run:  python tools/calibrate.py

Hover the mouse over targets in the live game and press hotkeys (read globally,
so the Roblox window can stay focused): F8 = capture/confirm, F9 = skip (use a
default), F10 = continue, ESC = abort.

Coordinates are saved as fractions of the Roblox window client area.
"""
import os
import sys
import time

import cv2
import win32api

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src import appconfig
from src.window import RobloxWindow
from src.capture import ScreenCapture
from src.vision import Vision
from src.parser import group_items, dedupe

VK = {"f7": 0x76, "f8": 0x77, "f9": 0x78, "f10": 0x79, "esc": 0x1B}


def _down(vk):
    return win32api.GetAsyncKeyState(vk) & 0x8000


def wait_keys(keys=("f8", "f9")):
    watch = list(keys) + (["esc"] if "esc" not in keys else [])
    while any(_down(VK[k]) for k in watch):          # wait for release first
        time.sleep(0.02)
    while True:
        for k in watch:
            if _down(VK[k]):
                while _down(VK[k]):
                    time.sleep(0.02)
                if k == "esc":
                    raise SystemExit("\nCalibration aborted (ESC).")
                return k
        time.sleep(0.02)


def gate(msg):
    print("\n>>> " + msg)
    print(">>> When you are ready, press F10  (ESC to quit).")
    wait_keys(("f10",))


def capture_point(window, label):
    print(f"\n[{label}]")
    print("    Hover the cursor over the CENTER of the target and press F8  (F9 to skip).")
    if wait_keys(("f8", "f9")) == "f9":
        print("    skipped")
        return None
    x, y = win32api.GetCursorPos()
    fx, fy = window.from_screen(x, y)
    print(f"    screen=({x},{y})  fraction=({fx:.4f},{fy:.4f})")
    return [round(fx, 4), round(fy, 4)]


def capture_region(window, label, default=None):
    print(f"\n[{label}]")
    print("    TOP-LEFT corner → F8   (F9 to use the default zone).")
    if wait_keys(("f8", "f9")) == "f9":
        print(f"    default zone: {default}")
        return default
    x1, y1 = win32api.GetCursorPos()
    print("    Now the BOTTOM-RIGHT corner → F8.")
    wait_keys(("f8",))
    x2, y2 = win32api.GetCursorPos()
    fx1, fy1 = window.from_screen(min(x1, x2), min(y1, y2))
    fx2, fy2 = window.from_screen(max(x1, x2), max(y1, y2))
    frac = [round(fx1, 4), round(fy1, 4), round(fx2 - fx1, 4), round(fy2 - fy1, 4)]
    print(f"    region fraction={frac}")
    return frac


def ocr_test(window, capture, vision, cfg):
    print("\n=== OCR TEST (item list recognition) ===")
    reg = cfg["regions"].get("item_list")
    if not reg:
        print("    item_list is not set — skipping.")
        return
    img = capture.grab(window.region_px(reg))
    dbg = os.path.join(HERE, cfg["debug"]["dir"])
    os.makedirs(dbg, exist_ok=True)
    cv2.imwrite(os.path.join(dbg, "calib_itemlist.png"), img)
    print("    recognizing (the first run will download the OCR model)…")
    lines = vision.ocr_lines(img)
    items = dedupe(group_items(lines, img.shape[0]))
    print(f"    OCR lines: {len(lines)}   items: {len(items)}")
    for it in items:
        print(f"      • {it['name']} | rarity={it['rarity']} | stock={it['stock']}")
    print(f"    (screenshot saved to {os.path.join(cfg['debug']['dir'], 'calib_itemlist.png')})")


def scroll_calibration(window, capture, vision, cfg):
    """Quick add-on: the close X + the "Country" return button."""
    print("\n=== EXTRA CALIBRATION: close button + return ===")
    gate("Open the shop.")
    cfg["buttons"]["close_x"] = capture_point(
        window, "Red X button (closes the shop) — hover exactly over its center")
    gate("Now CLOSE the shop with the X button (you will stay in the 3D view near the vendor).")
    cfg["buttons"]["country"] = capture_point(
        window, '"Country" button (the one that takes you back to the main screen)')
    appconfig.save(cfg)
    print("\nconfig.json saved.")
    ocr_test(window, capture, vision, cfg)
    print("\nDone. Run:  python run.py")


def main():
    cfg = appconfig.load()
    w = cfg["window"]
    window = RobloxWindow(w.get("title_contains", "Roblox"), w.get("class_name", "WINDOWSCLIENT"))
    capture = ScreenCapture()
    vision = Vision(cfg)

    print("=" * 60)
    print(" Roblox shop bot CALIBRATION")
    print("=" * 60)
    try:
        window.find()
    except Exception as e:
        print(f"error: {e}")
        return
    window.focus()
    rect = window.client_rect()
    print(f"Roblox window found. Client area: {rect[2]}x{rect[3]} px")
    print("Do not move or resize the Roblox window until calibration is finished.")

    if "scroll" in sys.argv[1:]:
        scroll_calibration(window, capture, vision, cfg)
        return

    # --- 1. main map ---
    gate("Open the country's MAIN screen (the Buy / Country / Sell buttons are visible).")
    cfg["buttons"]["buy"] = capture_point(window, '"Buy" button')
    cfg["regions"]["refill_banner"] = capture_region(
        window, 'Zone of the green "Shop has been restocked!" message (top center)',
        default=[0.30, 0.10, 0.40, 0.12])

    # --- 2. shop open ---
    gate("Now OPEN the shop (press E). A window with the Factory/Houses/Military/Special tabs should appear.")
    cfg["buttons"]["tab_factory"] = capture_point(window, '"Factory" tab')
    cfg["buttons"]["tab_houses"] = capture_point(window, '"Houses" tab')
    cfg["buttons"]["tab_military"] = capture_point(window, '"Military" tab')
    cfg["buttons"]["tab_special"] = capture_point(window, '"Special" tab')
    cfg["buttons"]["close_x"] = capture_point(window, "Close button (red X)")
    cfg["regions"]["shop_window"] = capture_region(
        window, "The entire shop window (top-left → bottom-right)",
        default=[0.18, 0.05, 0.64, 0.90])
    cfg["regions"]["item_list"] = capture_region(
        window, "The item LIST area (below the tabs down to the bottom of the window)",
        default=[0.20, 0.30, 0.60, 0.60])

    appconfig.save(cfg)
    print("\nconfig.json saved.")

    ocr_test(window, capture, vision, cfg)

    print("\n" + "=" * 60)
    print(" Calibration complete. Run:  python run.py")
    print("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        print(e)
