"""Drive the game: open the encyclopedia, visit each tome and unit page, capture
the page and the tooltips. Start with the game on the main menu."""
import json
import re
import time

from . import po
from .config import OUTPUT, tome_dir, unit_dir
from .describe import skill_type
from .game import Game
from .locate import find_template, find_text, hover_targets, norm, unit_abilities
from .ocr import read_lines
from .tooltips import find_link, find_tooltip, snap_to_border, sub_tooltip, titled_box

HOVER_DELAY = 1.5   # seconds for a tooltip to fully fade in
LOCK_DELAY = 1.5    # extra hover time before a tooltip locks so links inside it work
SETTLE_DELAY = 0.8  # seconds for a tooltip to disappear / UI to settle

# Encyclopedia category tabs, as distance right of the back button at 100% UI
# scale: Back, Info, Tomes, ..., Tome Units. Checked by the subtitle under
# "Encyclopedia" after clicking.
TABS = {"tomes": (106, "Tomes"), "units": (294, "Tome Units")}


class Session:
    def __init__(self, game):
        self.game = game
        self.scale = None
        self.tab = None

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
        self.log(f"encyclopedia open (UI scale {self.scale:.2f})")

    def open_tab(self, tab):
        if self.tab == tab:
            return
        offset, subtitle = TABS[tab]
        self.game.click(self.back[0] + offset * self.scale, self.back[1], wait=1.5)
        s = self.scale
        lines = read_lines(self.game.grab().crop((0, 0, int(340 * s), int(130 * s))))
        if not any(norm(t) == norm(subtitle) for t, _ in lines):
            self.log(f"WARNING: expected the '{subtitle}' section - the tab row may have changed")
        self.tab = tab

    def open_entry(self, name):
        """Search the current section for `name` and open its page."""
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

    def select_form(self, form):
        """Racial units: pick a form (e.g. 'Orcoid') in the Forms panel. Returns
        False if this unit has no forms or the form isn't listed."""
        g, s = self.game, self.scale
        w, h = g.size
        button = find_template(g.grab(), "forms_button", region=(0, 0, w * 0.45, h * 0.2), scales=[s])
        if not button:
            self.log(f"no Forms button on this page - '{form}' ignored (not a racial unit?)")
            return False
        g.click(button[0], button[1], wait=1.2)
        list_area = (int(340 * s), int(230 * s), int(650 * s), h)
        found = None
        for _ in range(8):  # scroll down through the list until the form shows
            lines = read_lines(g.grab().crop(list_area))
            hit = next(((t, b) for t, b in lines if norm(t) == norm(form)), None)
            if hit:
                found = hit
                break
            g.scroll((list_area[0] + list_area[2]) // 2, h // 2, -5)
        if found:
            _, (x0, y0, x1, y1) = found
            g.click(list_area[0] + (x0 + x1) // 2, list_area[1] + (y0 + y1) // 2, wait=1.5)
            self.log(f"form: {form}")
        else:
            self.log(f"form '{form}' not found in the Forms list")
        button = find_template(g.grab(), "forms_button", region=(0, 0, w * 0.5, h * 0.2), scales=[s])
        if button:
            g.click(button[0], button[1], wait=1.2)  # close the panel again
        return bool(found)

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

    def hover_capture(self, point, title=None, right=0.765):
        """(tooltip image, its box in the frame, frame before hovering) or None.

        title: find the tooltip by its title instead of by what changed - for
        unit pages, where the animated model changes between frames.
        """
        self.park()
        base = self.game.grab()
        self.game.move(*point)
        time.sleep(HOVER_DELAY)
        hovered = self.game.grab()
        if title:
            # Ability tooltips open left of the unit card, around the hovered row.
            w, h = hovered.size
            rx0, ry0 = int(0.2 * w), max(point[1] - int(0.45 * h), 0)
            region = (rx0, ry0, int(right * w), min(point[1] + int(0.45 * h), h))
            found = titled_box(hovered.crop(region), title)
            if not found:
                return None
            box = (found[0] + rx0, found[1] + ry0, found[2] + rx0, found[3] + ry0)
            return hovered.crop(box), box, base
        box = find_tooltip(base, hovered)
        if not box:
            return None
        return snap_to_border(hovered.crop(box)), box, base

    def sub_capture(self, parent_point, parent_box, link, titled=False):
        self.park()
        self.game.move(*parent_point)
        time.sleep(HOVER_DELAY + LOCK_DELAY)
        base = self.game.grab()
        target = find_link(base, parent_box, link)
        if not target:
            return None, f"link '{link}' not found in its parent tooltip"
        # Straight across into the tooltip first, then to the link: a slow
        # diagonal leaves the hovered element before reaching the tooltip,
        # and the tooltip closes.
        x0, y0, x1, y1 = parent_box
        m = int(12 * self.scale)
        entry = (min(max(parent_point[0], x0 + m), x1 - m), min(max(parent_point[1], y0 + m), y1 - m))
        self.game.glide(parent_point, entry, steps=6)
        self.game.glide(entry, target)
        time.sleep(HOVER_DELAY)
        if titled:  # unit pages: the animated model defeats frame differences
            for _ in range(6):  # nested tooltips can take a moment to open
                frame = self.game.grab()
                box = titled_box(frame.crop((0, 0, int(0.85 * frame.width), frame.height)), link)
                if box:
                    return frame.crop(box), None
                time.sleep(0.5)
            (OUTPUT / "_debug").mkdir(parents=True, exist_ok=True)
            frame.save(OUTPUT / "_debug" / f"sub_fail__{link.replace(' ', '_')}.png")
            return None, "no sub-tooltip appeared (last frame saved in output/_debug)"
        box = find_tooltip(base, self.game.grab())
        if not box:
            return None, "no sub-tooltip appeared"
        return sub_tooltip(snap_to_border(self.game.grab().crop(box)), link), None

    def snap_page(self, out, title, manifest, only, preview):
        """Screenshot the open page (cursor parked) and fill in the manifest basics."""
        self.park()
        page = self.game.grab()
        lines = read_lines(page)
        if not find_text(lines, title):
            self.log(f"WARNING: page doesn't read '{title}' - check page.png")
        page.save(out / "page.png")
        fps = find_text(lines, "FPS")
        s = self.scale
        manifest.update({
            "scale": s, "size": list(page.size), "page": "page.png", "page_lines": lines,
            "small_boxes": [[b[0] - 6 * s, b[1] - 6 * s, b[2] + 6 * s, b[3] + 6 * s] for _, b in fps],
        })
        return page, lines

    def hover_all(self, out, targets, item, manifest, only, preview, snapshots=True):
        """Hover each (name, point, kind) target, plus configured nested tooltips."""
        subs = {}
        for sub in item["subtooltips"]:
            subs.setdefault(sub["parent"], []).append(sub["link"])
        self.log(f"found {len(targets)} things to hover:")
        for name, _, kind in targets:
            extra = f" (+ nested: {', '.join(subs[name])})" if name in subs else ""
            self.log(f"  - {name} [{kind}]{extra}")
        if preview:
            return
        wanted = (set(only) | {p for p, links in subs.items() if set(links) & set(only)}) if only else None
        s = self.scale
        for name, point, kind in targets:
            if wanted and name not in wanted:
                continue
            if kind == "rank":  # opens over the card's left edge, titled "<Rank> Rank Unit"
                got = self.hover_capture(point, title="Rank Unit", right=0.85)
            else:
                got = self.hover_capture(point, title=name if kind == "ability" else None)
            if not got:
                self.log(f"{name}: NO TOOLTIP appeared")
                continue
            img, box, base = got
            if kind in ("icon", "link"):  # trim what the frame difference took in around the border
                tight = titled_box(img, name)
                if tight:
                    img = img.crop(tight)
            file = f"tooltip__{_slug(name)}.png"
            img.save(out / file)
            entry = {"name": name, "file": file, "anchor": list(point), "kind": kind}
            if kind != "ability":
                entry["type"] = skill_type(img)
            if snapshots and kind == "icon":  # what the icon looks like in game, for matching icon files
                r = int(32 * s)
                base.crop((point[0] - r, point[1] - r, point[0] + r, point[1] + r)).save(out / f"icon__{_slug(name)}.png")
                entry["snapshot"] = f"icon__{_slug(name)}.png"
            _replace(manifest["tooltips"], entry)
            self.log(f"{name}: tooltip {img.size[0]}x{img.size[1]}")

            for link in subs.get(name, []):
                if only and link not in only and name not in only:
                    continue
                sub_img, err = self.sub_capture(point, box, link, titled=kind in ("ability", "rank"))
                if err:
                    self.log(f"{name} > {link}: {err}")
                    continue
                sub_file = f"tooltip__{_slug(name)}__{_slug(link)}.png"
                sub_img.save(out / sub_file)
                _replace(manifest["tooltips"], {"name": f"{name} > {link}", "file": sub_file,
                                                "anchor": list(point), "kind": "sub", "parent": name})
                self.log(f"{name} > {link}: sub-tooltip {sub_img.size[0]}x{sub_img.size[1]}")

    def capture_tome(self, cfg, tome, names, only=None, preview=False):
        out, manifest = _start(tome_dir(cfg, tome), only, preview)
        self.open_tab("tomes")
        self.open_entry(tome["name"])
        page, lines = self.snap_page(out, tome["name"], manifest, only, preview)
        manifest["tome"] = tome["name"]
        targets = hover_targets(page, names, exclude=[tome["name"], *tome["skip"]], scale=self.scale, lines=lines)
        for extra in tome["extra_hovers"]:
            for text, b in find_text(lines, extra)[:1]:
                targets.append((extra, ((b[0] + b[2]) // 2, (b[1] + b[3]) // 2), "link"))
        targets = [(n, p, "icon" if k == "icon" else "link") for n, p, k in targets]
        self.hover_all(out, targets, tome, manifest, only, preview)
        if not preview:
            (out / "manifest.json").write_text(json.dumps(manifest, indent=1))

    def capture_unit(self, cfg, unit, names, only=None, preview=False):
        out, manifest = _start(unit_dir(cfg, unit), only, preview)
        self.open_tab("units")
        self.open_entry(unit["name"])
        if unit["form"]:
            self.select_form(unit["form"])
        page, lines = self.snap_page(out, unit["name"], manifest, only, preview)
        manifest.update({"unit": unit["name"], "form": unit["form"]})
        abilities = unit_abilities(page, names, self.scale, lines)
        if not preview:
            manifest["abilities"] = [{"name": n, "attack": a, "mod": m} for n, _, a, m in abilities]
        if unit["abilities"]:
            # The user's pick, in their order (names matched loosely).
            by_name = {norm(n): (n, p) for n, p, _, _ in abilities}
            targets = []
            for want in unit["abilities"]:
                hit = by_name.get(norm(want)) or next((v for k, v in by_name.items() if norm(want) in k), None)
                if hit:
                    targets.append((hit[0], hit[1], "ability"))
                else:
                    self.log(f"'{want}' isn't on this unit's card")
        else:
            # Default: attacks and the mod's own abilities; generic base-game
            # passives (Shield Defense, immunities...) only when asked for.
            targets = [(n, p, "ability") for n, p, attack, mod in abilities if attack or mod]
        picked = {t[0] for t in targets}
        self.log("abilities on the card ([x] = captured" + ("" if unit["abilities"] else ", default pick") + "):")
        for n, _, attack, mod in abilities:
            tags = ", ".join(t for t, on in (("attack", attack), ("mod", mod)) if on)
            self.log(f"  [{'x' if n in picked else ' '}] {n}{f' ({tags})' if tags else ''}")
        if unit.get("rank_rewards"):
            # Unit rank rewards: links in the tooltip of the "Tier N <Rank>" line.
            tier = next((b for t, b in lines if b[0] > 0.74 * page.width and re.search(r"\bTier\b", t)), None)
            if tier:
                targets.append(("Unit Rank", (tier[0] + int(10 * self.scale), (tier[1] + tier[3]) // 2), "rank"))
                unit = {**unit, "subtooltips": unit["subtooltips"] + [{"parent": "Unit Rank", "link": r} for r in unit["rank_rewards"]]}
            else:
                self.log("rank line ('Tier ...') not found on the card")
        self.hover_all(out, targets, unit, manifest, only, preview, snapshots=False)
        if not preview:
            (out / "manifest.json").write_text(json.dumps(manifest, indent=1))


def _start(out, only, preview):
    out.mkdir(parents=True, exist_ok=True)
    previous = out / "manifest.json"
    manifest = json.loads(previous.read_text()) if (only or preview) and previous.exists() else {"tooltips": []}
    return out, manifest


def _slug(text):
    return norm(text)[:40] or "x"


def _replace(entries, entry):
    entries[:] = [e for e in entries if e["name"] != entry["name"]] + [entry]


def capture(cfg, tomes, units=(), only=None, preview=False):
    """Capture tomes and units; preview=True only opens each page and lists what
    would be hovered."""
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
        for unit in units:
            print(f"[{unit['name']}{' - ' + unit['form'] if unit['form'] else ''}]")
            session.capture_unit(cfg, unit, names, only, preview)
    finally:
        session.close_encyclopedia()
