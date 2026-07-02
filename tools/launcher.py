"""Shop Bot — launcher GUI (pywebview / WebView2).

Frameless window to pick items to auto-buy, toggle test mode, and run/stop the bot.
While the bot runs, the window shrinks to an always-on-top status overlay (global
F7 = stop). Everything is saved to config.json — `python run.py` works without it.

Run:  python tools/launcher.py   (or launcher.bat)
"""
import os
import sys
import json
import time
import ctypes
import threading
import subprocess

try:
    import webview
except ImportError:
    import tkinter as _tk
    from tkinter import messagebox as _mb
    _r = _tk.Tk(); _r.withdraw()
    _mb.showerror("Shop Bot", "pywebview is not installed.\n\nRun:  pip install pywebview")
    raise SystemExit(1)

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from src import appconfig
CONFIG = appconfig.CONFIG_PATH

APP_SIZE = (552, 800)
OVERLAY_SIZE = (300, 142)

# ---- Win32 window helpers (move / resize / always-on-top the frameless window) ----
_user32 = ctypes.windll.user32
_user32.FindWindowW.restype = ctypes.c_void_p
_user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
_user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int,
                                 ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
from ctypes import wintypes
_user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
_user32.GetWindowRect.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.RECT)]
_user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
_user32.GetAsyncKeyState.restype = ctypes.c_short
_HWND_TOPMOST, _HWND_NOTOPMOST, _SWP_SHOW = -1, -2, 0x0040


def _hwnd():
    return _user32.FindWindowW(None, "Shop Bot")


def _screen():
    return _user32.GetSystemMetrics(0), _user32.GetSystemMetrics(1)


def _place(topmost, x, y, w, h):
    h_ = _hwnd()
    if h_:
        after = ctypes.c_void_p(_HWND_TOPMOST if topmost else _HWND_NOTOPMOST)
        _user32.SetWindowPos(h_, after, int(x), int(y), int(w), int(h), _SWP_SHOW)


_INSTANCE_MUTEX = None


def _single_instance() -> bool:
    """True if this is the only instance. Uses a named mutex, which Windows
    releases automatically when the process dies — no stale lock files."""
    global _INSTANCE_MUTEX
    ERROR_ALREADY_EXISTS = 183
    try:
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.restype = ctypes.c_void_p
        h = k32.CreateMutexW(None, False, "RobloxShopBot_SingleInstance_v1")
        if not h:
            return True                       # can't create → fail open
        if k32.GetLastError() == ERROR_ALREADY_EXISTS:
            return False
        _INSTANCE_MUTEX = h                   # keep the handle for the process lifetime
        return True
    except Exception:
        return True

CATS = [
    ("factory", "Factory", "factory", "#ef4444"),
    ("houses", "Houses", "house", "#3b82f6"),
    ("military", "Military", "shield", "#22c55e"),
    ("special", "Special", "star", "#eab308"),
]

# Fallback item list if config.json has no "catalog" section.
CATALOG = {
    "factory": {"Gold Cave": "Epic", "Bank": "Epic", "Research Labs": "Legendary",
                "Diamond Cave": "Legendary", "Uranium Cave": "Mythic", "Nuclear Reactor": "Mythic",
                "Data Center": "Mythic", "Blackhole Generator": "Secret",
                "Antimatter Reactor": "Secret", "Area 51 Lab": "Secret",
                "Quantum Core Generator": "Divine"},
    "houses": {"Helix Tower": "Legendary", "The Manor": "Mythic", "Hotel": "Mythic",
               "Giant Skyscraper": "Secret", "Double Turbo Tower": "Secret", "Grand Hotel": "Divine"},
    "military": {"Missile Launcher": "Legendary", "Military Hospital": "Legendary",
                 "General's Base": "Mythic", "Air Base": "Mythic", "Artillery Depot": "Mythic",
                 "Rocket Bunker": "Secret", "Mech Station": "Secret", "Spider Base": "Secret",
                 "Air Fortress": "Divine"},
    "special": {},
}


def get_catalog(cfg=None):
    """Item list (name -> rarity per category) from config.json's "catalog"
    section, falling back to the bundled CATALOG."""
    try:
        c = (cfg or load_config()).get("catalog")
        if isinstance(c, dict) and c:
            return c
    except Exception:
        pass
    return CATALOG

