"""Watch someone use the game and keep screenshots, to learn a new part of the UI.

    python tools/watch.py units

Passive: it never moves the mouse. While the game window has focus it saves a
screenshot just before every click (with the click position), and on hotkeys:

    F7  screenshot now, marked "hover" (press while a tooltip is showing)
    F8  screenshot now, marked "page" (press when a page is fully shown)
    F9  stop

Output: output/_watch/<name>/NNN_<kind>.png + log.json (positions in game
client coordinates, plus key presses).
"""
import json
import queue
import sys
import threading
import time
from pathlib import Path

import win32gui
from pynput import keyboard, mouse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tomedocs.config import OUTPUT  # noqa: E402
from tomedocs.game import Game  # noqa: E402


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else "session"
    out = OUTPUT / "_watch" / name
    out.mkdir(parents=True, exist_ok=True)
    game = Game()
    log, shots = [], queue.Queue()
    start = time.time()

    def shooter():
        # Screenshots happen off the input-hook thread so the mouse never lags.
        while (job := shots.get()) is not None:
            i, kind = job
            game.grab().save(out / f"{i:03d}_{kind}.png")

    def record(kind, **info):
        i = len(log)
        left, top, _, _ = game.rect
        x, y = mouse.Controller().position
        log.append({"i": i, "t": round(time.time() - start, 2), "kind": kind, "x": x - left, "y": y - top, **info})
        shots.put((i, kind))
        print(f"  {i:03d} {kind} at {x - left},{y - top} {info or ''}", flush=True)

    def in_game():
        return win32gui.GetForegroundWindow() == game.hwnd

    def on_click(x, y, button, pressed):
        if pressed and in_game():
            record("click", button=button.name)

    def on_press(key):
        if key == keyboard.Key.f9:
            return False
        if key == keyboard.Key.f7:
            record("hover")
        elif key == keyboard.Key.f8:
            record("page")
        elif in_game():
            k = key.char if isinstance(key, keyboard.KeyCode) and key.char else getattr(key, "name", str(key))
            log.append({"t": round(time.time() - start, 2), "kind": "key", "key": k})

    worker = threading.Thread(target=shooter, daemon=True)
    worker.start()
    print(f"Watching (game {game.size[0]}x{game.size[1]}). F7 = tooltip shot, F8 = page shot, F9 = stop.", flush=True)
    with mouse.Listener(on_click=on_click), keyboard.Listener(on_press=on_press) as kl:
        kl.join()
    shots.put(None)
    worker.join()
    (out / "log.json").write_text(json.dumps(log, indent=1))
    print(f"Saved {len(log)} events to {out}", flush=True)


if __name__ == "__main__":
    main()
