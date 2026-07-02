"""Shop-reading flow: open the shop, reach the vendor, press E, read all four tabs.

run_check() returns {"factory": [item, ...], "houses": [...], "military": [...], "special": [...]}
and raises NavigationError if it cannot reach the shop.
"""
from __future__ import annotations

import os
import time

import cv2
import numpy as np

from src.parser import group_items, dedupe, normalize_name, match_whitelist
from src import botstatus

CATEGORIES = ["factory", "houses", "military", "special"]
CAT_TAB_BUTTON = {
    "factory": "tab_factory",
    "houses": "tab_houses",
    "military": "tab_military",
    "special": "tab_special",
}


class NavigationError(RuntimeError):
    pass


class Navigator:
    def __init__(self, cfg, window, capture, vision, inp, root, log=print):
        self.cfg = cfg
        self.window = window
        self.capture = capture
        self.vision = vision
        self.inp = inp
        self.root = root
        self.log = log
        self._dbg = 0

    # ---- helpers ---------------------------------------------------------
    def _btn_xy(self, name):
        frac = self.cfg["buttons"].get(name)
        if not frac:
            raise NavigationError(f"Button '{name}' is not calibrated (run calibrate.py)")
        return self.window.to_screen(frac[0], frac[1])

    def _region(self, name):
        frac = self.cfg["regions"].get(name)
        if not frac:
            return self.window.client_rect()
        return self.window.region_px(frac)

    def _click_btn(self, name):
        x, y = self._btn_xy(name)
        if not self.window.is_foreground():   # focus can be lost mid-run
            self.window.focus()
            time.sleep(0.3)
        self.inp.click(x, y)

    def _grab(self, region_name):
        return self.capture.grab(self._region(region_name))

    def _save_debug(self, img, tag):
        if not self.cfg.get("debug", {}).get("save_screenshots"):
            return
        d = os.path.join(self.root, self.cfg["debug"].get("dir", "debug"))
        os.makedirs(d, exist_ok=True)
        self._dbg += 1
        cv2.imwrite(os.path.join(d, f"{self._dbg:03d}_{tag}.png"), img)

    # ---- main flow -------------------------------------------------------
    def _ensure_foreground(self, timeout=3.0):
        """Bring Roblox to the foreground and confirm it got there; an inactive
        window consumes the first click just to activate itself."""
        end_at = time.monotonic() + timeout
        self.window.focus()
        while time.monotonic() < end_at:
            if self.window.is_foreground():
                return True
            self.window.focus()
            time.sleep(0.3)
        return self.window.is_foreground()

    def run_check(self):
        t = self.cfg["timings"]
        if not self._ensure_foreground():
            raise NavigationError(
                "Could not bring the Roblox window to the foreground. Click the game window and retry "
                "(or run the bot as administrator if Roblox runs as admin).")
        time.sleep(1.0)  # give the window a moment; the first click is eaten otherwise

        self.log("→ opening the shop (Buy)")
        self._click_btn("buy")

        # "Buy" teleports you to the vendor — press E to open the shop
        nav = self.cfg.get("navigation", {})
        time.sleep(float(nav.get("e_delay_after_buy_sec", 1.5)))
        hold = t.get("e_press_hold_sec", 0.9)
        post = max(0.6, t.get("after_tab_sec", 1.0))
        opened = False
        for i in range(int(nav.get("e_retries", 3))):
            self.log(f"→ pressing E (attempt {i + 1})")
            self.inp.hold_key("e", hold)
            time.sleep(post)
            if self.shop_open():
                opened = True
                break
        if not opened:
            raise NavigationError(
                'The shop did not open after E. Check that "Buy" places you next to the vendor.')

        cats = self.cfg.get("navigation", {}).get("categories") or CATEGORIES
        results = {}
        purchases = []
        for cat in cats:
            self.log(f"→ reading category: {cat}")
            botstatus.write("reading", f"Reading {cat.capitalize()}…")
            time.sleep(0.4)                 # let any buffered scroll flush first
            self._click_btn(CAT_TAB_BUTTON[cat])
            time.sleep(t["after_tab_sec"])  # tab click resets the list to the top
            items, buys = self.read_and_buy(cat)
            results[cat] = items
            purchases.extend(buys)
            self.log(f"   {cat}: {len(items)} items"
                     + (f", bought {len(buys)}" if buys else ""))

        self.log("→ closing the shop")
        self._close_shop()
        return results, purchases

    # ---- shop open / close -----------------------------------------------
    def shop_open(self):
        img = self._grab("shop_window")
        text = self.vision.ocr_text(img, upscale=2.0).lower()
        # English shop chrome: tab names + "Restock"/"Stock"/"Common".
        keys = ["factory", "military", "special", "houses",
                "restock", "stock", "common"]
        hits = sum(1 for k in keys if k in text)
        return hits >= 2

    def _close_shop(self):
        closed = False
        for attempt in range(3):
            self._click_btn("close_x")
            time.sleep(0.7)
            if not self.shop_open():
                closed = True
                break
            if attempt < 2:
                self.log("   the shop did not close, trying again")
        if not closed:
            self.log("   !! could not close via the X button — check the close_x coordinate")
        # optional post-check action to return to the map where the banner shows
        nav = self.cfg.get("navigation", {})
        action = nav.get("post_check_action")
        if action:
            self._do_action(action)
            time.sleep(nav.get("return_settle_sec", 1.5))

    def _do_action(self, action):
        kind = action.get("type")
        val = action.get("value")
        if kind == "key":
            self.inp.tap(val)
        elif kind == "button":
            try:
                self._click_btn(val)
            except NavigationError:
                pass

    # ---- shop scrolling via the mouse wheel --------------------------------
    def _shop_focus(self):
        """Click a safe spot inside the item list (icon column, away from any buy button)
        so the shop's ScrollingFrame becomes the wheel target — without this first click
        the wheel scrolls the game camera, not the list."""
        box = self._region("item_list")
        fx = box[0] + int(box[2] * float(self.cfg.get("navigation", {}).get("focus_click_fx", 0.12)))
        fy = box[1] + int(box[3] * float(self.cfg.get("navigation", {}).get("focus_click_fy", 0.32)))
        self.inp.click(fx, fy)
        time.sleep(0.15)

    def _wheel_step(self, notches):
        """Hover the list centre and spin the wheel `notches` (negative = down) as
        individual 1-notch ticks so Roblox smooth-scrolls between them."""
        box = self._region("item_list")
        self.inp.move(box[0] + box[2] // 2, box[1] + box[3] // 2)
        time.sleep(0.03)
        n = int(notches)
        step = 1 if n >= 0 else -1
        for _ in range(abs(n) or 1):
            self.inp.scroll(step)
            time.sleep(0.02)

    # ---- read + buy in one scroll pass -----------------------------------
    def read_and_buy(self, cat):
        """Single top-to-bottom scroll per category: read every card for the report and
        buy any selected item as soon as its green button is in view.
        Returns (deduped_items, purchases)."""
        nav = self.cfg.get("navigation", {})
        box = self._region("item_list")
        read_pause = float(nav.get("scroll_read_pause", 0.14))
        notches = int(nav.get("wheel_notches_read", 2))
        max_steps = int(nav.get("wheel_max_steps_merged", nav.get("wheel_max_steps", 120)))
        still_diff = float(nav.get("wheel_still_diff", 9.0))
        after_found = int(nav.get("scroll_after_found", 2))

        # early-stop targets for the report; gated on all_bought below so we don't
        # stop above an item that still needs buying
        targets = (self.cfg.get("report", {}).get("items") or {}).get(cat)
        target_keys = {normalize_name(x) for x in targets} if targets else None

        # buying is gated on the green button, not the OCR'd stock line; _do_buy
        # stops once the button disappears
        buy_cfg = self.cfg.get("buy", {})
        buy_list = (buy_cfg.get("items") or {}).get(cat) if buy_cfg.get("enabled") else None
        if buy_list:
            max_qty = int(buy_cfg.get("max_per_item", 0))
            per_item = max_qty if max_qty > 0 else int(buy_cfg.get("buy_until_soldout_max", 20))
            to_buy = {entry: per_item for entry in buy_list}
            names = list(to_buy.keys())
            self.log("   to buy (selected): " + ", ".join(names))
        else:
            to_buy, names = {}, []
        hsv_low = buy_cfg.get("button_hsv_low", [40, 120, 180])
        hsv_high = buy_cfg.get("button_hsv_high", [75, 255, 255])
        right_frac = float(buy_cfg.get("right_fraction", 0.58))
        dry = bool(buy_cfg.get("dry_run", True))
        click_delay = float(buy_cfg.get("click_delay_sec", 0.5))

        collected, purchases, done, ocr_times = [], [], set(), []

        self._shop_focus()
        time.sleep(read_pause)
        # skip the low-rarity items at the top of each list (the catalog only offers
        # Epic+). `start_skip_notches` is a scalar or per-category dict (0 = off),
        # calibrated at `start_skip_ref_height`; Roblox scrolls fixed pixels per wheel
        # notch while the cards scale with the viewport, so scale the notch count by
        # the live client height.
        sk = nav.get("start_skip_notches", 0)
        skip = int(sk.get(cat, 0)) if isinstance(sk, dict) else int(sk)
        if skip > 0:
            ref_h = float(nav.get("start_skip_ref_height", 1009))
            try:
                ch = self.window.client_rect()[3]
                if ch > 0 and ref_h > 0:
                    skip = int(round(skip * ch / ref_h))
            except Exception:
                pass
        if skip > 0:
            self._wheel_step(-skip)
            time.sleep(read_pause)
        last_sig = None
        still = 0
        found_done = False
        extra = 0
        for idx in range(max_steps + 1):
            frame = self.capture.grab(box)
            self._save_debug(frame, f"{cat}_{idx}")
            t0 = time.perf_counter()
            lines = self.vision.ocr_lines(frame)
            ocr_times.append(time.perf_counter() - t0)
            items = group_items(lines, frame.shape[0])
            collected.extend(items)

            # --- buy at most one item per frame; re-capture handles the list reflow ---
            bought = False
            if names and len(done) < len(names):
                for it in sorted(items, key=lambda i: i.get("y") or 0.0):
                    canon = match_whitelist(it["name"], names)
                    if not canon or canon in done:
                        continue
                    y_name = it.get("y")
                    if y_name is None:
                        continue
                    if self.vision.find_buy_button(frame, y_name, hsv_low, hsv_high,
                                                   right_frac) is None:
                        continue          # button not in view yet — a later step reveals it
                    qty = to_buy[canon]
                    n, shot = self._do_buy(box, y_name, qty, hsv_low, hsv_high,
                                           right_frac, click_delay, dry)
                    done.add(canon)
                    purchases.append({"category": cat, "name": canon,
                                      "qty": (qty if dry else n), "dry": dry, "image": shot})
                    self.log(f"   {'[test] would buy' if dry else 'BOUGHT'}: {canon} "
                             f"×{qty if dry else n}")
                    botstatus.write("buying", f"Bought {canon} ×{qty if dry else n}")
                    bought = True
                    self._shop_focus()    # the buy click can defocus the list -> re-focus
                    break                 # one buy per frame; the frame is stale now — re-read
            if bought:
                last_sig = None           # the reflow changed the view -> reset bottom detect
                still = 0
                continue                  # re-read same spot (a neighbour may be buyable too)

            # --- bottom / early-stop detection ---
            if not found_done and target_keys and self._found_all(collected, targets, target_keys):
                found_done = True
            all_bought = (not names) or (len(done) >= len(names))
            sig = self._frame_sig(frame)
            if found_done and all_bought:
                extra += 1
                if extra > after_found:
                    break                 # everything wanted seen + a couple safety frames
            elif last_sig is not None and float(np.abs(sig - last_sig).mean()) < still_diff:
                # a static frame can be the real bottom or a wheel step that didn't land
                # (focus lost); re-focus and require two static frames in a row
                still += 1
                self._shop_focus()
                if still >= 2:
                    break                 # genuinely static after a re-focus retry -> bottom
            else:
                still = 0
            last_sig = sig
            self._wheel_step(-notches)

        if ocr_times:
            self.log(f"   OCR: {len(ocr_times)} frames, "
                     f"~{1000 * sum(ocr_times) / len(ocr_times):.0f} ms/frame")
        missed = [n for n in names if n not in done]
        if missed:
            self.log("   !! did not buy: " + ", ".join(missed))
        return dedupe(collected), purchases

    # ---- auto-buy --------------------------------------------------------
    @staticmethod
    def _png_bytes(frame):
        ok, buf = cv2.imencode(".png", frame)
        return buf.tobytes() if ok else None

    def _do_buy(self, box, y_name, qty, hsv_low, hsv_high, right_frac, click_delay, dry):
        if dry:
            return qty, self._png_bytes(self.capture.grab(box))
        done = 0
        for _ in range(qty + 2):
            if done >= qty:
                break
            frame = self.capture.grab(box)
            btn = self.vision.find_buy_button(frame, y_name, hsv_low, hsv_high, right_frac)
            if btn is None:
                break  # button gone -> sold out / nothing left to buy
            self.inp.click(box[0] + btn[0], box[1] + btn[1])
            done += 1
            time.sleep(click_delay)
        return done, self._png_bytes(self.capture.grab(box))

    @staticmethod
    def _frame_sig(img):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.resize(g, (48, 48)).astype(np.int32)

    @staticmethod
    def _sig_close(a, b):
        return float(np.abs(a - b).mean()) < 3.0

    @staticmethod
    def _found_all(collected, targets, target_keys):
        got = set()
        for it in collected:
            # require the status row too — a name alone can peek over the bottom edge
            # of the view before its stock line scrolls in
            if it.get("status") is None and it.get("stock") is None:
                continue
            m = match_whitelist(it["name"], targets)
            if m:
                got.add(normalize_name(m))
        return target_keys.issubset(got)
