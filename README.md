# Roblox Shop Restock Bot

An auto-buyer for a Roblox tycoon shop. It watches the game window for the green
**"Shop has been restocked!"** banner, then opens the shop, reads each category with OCR,
and buys the items you picked in `config.json`.

Pure computer-vision automation: it only **screen-captures the Roblox window**, reads it with
OCR, and sends normal mouse/keyboard input — like an autoclicker. It does not inject into the
game, read game memory, or modify any game files.

## How it works

1. Watches a small region of the screen for the restock banner (green-pixel check + OCR confirm).
2. On restock: presses **E** to open the shop, then walks the Factory / Houses / Military tabs.
3. Scrolls each list, OCR-reads the item names + rarity + stock, and clicks **Buy** on the ones
   you selected.
4. Returns to the map and goes back to watching.

## Requirements

- Windows 10/11
- Python 3.12
- The Roblox game running in a window (not fullscreen-exclusive)

## Install

```bat
python -m pip install -r requirements.txt
```

The OCR model (`en/PP-OCRv5`) downloads automatically on first run (needs internet once).

## Configure

Edit **`config.json`**:

- `buy.items` — the item names to buy, per category. Names must match the in-game text.
- `buy.dry_run` — set to `true` to only **log** what it would buy (safe for a first test); set
  to `false` to actually buy.
- `buy.max_per_item` — `0` buys the whole stock; a number caps it.
- `navigation.categories` — which tabs to scan.

All button/region coordinates are **fractions** of the Roblox window, so they survive most
window sizes. If the game UI moved or your layout differs, re-calibrate:

```bat
python tools/calibrate.py
```

(Hover the targets in-game and press the on-screen hotkeys; it writes the coords back to
`config.json`.)

## Run

Open Roblox, stand next to the shop vendor, then:

```bat
python run.py
```

It prints what it sees and buys. Press **Ctrl+C** to stop.

### Launcher (GUI, optional)

There is also a small GUI to pick the items to buy, toggle test mode, and start/stop the bot:

```bat
python tools/launcher.py
```

(or double-click `launcher.bat`). While the bot runs, the window shrinks to a small
always-on-top status overlay in the top-right corner; **F7** stops the bot from anywhere.
The launcher just edits `config.json` and spawns `run.py` — it's optional.

## Project layout

```
run.py              entry point
config.json         all settings (coords, timings, catalog, what to buy)
src/
  watcher.py        main loop: detect restock -> check -> buy
  navigator.py      opens the shop, scrolls, reads + buys
  vision.py         OCR + green-banner / buy-button detection
  parser.py         turns OCR lines into {name, rarity, stock}
  capture.py        mss screen capture (self-healing)
  window.py         locates the Roblox window, fraction<->pixel mapping
  input_control.py  mouse / keyboard via Win32 SendInput
  botstatus.py      writes a small status.json (read by the launcher overlay)
tools/
  launcher.py       GUI: item selection, test mode, Run/Stop + status overlay
  calibrate.py      interactive coordinate calibration
launcher.bat        double-click shortcut for the GUI
```

## Notes

- This is game automation. Automating a game may violate its Terms of Service — use it at your
  own risk, on your own account. Provided as-is, for educational purposes.
- Nothing here talks to any external server except the one-time OCR-model download by the
  `rapidocr` library.

## License

MIT — see `LICENSE`.
