# Roblox Shop Restock Bot

An auto-buyer for a Roblox MiniWar shop. It watches the game window for the green
**"Shop has been restocked!"** banner, then opens the shop, reads each category with OCR,
and buys the items you selected in the launcher.

Pure computer-vision automation: it only **screen-captures the Roblox window**, reads it with
OCR, and sends normal mouse/keyboard input — like an autoclicker. It does **not** inject into
the game, read game memory, or modify any game files.

---

## Features

- Automatic restock detection
- OCR-based item recognition
- Easy-to-use GUI launcher
- Dry Run mode for safe testing
- Automatic scrolling through all shop categories
- Resolution-independent coordinate system
- No memory reading or code injection

---

## How it works

1. Watches a small region of the screen for the green **"Shop has been restocked!"** banner.
2. Confirms the banner using OCR.
3. Presses **E** to open the shop.
4. Walks through the Factory, Houses and Military tabs.
5. Scrolls each category and OCR-reads the item names, rarity and stock.
6. Buys the items you selected.
7. Closes the shop and waits for the next restock.

---

# Requirements

- Windows 10 or Windows 11
- Python 3.12
- Roblox running in **Windowed** mode

---

# Installation (For Beginners, takes 3 min)

## 1. Install Python

Download **Python 3.12** from the official website:

https://www.python.org/downloads/

During installation **make sure** to enable:

✅ **Add Python to PATH**

Then click **Install Now**.

---

## 2. Download the project

Download this repository as a ZIP from GitHub and extract it anywhere.

Example:

```
C:\Users\YourName\Downloads\roblox-shop-restock-bot
```

---

## 3. Open Command Prompt

Open the project folder.

Click the address bar in File Explorer.

Type:

```text
cmd
```

Press **Enter**.

A Command Prompt will open inside the project folder.

---

## 4. Install dependencies

Run:

```bat
python -m pip install -r requirements.txt
```

The installation may take a few minutes.

The OCR model (`PP-OCRv5`) is downloaded automatically the first time you run the bot (internet required once).

---

## 5. Launch the bot

Simply double-click:

```
launcher.bat
```

or run:

```bat
python tools/launcher.py
```

The launcher lets you:

- Select which items to buy
- Enable or disable **Dry Run** (test mode)
- Start and stop the bot

All settings are saved automatically.

---

# In-Game Settings (Important)

Before running the bot:

- Open Roblox in **Windowed** mode and maximize the game window.
- Do **not** use Exclusive Fullscreen.
- Join **MiniWar**.
- Open the **⚙️ Settings** menu in the top-right corner.

Recommended settings:

- ✅ Enable **Low Performance**
- ✅ Disable **Alliances**

---

# Running

1. Join **MiniWar**.
2. Stand next to the shop NPC.
3. Open **launcher.bat**.
4. Select the items you want to buy.
5. Click **Start Bot**.

The bot will automatically wait for the next shop restock.

Press **F7** at any time to stop the bot.

---

# Calibration (Optional)

If a game update changes the UI and buttons no longer line up correctly, run:

```bat
python tools/calibrate.py
```

Follow the on-screen instructions to recalibrate the coordinates.

---

# Project Layout

```
run.py              Entry point
config.json         Saved settings

src/
  watcher.py        Restock detection loop
  navigator.py      Shop navigation
  vision.py         OCR and image detection
  parser.py         OCR text parser
  capture.py        Screen capture
  window.py         Roblox window detection
  input_control.py  Mouse & keyboard input
  botstatus.py      Launcher status information

tools/
  launcher.py       GUI launcher
  calibrate.py      Interactive coordinate calibration

launcher.bat        Launcher shortcut
```

---

# Notes

- The only internet connection made by the bot is the one-time download of the OCR model on first launch.
- The developers of MiniWar have confirmed that this bot can be used.

# Disclaimer
This software is provided "as is", for educational and research purposes only. The authors accept no responsibility or liability for how it is used. You are solely responsible for your own actions.
We do not endorse or recommend using this software with Roblox or any other game. Automating a game may violate its Terms of Service and can result in penalties up to and including a permanent account ban. If you choose to use it, you do so entirely at your own risk.
The authors are not liable for any misuse, for any damage, data loss, account suspension, or ban, or for any use of this software (copies, forks, etc.) for malicious or prohibited purposes. By downloading or running it, you accept full responsibility for the consequences.
---

# License

MIT License — see `LICENSE`.
