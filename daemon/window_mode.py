#!/usr/bin/env python3
"""Floats or tiles the mixer window in Hyprland.

    window_mode.py floating|tiled

Run by the window each time it opens, and when the setting changes. Floating
means centred at a mixer's size - shrunk to fit a small screen - and tiled
means left to Hyprland's layout like any other window.

The window is found by its title, since it shares the org.quickshell class
with every other shell surface. Outside Hyprland this does nothing.
"""
import json
import os
import subprocess
import sys
import time

TITLE = "Pipeworks"
WIDTH, HEIGHT = 1210, 805
FIT = 0.9  # at most this much of the screen


def hyprctl(*args):
    result = subprocess.run(["hyprctl", *args], capture_output=True, text=True, timeout=3)
    return result.stdout


def find_window(timeout=2.0):
    """The mixer's client, waiting briefly: it is still being mapped when the
    window asks for this."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            for client in json.loads(hyprctl("clients", "-j") or "[]"):
                if client.get("title") == TITLE and client.get("class") == "org.quickshell":
                    return client
        except (ValueError, subprocess.SubprocessError, OSError):
            pass
        time.sleep(0.1)
    return None


def dispatch(expression):
    hyprctl("dispatch", expression)


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("floating", "tiled"):
        print("usage: window_mode.py floating|tiled", file=sys.stderr)
        return 2
    if not os.environ.get("HYPRLAND_INSTANCE_SIGNATURE"):
        return 0
    client = find_window()
    if client is None:
        return 0
    window = f'"address:{client["address"]}"'

    if sys.argv[1] == "tiled":
        dispatch(f'hl.dsp.window.float({{ action = "disable", window = {window} }})')
        return 0

    dispatch(f'hl.dsp.window.float({{ action = "enable", window = {window} }})')
    width, height = WIDTH, HEIGHT
    try:
        monitors = json.loads(hyprctl("monitors", "-j") or "[]")
        monitor = next((m for m in monitors if m.get("id") == client.get("monitor")), None)
        if monitor:
            scale = float(monitor.get("scale") or 1)
            width = min(WIDTH, int(monitor["width"] / scale * FIT))
            height = min(HEIGHT, int(monitor["height"] / scale * FIT))
    except (ValueError, KeyError, subprocess.SubprocessError, OSError):
        pass
    dispatch(f"hl.dsp.window.resize({{ x = {width}, y = {height}, window = {window} }})")
    dispatch(f"hl.dsp.window.center({{ window = {window} }})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
