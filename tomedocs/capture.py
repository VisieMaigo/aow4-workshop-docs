"""Drive the game: open the encyclopedia, visit each tome page, capture the page
and every skill tooltip. Start with the game on the main menu."""
import json
import time

from . import po
from .config import tome_dir
from .describe import skill_type
from .game import Game
from .locate import find_template, find_text, hover_targets, norm
from .ocr import read_lines
from .tooltips import find_link, find_tooltip, snap_to_border, sub_tooltip

HOVER_DELAY = 1.5   # seconds for a tooltip to fully fade in
LOCK_DELAY = 1.5    # extra hover time before a tooltip locks so links inside it work
SETTLE_DELAY = 0.8  # seconds for a tooltip to disappear / UI to settle


class Session:
    def __init__(self, game):
        self.game = game
        self.scale = None

    def log(self, msg):
        print(f"  {msg}", flush=True)

    # --- navigation ----------------------------------------------------------
    def open_encyclopedia(self):
        frame = self.game.grab()
        w, h = self.game.size
        info = find_template(frame, "info_button", region=(w * 0.8, 0, w, h * 0.1))
        if info:
            self.scale = info[2]
            self.game.click(info[0], info[1], wait=2.5)
            frame = self.game.grab()
        back = find_template(frame, "back_button", region=(0, 0, w * 0.15, h * 0.12))
        if not back:
            raise SystemExit("Couldn't open the encyclopedia. Is the game on the main menu?")
        self.scale = self.scale or back[2]
        self.back = back
        # Category tabs sit in a row right of the back button: Back, Info, Tomes, ...
        self.game.click(back[0] + 106 * self.scale, back[1], wait=1.5)
        self.log(f"encyclopedia open (UI scale {self.scale:.2f})")

    def open_tome(self, name):
        g, s = self.game, self.scale
        lines = read_lines(g.grab().crop((0, 0, int(400 * s), int(260 * s))))
        drop = find_text(lines, "All Tomes")
        if drop:
            (_, (x0, y0, x1, y1)) = drop[0]
            box = ((x0 + x1) // 2, y0 - int(48 * s))     # search box sits above the filter dropdown
        else:
            box = (int(165 * s), int(150 * s))
        g.click(*box, wait=0.3)
        g.key("end")
        g.key("backspace", 40)
        g.type(name)
        time.sleep(1.5)

        # The result list wraps names over two lines; click the line with the
        # most distinctive words of the name.
        words = {norm(w) for w in name.split() if norm(w) not in ("tome", "of", "the")}
        panel = read_lines(g.grab().crop((0, int(220 * s), int(340 * s), g.size[1])))
        scored = [(len(words & {norm(w) for w in t.split()}), t, b) for t, b in panel]
        scored = [x for x in scored if x[0]]
        if not scored:
            raise SystemExit(f"'{name}' not found in the encyclopedia search. Is the mod enabled?")
        _, _, (x0, y0, x1, y1) = max(scored, key=lambda x: x[0])
        g.click((x0 + x1) // 2, (y0 + y1) // 2 + int(220 * s), wait=2.0)

    def close_encyclopedia(self):
        frame = self.game.grab()
        w, h = self.game.size
        back = find_template(frame, "back_button", region=(0, 0, w * 0.15, h * 0.12))
        if back:
            self.game.click(back[0], back[1], wait=1.5)
        else:
            self.game.key("esc")

    # --- capture ---------------------------------------------------------------
    def park(self):
        w, h = self.game.size
        self.game.move(w - int(15 * self.scale), h // 2)  # empty starfield, no tooltips
        time.sleep(SETTLE_DELAY)

    def hover_capture(self, point):
        """(tooltip image, its box in the frame, frame before hovering) or None."""
        self.park()
        base = self.game.grab()
        self.game.move(*point)
        time.sleep(HOVER_DELAY)
        hovered = self.game.grab()
        box = find_tooltip(base, hovered)
        if not box:
            return None
        return snap_to_border(hovered.crop(box)), box, base

    def sub_capture(self, parent_point, parent_box, link):
        self.park()
        self.game.move(*parent_point)
        time.sleep(HOVER_DELAY + LOCK_DELAY)
        base = self.game.grab()
        target = find_link(base, parent_box, link)
        if not target:
            return None, f"link '{link}' not found in its parent tooltip"
        self.game.glide(parent_point, target)
        time.sleep(HOVER_DELAY)
        box = find_tooltip(base, self.game.grab())
        if not box:
            return None, "no sub-tooltip appeared"
        return sub_tooltip(snap_to_border(self.game.grab().crop(box)), link), None

    def capture_tome(self, cfg, tome, names, only=None, preview=False):
        out = tome_dir(cfg, tome)
        out.mkdir(parents=True, exist_ok=True)
        previous = out / "manifest.json"
        manifest = json.loads(previous.read_text()) if (only or preview) and previous.exists() else {"tooltips": []}

        self.open_tome(tome["name"])
        self.park()
        page = self.game.grab()
        lines = read_lines(page)
        if not find_text(lines, tome["name"]):
            self.log(f"WARNING: page title doesn't read '{tome['name']}' - check page.png")
        page.save(out / "page.png")
        fps = find_text(lines, "FPS")
        s = self.scale
        manifest.update({
            "tome": tome["name"], "scale": s, "size": list(page.size), "page": "page.png",
            "page_lines": lines,
            "small_boxes": [[b[0] - 6 * s, b[1] - 6 * s, b[2] + 6 * s, b[3] + 6 * s] for _, b in fps],
        })

        targets = hover_targets(page, names, exclude=[tome["name"], *tome["skip"]], scale=s, lines=lines)
        for extra in tome["extra_hovers"]:
            for text, b in find_text(lines, extra)[:1]:
                targets.append((extra, ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2), "link"))
        subs = {}
        for sub in tome["subtooltips"]:
            subs.setdefault(sub["parent"], []).append(sub["link"])
        self.log(f"found {len(targets)} things to hover:")
        for name, _, kind in targets:
            extra = f" (+ nested: {', '.join(subs[name])})" if name in subs else ""
            self.log(f"  - {name} [{'skill icon' if kind == 'icon' else 'text link'}]{extra}")
        if preview:
            return
        wanted = None
        if only:
            wanted = set(only) | {p for p, links in subs.items() if set(links) & set(only)}

        for name, point, kind in targets:
            if wanted and name not in wanted:
                continue
            got = self.hover_capture(point)
            if not got:
                self.log(f"{name}: NO TOOLTIP appeared")
                continue
            img, box, base = got
            file = f"tooltip__{_slug(name)}.png"
            img.save(out / file)
            entry = {"name": name, "file": file, "anchor": list(point), "kind": kind, "type": skill_type(img)}
            if kind == "icon":  # what the icon looks like in game, for matching icon files
                r = int(32 * s)
                base.crop((point[0] - r, point[1] - r, point[0] + r, point[1] + r)).save(out / f"icon__{_slug(name)}.png")
                entry["snapshot"] = f"icon__{_slug(name)}.png"
            _replace(manifest["tooltips"], entry)
            self.log(f"{name}: tooltip {img.size[0]}x{img.size[1]}")

            for link in subs.get(name, []):
                if only and link not in only and name not in only:
                    continue
                sub_img, err = self.sub_capture(point, box, link)
                if err:
                    self.log(f"{name} > {link}: {err}")
                    continue
                sub_file = f"tooltip__{_slug(name)}__{_slug(link)}.png"
                sub_img.save(out / sub_file)
                _replace(manifest["tooltips"], {"name": f"{name} > {link}", "file": sub_file,
                                                "anchor": list(point), "kind": "sub", "parent": name})
                self.log(f"{name} > {link}: sub-tooltip {sub_img.size[0]}x{sub_img.size[1]}")
        (out / "manifest.json").write_text(json.dumps(manifest, indent=1))


def _slug(text):
    return norm(text)[:40] or "x"


def _replace(entries, entry):
    entries[:] = [e for e in entries if e["name"] != entry["name"]] + [entry]


def capture(cfg, tomes, only=None, preview=False):
    """Capture tomes; preview=True only opens each page and lists what would be hovered."""
    strings, _ = po.load_mod_strings(cfg["mod_folder"], cfg["language"])
    names = po.name_strings(strings)
    game = Game()
    print("Hands off the mouse and keyboard until this finishes.")
    game.focus()
    session = Session(game)
    session.open_encyclopedia()
    try:
        for tome in tomes:
            print(f"[{tome['name']}]")
            session.capture_tome(cfg, tome, names, only, preview)
    finally:
        session.close_encyclopedia()
