"""Entry point.  Run:  python run.py

Make sure the Roblox game window is open and you are standing next to the shop vendor,
then start the bot. It watches for the "Shop has been restocked!" banner and buys the
items you selected in config.json (buy.items).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def main():
    from src.watcher import Watcher
    Watcher().run()


if __name__ == "__main__":
    main()
