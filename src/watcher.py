"""Main loop: watch for the green "Shop has been restocked!" banner, then run a check.

When the banner is detected the bot opens the shop, OCR-reads each category, and buys any
item you selected in config.json (buy.items). A single non-blocking lock guards the shop
read/buy flow so nothing fights over the mouse or the (single) OCR engine.
"""
from __future__ import annotations

import os
import time
import threading
from datetime import datetime

import cv2

from src import appconfig, botstatus
from src.window import RobloxWindow, RobloxWindowError
from src.capture import ScreenCapture
from src.vision import Vision
from src.input_control import InputController
from src.navigator import Navigator, NavigationError


def _prune_dir(path, keep):
    """Keep only the newest `keep` files in `path` by mtime (0 = delete all). Best-effort."""
    try:
        files = [os.path.join(path, f) for f in os.listdir(path)]
        files = [f for f in files if os.path.isfile(f)]
    except OSError:
        return
    if len(files) <= keep:
        return
    files.sort(key=lambda f: os.path.getmtime(f), reverse=True)
    for f in files[keep:]:
        try:
            os.remove(f)
        except OSError:
            pass


class Watcher:
    def __init__(self):
        self.root = appconfig.ROOT
        self.cfg = appconfig.load()

        w = self.cfg["window"]
        self.window = RobloxWindow(w.get("title_contains", "Roblox"),
                                   w.get("class_name", "WINDOWSCLIENT"))
        self.capture = ScreenCapture()
        self.banner_capture = ScreenCapture()
        self.vision = Vision(self.cfg)
        self.inp = InputController()
        self.navigator = Navigator(self.cfg, self.window, self.capture,
                                   self.vision, self.inp, self.root, log=self._log)

        self._check_lock = threading.Lock()
        self._stop = threading.Event()
        self._last_results = None
        self._last_time = "not yet"
        self._last_error = None
        self._checks = 0
        self._buys = 0

        try:
            logdir = os.path.join(self.root, "logs")
            os.makedirs(logdir, exist_ok=True)
            self._logpath = os.path.join(logdir, datetime.now().strftime("bot_%Y%m%d_%H%M%S.log"))
        except Exception:
            self._logpath = None

    # ---- logging ---------------------------------------------------------
    def _log(self, msg):
        line = time.strftime("[%H:%M:%S] ") + str(msg)
        print(line, flush=True)
        if getattr(self, "_logpath", None):
            try:
                with open(self._logpath, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except Exception:
                pass

    # ---- the actual check ------------------------------------------------
    @staticmethod
    def _summarize(results):
        parts = []
        for cat, items in results.items():
            names = [it["name"] + (f" x{it['stock']}" if it.get("stock") else "") for it in items]
            if names:
                parts.append(f"{cat}: " + ", ".join(names))
        return " | ".join(parts) if parts else "nothing notable"

    def _do_check(self, reason):
        """Runs under _check_lock. Reads the shop and buys selected items."""
        self._log(f"=== CHECK ({reason}) ===")
        self.capture.reset()   # a long-lived mss handle can return frozen frames
        try:
            results, purchases = self.navigator.run_check()
        except NavigationError as e:
            self._last_error = str(e)
            self._log(f"!!! navigation: {e}")
            return False
        except Exception as e:
            self._last_error = str(e)
            self._log(f"!!! error: {e!r}")
            return False

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self._last_results = results
        self._last_time = ts
        self._last_error = None
        total = sum(len(v) for v in results.values())
        self._log(f"=== DONE: {total} items === {self._summarize(results)}")
        self._checks += 1
        self._buys += len(purchases)
        botstatus.write("watching", f"{total} items read - watching for restock...",
                        checks=self._checks, buys=self._buys)
        for p in purchases:
            tag = "would buy" if p.get("dry") else "BOUGHT"
            self._log(f"{tag}: {p['name']} x{p['qty']} ({p['category']})")
        return True

    def _housekeeping(self):
        """Purge debug frames when debug is off; cap the event/timed screenshot dirs."""
        dbg = self.cfg.get("debug", {})
        if not dbg.get("save_screenshots"):
            _prune_dir(os.path.join(self.root, dbg.get("dir", "debug")), 0)
        ev = self.cfg.get("events", {})
        _prune_dir(os.path.join(self.root, ev.get("dir", "events")), int(ev.get("keep", 50)))
        ts = self.cfg.get("timed_screenshots", {})
        _prune_dir(os.path.join(self.root, ts.get("dir", "timed")), int(ts.get("keep", 50)))
        _prune_dir(os.path.join(self.root, "logs"), 40)

    def _save_event_screenshot(self):
        ev = self.cfg.get("events", {})
        if not ev.get("enabled", True):
            return
        try:
            full = self.banner_capture.grab(self.window.client_rect())
            d = os.path.join(self.root, ev.get("dir", "events"))
            os.makedirs(d, exist_ok=True)
            fn = os.path.join(d, datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
            cv2.imwrite(fn, full)
            _prune_dir(d, int(ev.get("keep", 50)))
            self._log(f"screenshot saved: {fn}")
        except Exception as e:
            self._log(f"screenshot failed: {e!r}")

    def _start_timed_screenshots(self):
        ts = self.cfg.get("timed_screenshots", {})
        if not ts.get("enabled"):
            return
        threading.Thread(target=self._timed_loop, args=(ts,), daemon=True).start()

    def _timed_loop(self, ts):
        cap = ScreenCapture()
        d = os.path.join(self.root, ts.get("dir", "timed"))
        os.makedirs(d, exist_ok=True)
        period = float(ts.get("period_sec", 270))
        extra = float(ts.get("extra_offset_sec", 30))
        offsets = [0.0] if extra <= 0 else [0.0, extra]
        t0 = time.monotonic()
        n = 1
        while not self._stop.is_set():
            for off in offsets:
                wait = t0 + period * n + off - time.monotonic()
                if wait > 0 and self._stop.wait(wait):
                    return
                try:
                    full = cap.grab(self.window.client_rect())
                    fn = os.path.join(d, datetime.now().strftime("%Y%m%d_%H%M%S") + ".png")
                    cv2.imwrite(fn, full)
                except Exception as e:
                    self._log(f"timed-shot failed: {e!r}")
            n += 1

    # ---- run -------------------------------------------------------------
    def run(self):
        self._housekeeping()
        self._log("Starting. Warming up OCR (first run downloads the model)...")
        try:
            self.vision.warmup()
            self._log("OCR ready.")
        except Exception as e:
            self._log(f"OCR warmup failed: {e!r} (check rapidocr/onnxruntime install)")

        botstatus.write("watching", "Watching for restock...", checks=0, buys=0)

        interval = float(self.cfg["timings"].get("watch_interval_sec", 0.5))
        cooldown = float(self.cfg["timings"].get("cooldown_after_check_sec", 25))
        confirm_interval = float(self.cfg["timings"].get("banner_confirm_interval_sec", 1.5))
        last_fire = 0.0
        last_confirm = 0.0
        last_skip_log = 0.0
        last_reset = 0.0
        capture_reset = float(self.cfg["timings"].get("capture_reset_sec", 10))
        warned_no_window = False

        self._start_timed_screenshots()
        self._log("Watching the shop...  (Ctrl+C to quit)")
        try:
            while not self._stop.is_set():
                try:
                    region = self.cfg["regions"].get("refill_banner")
                    if not region:
                        self._log("Banner region not calibrated - run tools/calibrate.py")
                        time.sleep(5)
                        continue
                    box = self.window.region_px(region)
                    warned_no_window = False
                except RobloxWindowError:
                    if not warned_no_window:
                        self._log("Roblox window not found, waiting...")
                        warned_no_window = True
                    time.sleep(2)
                    continue

                # A long-lived mss handle can silently start returning frozen frames,
                # so recreate it every capture_reset seconds.
                mono = time.monotonic()
                if mono - last_reset > capture_reset:
                    self.banner_capture.reset()
                    last_reset = mono

                img = self.banner_capture.grab(box)
                present = self.vision.banner_present(img)
                now = time.monotonic()

                if (present and (now - last_fire) > cooldown
                        and (now - last_confirm) > confirm_interval):
                    # Green gate passed - OCR-confirm before firing, so persistent
                    # green (grass, event banners) can't false-trigger.
                    if self._check_lock.acquire(blocking=False):
                        last_confirm = time.monotonic()
                        try:
                            if self.vision.banner_confirm_ocr(img):
                                self._log("Detected: 'Shop has been restocked!'")
                                botstatus.write("restock", "Shop restocked - opening...")
                                self._save_event_screenshot()
                                last_fire = time.monotonic()
                                self._do_check("shop restocked")
                        finally:
                            self._check_lock.release()
                    elif now - last_skip_log > 15:
                        self._log("Banner visible but a check is already running - skipping.")
                        last_skip_log = now

                time.sleep(interval)
        except KeyboardInterrupt:
            self._log("Stopped (Ctrl+C)")
        finally:
            self._stop.set()
            botstatus.write("stopped", "Stopped")


if __name__ == "__main__":
    Watcher().run()
