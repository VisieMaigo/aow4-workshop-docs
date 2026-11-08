"""Game window, screenshots and mouse/keyboard input (Windows)."""
import ctypes
import time

# Must happen before any coordinate/screen calls so we work in physical pixels.
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import numpy as np
import win32api
import win32con
import win32gui
from PIL import ImageGrab
from pynput import keyboard, mouse

WINDOW_TITLE = "Age of Wonders 4"

mouse_ctl = mouse.Controller()
kb_ctl = keyboard.Controller()


class Game:
    """The running game window. All coordinates are relative to its client area."""

    def __init__(self):
        hits = []

        def cb(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd).startswith(WINDOW_TITLE):
                hits.append(hwnd)

        win32gui.EnumWindows(cb, None)
        if not hits:
            raise SystemExit("Age of Wonders 4 is not running. Start the game and go to the main menu.")
        self.hwnd = hits[0]

    @property
    def rect(self):
        """Client area in screen coordinates: (left, top, right, bottom)."""
        _, _, w, h = win32gui.GetClientRect(self.hwnd)
        left, top = win32gui.ClientToScreen(self.hwnd, (0, 0))
        return left, top, left + w, top + h

    @property
    def size(self):
        l, t, r, b = self.rect
        return r - l, b - t

    def monitor(self):
        info = win32api.GetMonitorInfo(win32api.MonitorFromWindow(self.hwnd, win32con.MONITOR_DEFAULTTONEAREST))
        return info["Device"], info["Monitor"]

    def grab(self):
        return ImageGrab.grab(bbox=self.rect, all_screens=True).convert("RGB")

    def focus(self):
        if win32gui.IsIconic(self.hwnd):
            win32gui.ShowWindow(self.hwnd, win32con.SW_RESTORE)
        # Windows refuses SetForegroundWindow unless we "own" input; an Alt tap unlocks it.
        ctypes.windll.user32.keybd_event(0x12, 0, 0, 0)
        ctypes.windll.user32.keybd_event(0x12, 0, 2, 0)
        win32gui.SetForegroundWindow(self.hwnd)
        time.sleep(0.5)

    # --- input -----------------------------------------------------------
    def move(self, x, y):
        l, t, _, _ = self.rect
        mouse_ctl.position = (l + int(x), t + int(y))
        # Nudge with real relative input so the game registers a hover.
        mouse_ctl.move(1, 0)
        mouse_ctl.move(-1, 0)

    def glide(self, start, end, steps=20):
        """Move smoothly, so the game sees the cursor travel (e.g. into a tooltip)."""
        (x0, y0), (x1, y1) = start, end
        l, t, _, _ = self.rect
        for i in range(1, steps + 1):
            mouse_ctl.position = (l + round(x0 + (x1 - x0) * i / steps), t + round(y0 + (y1 - y0) * i / steps))
            time.sleep(0.015)
        self.move(x1, y1)

    def click(self, x, y, wait=0.8):
        self.move(x, y)
        time.sleep(0.05)
        # Games often miss instantaneous press/release pairs; hold briefly.
        mouse_ctl.press(mouse.Button.left)
        time.sleep(0.08)
        mouse_ctl.release(mouse.Button.left)
        time.sleep(wait)

    def key(self, name, times=1):
        k = getattr(keyboard.Key, name, None) or name
        for _ in range(times):
            kb_ctl.press(k)
            kb_ctl.release(k)
            time.sleep(0.02)

    def type(self, text):
        for ch in text:
            kb_ctl.press(ch)
            kb_ctl.release(ch)
            time.sleep(0.04)

    def scroll(self, x, y, clicks):
        """Mouse wheel at a point; negative = down."""
        self.move(x, y)
        for _ in range(abs(clicks)):
            mouse_ctl.scroll(0, -1 if clicks < 0 else 1)
            time.sleep(0.05)
        time.sleep(0.4)

    def looks_black(self):
        return np.asarray(self.grab()).mean() < 3