# SVG icons (lucide-style) by key
ICONS = {
    "factory": '<path d="M2 20h20M4 20V8l5 4V8l5 4V4l6 4v12"/>',
    "house": '<path d="M3 11l9-8 9 8M5 10v10h14V10"/>',
    "shield": '<path d="M12 2l8 4v6c0 5-4 8-8 10-4-2-8-5-8-10V6z"/>',
    "star": '<path d="M12 2l2.9 6.3 6.9.6-5.2 4.6 1.6 6.8L12 17l-6.2 3.3 1.6-6.8L2.2 8.9l6.9-.6z"/>',
    "flask": '<path d="M9 3v7.6L4.6 19a2 2 0 0 0 1.7 3h11.4a2 2 0 0 0 1.7-3L15 10.6V3"/><path d="M8 3h8"/><path d="M7.5 16h9"/>',
}


def load_config():
    with open(CONFIG, encoding="utf-8") as f:
        return json.load(f)


def save_config(cfg):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


class Api:
    def __init__(self):
        self.proc = None
        self._lphase = "idle"      # idle | launching | running | error
        self._lmsg = ""
        self._lpct = 0             # 0..100 launch progress

    # ---- window controls ----
    def minimize(self):
        if webview.windows:
            webview.windows[0].minimize()
        return {"ok": True}

    def close_app(self):
        try:
            if self.proc and self.proc.poll() is None:
                self.proc.terminate()   # closing the launcher kills the running bot too
        except Exception:
            pass
        if webview.windows:
            webview.windows[0].destroy()
        return {"ok": True}

    def start_drag(self):
        # Frameless drag: one bridge call on mousedown, then a thread moves the window
        # via GetCursorPos/SetWindowPos while the button is held (WebView2's CSS
        # drag regions are unreliable).
        if getattr(self, "_dragging", False):
            return {"ok": True}
        self._dragging = True
        threading.Thread(target=self._drag_loop, daemon=True).start()
        return {"ok": True}

    def _drag_loop(self):
        try:
            h = _hwnd()
            if not h:
                return
            pt = wintypes.POINT()
            rect = wintypes.RECT()
            _user32.GetCursorPos(ctypes.byref(pt))
            _user32.GetWindowRect(h, ctypes.byref(rect))
            offx, offy = pt.x - rect.left, pt.y - rect.top
            SWP = 0x0001 | 0x0004 | 0x0010   # NOSIZE | NOZORDER | NOACTIVATE
            while _user32.GetAsyncKeyState(0x01) & 0x8000:   # VK_LBUTTON held
                _user32.GetCursorPos(ctypes.byref(pt))
                _user32.SetWindowPos(h, None, pt.x - offx, pt.y - offy, 0, 0, SWP)
                time.sleep(0.008)
        except Exception:
            pass
        finally:
            self._dragging = False

    # ---- overlay (small always-on-top status widget while the bot runs) ----
    def enter_overlay(self):
        sw, _sh = _screen()
        w, h = OVERLAY_SIZE
        _place(True, sw - w - 24, 26, w, h)        # top-right corner
        return {"ok": True}

    def exit_overlay(self):
        sw, sh = _screen()
        w, h = APP_SIZE
        _place(False, max(0, (sw - w) // 2), max(20, (sh - h) // 2), w, h)
        return {"ok": True}

    def bot_status(self):
        from src import botstatus
        return botstatus.read() or {}

    # ---- state ----
    def get_state(self):
        cfg = load_config()
        catalog_all = get_catalog(cfg)
        buy = cfg.get("buy", {}).get("items", {}) or {}
        nav = set(cfg.get("navigation", {}).get("categories") or [c for c, *_ in CATS])
        cats = []
        for key, title, icon, color in CATS:
            buyset = set(buy.get(key, []))
            catalog = catalog_all.get(key, {})
            names = list(catalog.keys()) + [n for n in buyset if n not in catalog]
            items = [{"name": n, "rarity": catalog.get(n, ""), "buy": n in buyset} for n in names]
            cats.append({"key": key, "title": title, "icon": icon, "color": color,
                         "read": key in nav, "items": items})
        return {
            "dry_run": bool(cfg.get("buy", {}).get("dry_run", True)),
            "cats": cats, "running": self._running(),
        }

    def _apply(self, state):
        cfg = load_config()
        cfg.setdefault("navigation", {})["categories"] = [c["key"] for c in state["cats"] if c.get("read")]
        cfg.setdefault("buy", {}).setdefault("items", {})
        cfg["buy"]["dry_run"] = bool(state.get("dry_run", True))
        catalog_all = get_catalog(cfg)
        buy_items = {}
        for c in state["cats"]:
            order = list(catalog_all.get(c["key"], {}).keys())
            picked = [it["name"] for it in c["items"] if it.get("buy")]
            buy_items[c["key"]] = [n for n in order if n in picked] + \
                                  [n for n in picked if n not in order]
        cfg["buy"]["items"] = buy_items
        save_config(cfg)

    def save(self, state):
        self._apply(state)
        return {"ok": True}

    def launch(self, state):
        # Returns immediately; the UI polls launch_status() while the bot spawns.
        self._apply(state)
        if self._running():
            return {"ok": False, "running": True, "msg": "Bot is already running"}
        try:
            from src import botstatus
            botstatus.clear()          # drop any stale status so the overlay starts clean
        except Exception:
            pass
        self._lphase = "launching"
        self._lmsg = "Starting engine…"
        self._lpct = 8
        threading.Thread(target=self._do_launch, daemon=True).start()
        return {"ok": True, "async": True}

    def _do_launch(self):
        try:
            exe = sys.executable
            cand = os.path.join(os.path.dirname(exe), "python.exe")
            py = cand if os.path.exists(cand) else exe
            flags = subprocess.CREATE_NEW_CONSOLE if os.name == "nt" else 0
            self.proc = subprocess.Popen([py, os.path.join(HERE, "run.py")], cwd=HERE,
                                         creationflags=flags)
            self._lpct = 60
            self._lphase = "running"
            self._lmsg = "Warming up OCR…"
        except Exception as e:
            self._lphase = "error"
            self._lmsg = f"Launch failed: {e.__class__.__name__}"

    def launch_status(self):
        return {"phase": self._lphase, "msg": self._lmsg, "pct": self._lpct, "running": self._running()}

    def stop(self):
        if self._running():
            self.proc.terminate()
        return {"ok": True, "running": False}

    def is_running(self):
        return {"running": self._running()}

    def _running(self):
        return bool(self.proc and self.proc.poll() is None)


UI_HTML = r"""<!DOCTYPE html><html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shop Bot</title>
<style>
  :root{
    --bg:oklch(0.16 0.012 260); --fg:oklch(0.96 0.005 260);
    --card:oklch(0.19 0.014 260); --elevated:oklch(0.23 0.016 260);
    --secondary:oklch(0.26 0.016 260); --muted:oklch(0.66 0.012 260);
    --primary:oklch(0.74 0.18 150); --primary-fg:oklch(0.18 0.02 150);
    --destructive:oklch(0.58 0.2 18); --line:oklch(1 0 0 / 9%); --line2:oklch(1 0 0 / 14%);
  }
  *{box-sizing:border-box} html,body{height:100%;margin:0}
  :root{color-scheme:dark}
  body{display:flex;flex-direction:column;overflow:hidden;color:var(--fg);user-select:none;
    font-family:"Segoe UI Variable Display","Segoe UI",system-ui,sans-serif;-webkit-font-smoothing:antialiased;
    background:
      radial-gradient(600px circle at 20% 8%, color-mix(in oklch, var(--primary) 12%, transparent), transparent 50%),
      radial-gradient(520px circle at 88% 96%, oklch(0.55 0.12 260 / .14), transparent 50%),
      var(--bg);}
  ::-webkit-scrollbar{width:8px}::-webkit-scrollbar-thumb{background:oklch(0.4 0.02 260);border-radius:8px}
  .hidden{display:none!important}
  /* launch loading panel */
  #loading{position:fixed;inset:46px 0 0 0;z-index:60;display:flex;align-items:center;justify-content:center;
    background:var(--bg);animation:fade .2s ease}
  @keyframes fade{from{opacity:0}to{opacity:1}}
  .ld{width:84%;max-width:380px;display:flex;flex-direction:column;align-items:center;gap:15px;text-align:center}
  .ld-spin{width:36px;height:36px;border:3px solid var(--secondary);border-top-color:var(--primary);
    border-radius:50%;animation:sp .8s linear infinite}
  @keyframes sp{to{transform:rotate(360deg)}}
  .ld-title{font-size:16px;font-weight:800;letter-spacing:.2px}
  .ld-bar{width:100%;height:9px;border-radius:99px;background:var(--secondary);overflow:hidden;
    box-shadow:inset 0 0 0 1px var(--line)}
  .ld-bar i{display:block;height:100%;width:0;border-radius:99px;transition:width .35s cubic-bezier(.4,0,.2,1);
    background:linear-gradient(90deg,var(--primary),oklch(0.82 0.16 165));
    box-shadow:0 0 12px color-mix(in oklch,var(--primary) 55%,transparent)}
  .ld-row{width:100%;display:flex;justify-content:space-between;align-items:center;font-size:12.5px;color:var(--muted)}
  #ldPct{font-weight:800;font-size:14px;color:var(--fg);font-variant-numeric:tabular-nums}
  .ld-hint{font-size:11px;color:var(--muted);opacity:.8;margin-top:2px;line-height:1.4}
  .ld.err .ld-spin{animation:none;border-color:#46232f;border-top-color:oklch(0.65 0.18 22)}
  .ld.err .ld-title{color:oklch(0.72 0.17 22)}
  svg{width:1em;height:1em;stroke:currentColor;fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}

  /* title bar */
  .titlebar{flex:none;display:flex;align-items:center;height:46px;padding:0 8px 0 14px;border-bottom:1px solid var(--line)}
  .drag{flex:1;display:flex;align-items:center;gap:9px;height:100%;font-size:13px;font-weight:600}
  .logo{width:22px;height:22px;border-radius:7px;display:grid;place-items:center;font-size:11px;font-weight:900;
    background:color-mix(in oklch, var(--primary) 22%, transparent);color:var(--primary)}
  .tdim{color:var(--muted);font-weight:500}
  .tright{display:flex;align-items:center;gap:10px}
  .stat{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted)}
  .dot{width:7px;height:7px;border-radius:50%;background:var(--muted)}
  .dot.on{background:var(--primary);box-shadow:0 0 0 3px color-mix(in oklch,var(--primary) 20%,transparent);animation:pulse 1.8s infinite}
  .wbtns{display:flex;gap:2px}
  .wbtn{width:32px;height:28px;border:0;border-radius:7px;background:transparent;color:var(--muted);cursor:pointer;
    font-size:14px;display:grid;place-items:center;transition:.15s}
  .wbtn:hover{background:var(--elevated);color:var(--fg)} .wbtn.close:hover{background:var(--destructive);color:#fff}

  /* ===== APP ===== */
  #app{flex:1;display:flex;flex-direction:column;overflow:hidden}
  .content{flex:1;overflow-y:auto;padding:16px 16px 8px}
  .lbl{font-size:10px;letter-spacing:.7px;text-transform:uppercase;color:var(--muted);margin:0 0 9px 2px;font-weight:600}
  .mode{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:14px;border-radius:13px;
    border:1px solid var(--line);background:var(--card);cursor:pointer;margin-bottom:16px}
  .mode-l{display:flex;align-items:center;gap:11px}
  .mode-ic{width:38px;height:38px;border-radius:10px;display:grid;place-items:center;font-size:18px;
    background:color-mix(in oklch,var(--primary) 15%,transparent);color:var(--primary)}
  .mode.real .mode-ic{background:color-mix(in oklch,var(--destructive) 16%,transparent);color:var(--destructive)}
  .mode-t{font-weight:700;font-size:13.5px} .mode-s{font-size:11.5px;color:var(--muted);margin-top:1px}
  .sw{width:44px;height:24px;border-radius:999px;background:var(--secondary);position:relative;flex:none;transition:.3s}
  .sw.on{background:var(--primary)} .sw .k{position:absolute;top:2px;left:2px;width:20px;height:20px;border-radius:50%;
    background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.4);transition:transform .3s cubic-bezier(.4,1.3,.5,1)}
  .sw.on .k{transform:translateX(20px)}
  .cat{border:1px solid var(--line);border-radius:13px;overflow:hidden;background:var(--card);margin-bottom:13px}
  .cat .acc{height:2px;background:var(--accent)}
  .cat-in{padding:14px}
  .cat-h{display:flex;align-items:center;justify-content:space-between}
  .cat-l{display:flex;align-items:center;gap:10px}
  .cat-ic{width:36px;height:36px;border-radius:9px;display:grid;place-items:center;font-size:18px;
    background:color-mix(in oklch,var(--accent) 16%,transparent);color:var(--accent)}
  .cat-name{font-weight:700;font-size:15px} .cat-sub{font-size:11.5px;color:var(--muted)} .cat-sub b{color:var(--fg)}
  .read{display:flex;align-items:center;gap:8px;font-size:11.5px;color:var(--muted)}
  .sw.sm{width:36px;height:20px} .sw.sm .k{width:16px;height:16px} .sw.sm.on .k{transform:translateX(16px)}
  .chips{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:14px}
  .chip{display:flex;align-items:center;justify-content:space-between;gap:8px;min-width:0;cursor:pointer;
    border:1px solid var(--line);background:var(--elevated);border-radius:10px;padding:10px 12px;
    transition:transform .14s,border-color .2s,background .2s}
  .chip:hover{transform:translateY(-1px)} .chip:active{transform:scale(.97)}
  .chip.on{border-color:color-mix(in oklch,var(--primary) 60%,transparent);
    background:color-mix(in oklch,var(--primary) 10%,transparent)}
  .chip .nm{min-width:0;flex:1;font-size:14px;font-weight:500;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .empty{color:var(--muted);font-style:italic;font-size:13px;margin-top:12px}
  .badge{display:inline-flex;align-items:center;font-size:10px;font-weight:700;letter-spacing:.025em;
    text-transform:uppercase;line-height:1;padding:3px 6px;border-radius:6px;
    box-shadow:0 1px 2px rgba(0,0,0,.18);flex:none;white-space:nowrap}

  .foot{flex:none;border-top:1px solid var(--line);background:color-mix(in oklch,var(--card) 60%,transparent);padding:14px 16px}
  .sumline{text-align:center;font-size:12px;color:var(--muted)} .sumline b{color:var(--fg)} .sumline .t{color:var(--primary);font-weight:700}
  .autosave{text-align:center;font-size:10.5px;color:oklch(0.66 0.012 260 / .7);margin:3px 0 12px;transition:.25s}
  .autosave.ok{color:var(--primary)}
  .acts{display:grid;grid-template-columns:1fr 1fr;gap:9px}
  .rbtn{border:0;border-radius:11px;padding:12px;font:700 14px/1 inherit;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;transition:.15s}
  .rbtn.run{background:var(--primary);color:var(--primary-fg)} .rbtn.run:hover{filter:brightness(1.06)}
  .rbtn.run:disabled{opacity:.5;cursor:default}
  .rbtn.stop{border:1px solid color-mix(in oklch,var(--destructive) 40%,transparent);
    background:color-mix(in oklch,var(--destructive) 15%,transparent);color:var(--destructive)}
  .rbtn.stop:disabled{opacity:.4;cursor:default}
  .scanbar{display:none;margin-top:11px;align-items:center;gap:9px;padding:9px 12px;border-radius:10px;
    border:1px solid color-mix(in oklch,var(--primary) 30%,transparent);background:color-mix(in oklch,var(--primary) 10%,transparent);
    font-size:11px;color:var(--fg)}
  #app.running .scanbar{display:flex}
  .ping{position:relative;width:8px;height:8px}.ping i{position:absolute;inset:0;border-radius:50%;background:var(--primary)}
  .ping b{position:absolute;inset:0;border-radius:50%;background:color-mix(in oklch,var(--primary) 70%,transparent);animation:ping 1.4s infinite}

  /* overlay (small status widget) */
  #overlay{position:fixed;inset:0;display:flex}
  #overlay .ov{flex:1;display:flex;flex-direction:column;justify-content:center;gap:9px;padding:15px 17px;
    background:radial-gradient(420px circle at 92% -30%, color-mix(in oklch,var(--primary) 12%,transparent), transparent 60%), var(--card);
    border:1px solid var(--line2);border-radius:14px}
  .ov-h{display:flex;align-items:center;gap:10px}
  .ov-dot{position:relative;width:10px;height:10px;flex:none}
  .ov-dot b{position:absolute;inset:0;border-radius:50%;background:color-mix(in oklch,var(--primary) 70%,transparent);animation:ping 1.4s infinite}
  .ov-dot i{position:absolute;inset:0;border-radius:50%;background:var(--primary)}
  .ov-state{font-weight:800;font-size:14.5px;letter-spacing:.2px}
  .ov-x{margin-left:auto;border:1px solid var(--line2);background:var(--elevated);color:var(--muted);
    font:700 10px/1 inherit;padding:6px 9px;border-radius:8px;cursor:pointer;-webkit-app-region:no-drag}
  .ov-x:hover{color:var(--fg);border-color:color-mix(in oklch,var(--primary) 60%,transparent)}
  .ov-act{font-size:12.5px;color:var(--fg);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .ov-foot{font-size:10.5px;color:var(--muted)}

  @keyframes pulse{0%{box-shadow:0 0 0 0 color-mix(in oklch,var(--primary) 35%,transparent)}70%{box-shadow:0 0 0 6px transparent}100%{box-shadow:0 0 0 0 transparent}}
  @keyframes ping{75%,100%{transform:scale(2.2);opacity:0}}
  @keyframes fadeup{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:none}}
  .anim{animation:fadeup .45s both}
</style></head>
<body>
  <div class="titlebar" id="titlebar">
    <div class="drag pywebview-drag-region">
      <span class="logo"><span style="font-weight:900">S</span></span>
      <span>Shop Bot <span class="tdim">· Mini War</span></span>
    </div>
    <div class="tright">
      <span class="stat" id="statWrap"><span class="dot" id="dot"></span><span id="statusText">Stopped</span></span>
      <div class="wbtns">
        <button class="wbtn" id="minBtn" title="Minimize">&#8211;</button>
        <button class="wbtn close" id="closeBtn" title="Close">&#10005;</button>
      </div>
    </div>
  </div>

  <!-- APP -->
  <div id="app">
    <div class="content">
      <p class="lbl" style="margin-top:4px">Mode</p>
      <div class="mode" id="modeCard">
        <div class="mode-l">
          <span class="mode-ic"><svg viewBox="0 0 24 24" id="modeIcon"></svg></span>
          <div><div class="mode-t" id="modeTitle"></div><div class="mode-s" id="modeSub"></div></div>
        </div>
        <div class="sw" id="modeSw"><div class="k"></div></div>
      </div>
      <p class="lbl">Auto-buy</p>
      <div id="cats"></div>
    </div>
    <div class="foot">
      <div class="sumline" id="summary"></div>
      <div class="autosave" id="autosave">Changes apply automatically</div>
      <div class="acts">
        <button class="rbtn run" id="runBtn"><svg viewBox="0 0 24 24" style="fill:currentColor;stroke:none"><path d="M6 4l14 8-14 8z"/></svg> Run</button>
        <button class="rbtn stop" id="stopBtn" disabled><svg viewBox="0 0 24 24" style="fill:currentColor;stroke:none"><rect x="6" y="6" width="12" height="12" rx="2"/></svg> Stop</button>
      </div>
      <div class="scanbar"><span class="ping"><b></b><i></i></span><span id="scanText">Bot is scanning shop</span></div>
    </div>
  </div>

  <!-- LOADING -->
  <div id="loading" class="hidden">
    <div class="ld">
      <div class="ld-spin"></div>
      <div class="ld-title" id="ldTitle">Launching bot…</div>
      <div class="ld-bar"><i id="ldFill"></i></div>
      <div class="ld-row"><span id="ldMsg">Starting…</span><span id="ldPct">0%</span></div>
      <div class="ld-hint" id="ldHint">First run downloads the OCR model — this can take a minute.</div>
    </div>
  </div>

  <div id="overlay" class="hidden pywebview-drag-region">
    <div class="ov">
      <div class="ov-h">
        <span class="ov-dot"><b></b><i></i></span>
        <span class="ov-state" id="ovState">Working</span>
        <button class="ov-x" id="ovStop">F7 · stop</button>
      </div>
      <div class="ov-act" id="ovAct">Starting…</div>
      <div class="ov-foot" id="ovMeta"></div>
    </div>
  </div>

<script>
const ICONS = __ICONS__;
let S = null;
try{ S = __BOOT_STATE__; }catch(e){}
const $ = id => document.getElementById(id);
function apiReady(){return new Promise(res=>{(function w(){var a=window.pywebview&&window.pywebview.api;
  if(a&&a.save) return res(a); setTimeout(w,40);})();});}
function svg(el,name){ if(el) el.innerHTML = ICONS[name]||""; }

svg($("modeIcon"),"flask");

/* ---------- APP ---------- */
let _saveT=null;
function apply(){ clearTimeout(_saveT); _saveT=setTimeout(async()=>{ try{ const a=await apiReady(); await a.save(S); flashSaved(); }catch(e){} },120); }
function flashSaved(){ const a=$("autosave"); a.textContent="✓ Saved"; a.classList.add("ok");
  clearTimeout(a._t); a._t=setTimeout(()=>{a.textContent="Changes apply automatically";a.classList.remove("ok");},1000); }
const RBG={epic:["#a855f7","#7c3aed","#fff"],legendary:["#f59e0b","#b45309","#fff"],
  mythic:["#ec4899","#be185d","#fff"],secret:["#f97316","#eab308","#1a1205"],divine:["#facc15","#f59e0b","#1a1205"]};
function badge(r){ const s=RBG[(r||"").toLowerCase()]; if(!s) return "";
  return `<span class="badge" style="background:linear-gradient(135deg,${s[0]},${s[1]});color:${s[2]}">${r}</span>`; }

function renderMode(){
  const test=!!S.dry_run;
  $("modeCard").classList.toggle("real",!test);
  $("modeSw").classList.toggle("on",test);
  $("modeTitle").textContent = test ? "Test mode" : "Live mode";
  $("modeSub").textContent = test ? "Only logs what it would buy — no real purchases"
                                  : "Buys the selected items for real";
}

function renderApp(){
  const host=$("cats"); host.innerHTML="";
  S.cats.forEach((c,ci)=>{
    const card=document.createElement("div"); card.className="cat anim";
    card.style.setProperty("--accent",c.color); card.style.animationDelay=(.04+ci*.05)+"s";
    const buyN=c.items.filter(i=>i.buy).length;
    card.innerHTML=`<div class="acc"></div><div class="cat-in">
      <div class="cat-h"><div class="cat-l"><span class="cat-ic"><svg viewBox="0 0 24 24">${ICONS[c.icon]||""}</svg></span>
        <div><div class="cat-name">${c.title}</div><div class="cat-sub"><b>${buyN}</b> to buy</div></div></div>
        <div class="read"><span>Read</span><div class="sw sm ${c.read?'on':''}"><div class="k"></div></div></div></div>
      <div class="chips"></div></div>`;
    const rd=card.querySelector(".read");
    rd.onclick=()=>{ c.read=!c.read; rd.querySelector(".sw").classList.toggle("on",c.read); summary(); apply(); };
    const chips=card.querySelector(".chips");
    if(!c.items.length){ chips.innerHTML='<div class="empty">— nothing here yet —</div>'; }
    c.items.forEach(it=>{
      const chip=document.createElement("button"); chip.className="chip"+(it.buy?" on":"");
      chip.innerHTML=`<span class="nm">${it.name}</span>${badge(it.rarity)}`;
      chip.onclick=()=>{ it.buy=!it.buy; chip.classList.toggle("on",it.buy);
        card.querySelector(".cat-sub b").textContent=c.items.filter(i=>i.buy).length; summary(); apply(); };
      chips.appendChild(chip);
    });
    host.appendChild(card);
  });
  renderMode();
  summary();
}
function summary(){
  const reads=S.cats.filter(c=>c.read).length, buys=S.cats.reduce((a,c)=>a+c.items.filter(i=>i.buy).length,0);
  $("summary").innerHTML=`${reads} tabs read · <b>${buys} to buy</b>`+(S.dry_run?' · <span class="t">test</span>':'');
  $("scanText").textContent=`Bot is scanning shop · ${S.dry_run?"test mode (no real buys)":`auto-buying ${buys} item${buys===1?"":"s"}`}`;
}
function setStatus(r){ $("dot").classList.toggle("on",r); $("statusText").textContent=r?"Running":"Stopped";
  $("app").classList.toggle("running",r); $("runBtn").disabled=r; $("stopBtn").disabled=!r; }

/* ---------- OVERLAY ---------- */
let _ovPoll=null;
const OVLBL={watching:"Watching",restock:"Restock!",reading:"Reading",buying:"Buying",stopped:"Stopped",idle:"Idle"};
function enterOverlay(){
  $("titlebar").classList.add("hidden"); $("app").classList.add("hidden");
  $("overlay").classList.remove("hidden");
  apiReady().then(a=>a.enter_overlay());
  ovTick(); _ovPoll=setInterval(ovTick,700);
}
async function ovTick(){
  const a=await apiReady(); let running=true;
  try{ running=(await a.is_running()).running; }catch(e){}
  if(!running){ exitOverlay(); return; }
  let st={}; try{ st=await a.bot_status(); }catch(e){}
  $("ovState").textContent=OVLBL[st.state]||"Starting";
  $("ovAct").textContent=st.action||"Starting the bot…";
  $("ovMeta").textContent=`${st.checks||0} checks · ${st.buys||0} buys`;
}
async function exitOverlay(){
  if(_ovPoll){ clearInterval(_ovPoll); _ovPoll=null; }
  try{ const a=await apiReady(); await a.exit_overlay(); }catch(e){}
  $("overlay").classList.add("hidden"); $("titlebar").classList.remove("hidden"); $("app").classList.remove("hidden");
  renderApp(); setStatus(false);
}
async function stopBot(){ try{ const a=await apiReady(); await a.stop(); }catch(e){} exitOverlay(); }
window.onHotkeyStop=stopBot;

function setProgress(pct,msg){
  pct=Math.max(0,Math.min(100,pct));
  $("ldFill").style.width=pct+"%"; $("ldPct").textContent=Math.round(pct)+"%";
  if(msg!==undefined) $("ldMsg").textContent=msg;
}
function showLoading(){
  document.querySelector(".ld").classList.remove("err");
  $("ldTitle").textContent="Launching bot…"; $("ldHint").style.display="";
  setProgress(0,"Starting…"); $("loading").classList.remove("hidden");
}
function hideLoading(){ $("loading").classList.add("hidden"); }
function loadingError(msg){
  document.querySelector(".ld").classList.add("err");
  $("ldTitle").textContent="Couldn't start"; $("ldHint").style.display="none";
  $("ldMsg").textContent=msg||"Error";
}
async function runBot(){
  const a=await apiReady();
  showLoading();
  try{ await a.launch(S); }catch(e){ loadingError("Launch failed"); setTimeout(hideLoading,2600); return; }
  let lastPct=0, stable=0, wasRunning=false;
  const t=setInterval(async()=>{
    let ls; try{ ls=await a.launch_status(); }catch(e){ return; }
    if(ls.phase==="error"){ clearInterval(t); loadingError(ls.msg||"Error"); setTimeout(hideLoading,3200); return; }
    if(ls.running) wasRunning=true;
    else if(wasRunning){ clearInterval(t); loadingError("Bot stopped on startup — check the bot console window."); setTimeout(hideLoading,3600); return; }
    let pct=ls.pct||0;
    if(ls.running){ stable++; pct=Math.max(pct, Math.min(97, lastPct+1.6)); }  // trickle while OCR warms up
    lastPct=Math.max(lastPct,pct);
    setProgress(lastPct, ls.msg);
    if(ls.running){
      let st={}; try{ st=await a.bot_status(); }catch(e){}
      const live = st && st.state && st.state!=="stopped" && st.state!=="idle";
      if(live || stable>60){ clearInterval(t); setProgress(100,"Ready"); setTimeout(()=>{ hideLoading(); enterOverlay(); }, 350); }
    }
  },500);
}
function wireApp(){
  $("runBtn").onclick=runBot;
  $("stopBtn").onclick=stopBot;
  $("ovStop").onclick=stopBot;
  $("modeCard").onclick=()=>{ S.dry_run=!S.dry_run; renderMode(); summary(); apply(); };
  setInterval(async()=>{ try{ if(!_ovPoll){ const a=await apiReady(); const r=await a.is_running(); setStatus(r.running);} }catch(e){} },2500);
}

function initDrag(){
  // One call on mousedown; Python drags the window (Win32) while the button is held.
  document.querySelectorAll(".pywebview-drag-region").forEach(el=>{
    el.addEventListener("mousedown", e=>{
      if(e.button!==0) return;
      e.preventDefault();
      try{ if(window.pywebview&&window.pywebview.api&&window.pywebview.api.start_drag){ window.pywebview.api.start_drag(); } }catch(_){}
    });
  });
}

function start(){
  if(!S){ S={dry_run:true,cats:[],running:false}; }
  $("minBtn").onclick=()=>apiReady().then(a=>a.minimize());
  $("closeBtn").onclick=()=>apiReady().then(a=>a.close_app());
  initDrag();
  wireApp();
  renderApp();
  setStatus(!!S.running);
}
start();
</script></body></html>"""


def _f7_loop(api):
    """Global F7 = stop the bot & leave the overlay (works even when the game is focused)."""
    prev = False
    while True:
        down = bool(_user32.GetAsyncKeyState(0x76) & 0x8000)   # VK_F7
        if down and not prev and api._running():
            try:
                if webview.windows:
                    webview.windows[0].evaluate_js("window.onHotkeyStop && window.onHotkeyStop()")
            except Exception:
                pass
        prev = down
        time.sleep(0.04)


def main():
    if not _single_instance():
        try:
            ctypes.windll.user32.MessageBoxW(
                0, "Shop Bot is already running.\n\nCheck your taskbar.",
                "Shop Bot", 0x10 | 0x40000)     # MB_ICONERROR | MB_TOPMOST
        except Exception:
            pass
        raise SystemExit(0)
    api = Api()
    # The JS bridge connects late, so bake the boot state into the HTML; the JS side
    # polls apiReady() before making bridge calls.
    boot = api.get_state()
    html = (UI_HTML.replace("__ICONS__", json.dumps(ICONS))
            .replace("__BOOT_STATE__", json.dumps(boot)))
    window = webview.create_window("Shop Bot", html=html, js_api=api,
                                   width=APP_SIZE[0], height=APP_SIZE[1],
                                   resizable=False, frameless=True, easy_drag=False,
                                   background_color="#15171e")

    def _on_closing():
        try:
            if api.proc and api.proc.poll() is None:
                api.proc.terminate()   # closing the launcher kills the running bot too
        except Exception:
            pass

    try:
        window.events.closing += _on_closing
    except Exception:
        pass
    threading.Thread(target=_f7_loop, args=(api,), daemon=True).start()
    webview.start()


if __name__ == "__main__":
    main()
