"""Build the workshop images for captured tomes and units:

  <Tome> - Overview.png   the tome page as shown in game, encyclopedia UI blended away
  <Tome> - Tooltips.png   every tooltip (sub-tooltips stacked under their parent) with the
                          mod's icon beside it, on the same starfield, as large as fits
  <Unit>.png              the unit page (model and stat card), UI blended away, with
                          the captured ability tooltips beside and below the model
"""
import itertools
import json

import cv2
import numpy as np
from PIL import Image, ImageFilter

from . import icons as icon_match
from .background import UNIT_PANEL_W, _content_mask, build_plate
from .config import file_name, final_dir, tome_dir, unit_dir
from .describe import skill_type
from .locate import find_template, norm

PAD = 32          # outer border
GAP = 18          # between tooltips
SHADOW = 12       # blur radius of the drop shadow behind tooltips
ICON = 88         # size of the mod icon shown left of each tooltip
ICON_GAP = 10
CARD_MARGIN = 33  # the unit stat card's gap to the right screen edge at 100% UI scale


def unit_size(u):
    """A unit is a tooltip plus any sub-tooltips stacked under it (+ icon space)."""
    return (max(i.width for i in u["imgs"]) + u["icon_space"],
            sum(i.height for i in u["imgs"]) + GAP * (len(u["imgs"]) - 1))


def reading_order(u):
    # Icons on roughly the same row (within 60 px) read left to right.
    return (u["anchor"][1] // 60, u["anchor"][0])


def arrange(units, size):
    """Column count that lets tooltips be largest: (scale, columns). Tallest units
    go first into the shortest column; each column keeps reading order."""
    best = None
    for n in range(1, len(units) + 1):
        columns = [[] for _ in range(n)]
        for u in sorted(units, key=lambda u: -unit_size(u)[1]):
            min(columns, key=lambda c: sum(unit_size(x)[1] for x in c)).append(u)
        columns = [sorted(c, key=reading_order) for c in columns if c]
        columns.sort(key=lambda c: reading_order(c[0]))
        width = sum(max(unit_size(u)[0] for u in c) for c in columns) + GAP * (len(columns) - 1)
        height = max(sum(unit_size(u)[1] for u in c) + GAP * (len(c) - 1) for c in columns)
        s = min(1.0, (size[0] - 2 * PAD) / width, (size[1] - 2 * PAD) / height)
        if best is None or s > best[0] + 1e-6:
            best = (s, columns)
    return best


def scaled(img, s):
    return img if s == 1 else img.resize((round(img.width * s), round(img.height * s)), Image.LANCZOS)


def paste_with_shadow(canvas, img, x, y):
    shadow = Image.new("L", canvas.size, 0)
    shadow.paste(200, (x + 4, y + 6, x + img.width + 4, y + img.height + 6))
    canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(SHADOW)))
    canvas.paste(img, (x, y))


def paste_icon(canvas, icon, x, y, size):
    icon = icon.copy()
    icon.thumbnail((size, size), Image.LANCZOS)
    shadow = Image.new("L", canvas.size, 0)
    shadow.paste(icon.getchannel("A").point(lambda a: a * 0.8), (x + 3, y + 5))
    canvas.paste(Image.new("RGB", canvas.size, (0, 0, 0)), (0, 0), shadow.filter(ImageFilter.GaussianBlur(6)))
    canvas.paste(icon, (x + (size - icon.width) // 2, y), icon)


def find_icons(tome, entries, folder):
    available = icon_match.load_icons(tome["icon_folder"])
    if not available:
        return {}
    found = {}
    for e in entries:
        if e["kind"] == "sub":
            continue  # sub-tooltips show their own icon in their header
        file = tome["icons"].get(e["name"])
        how = "project file"
        if not file:
            file, how = icon_match.match(e, folder, available)
        if file in available:
            found[e["name"]] = available[file]
        print(f"    icon {e['name']}: {file or '-'} ({how})")
    return found


def output_name(tome, kind):
    """e.g. 'Tome of the Looming Frost - Overview.png'."""
    return f"{file_name(tome['name'])} - {kind}.png"


def compose(cfg, tome):
    folder = tome_dir(cfg, tome)
    manifest = json.loads((folder / "manifest.json").read_text())
    size = tuple(cfg.get("output_size") or manifest["size"])
    page = Image.open(folder / manifest["page"]).convert("RGB")
    s = manifest["scale"]

    plate = build_plate(page, s, manifest["small_boxes"])
    path = final_dir(cfg) / output_name(tome, "Overview")
    Image.fromarray(plate).resize(size, Image.LANCZOS).save(path)
    print(f"  {path}")

    # Units always get their own dedicated images, so they're left out here.
    for e in manifest["tooltips"]:
        if "type" not in e and e["kind"] != "sub":
            e["type"] = skill_type(Image.open(folder / e["file"]))
    hidden = set(tome["hide_in_tooltips_image"]) | {e["name"] for e in manifest["tooltips"] if e.get("type") == "Unit"}
    shown = [e for e in manifest["tooltips"] if e["name"] not in hidden and e.get("parent") not in hidden]
    plain = build_plate(page, s, manifest["small_boxes"], remove_content=True)
    tooltips_image(folder, shown, find_icons(tome, shown, folder) if shown else {}, plain, size,
                   final_dir(cfg) / output_name(tome, "Tooltips"))


def compose_unit(cfg, unit):
    """<Unit>.png: the unit page (model and stat card, UI blended away) with the
    captured ability tooltips, shrunk, in the free space left of the model and,
    if they don't all fit there, in a row below it."""
    folder = unit_dir(cfg, unit)
    manifest = json.loads((folder / "manifest.json").read_text())
    size = tuple(cfg.get("output_size") or manifest["size"])
    # The model is animated: the user can supply a screenshot with a better pose.
    page = Image.open(unit.get("page_image") or folder / manifest["page"]).convert("RGB")
    if page.size != tuple(manifest["size"]):
        page = page.resize(tuple(manifest["size"]), Image.LANCZOS)
    s = manifest["scale"]
    boxes = list(manifest["small_boxes"])
    # The round button on the panel edge: Forms on racial units, the unit's
    # type badge otherwise (no template for those, so use the Forms position).
    button = find_template(page, "forms_button", region=(0, 0, page.width * 0.3, page.height * 0.2), scales=[s])
    bx, by = button[:2] if button else (373 * s, 103 * s)
    r = 30 * s
    boxes.append([bx - r, by - r, bx + r, by + r])
    W, H = page.size
    # The stat card: its flat dark background must not be copied as "starfield".
    card_left = min((b[0] for _, b in manifest["page_lines"] if b[0] > 0.74 * W), default=int(0.76 * W))
    card = [card_left - 40 * s, 0, W, H]
    if unit.get("base_image"):  # the user's own finished background: used as is
        canvas = Image.open(unit["base_image"]).convert("RGB").resize(page.size, Image.LANCZOS)
        plate = np.asarray(canvas)
    else:
        plate = build_plate(page, s, boxes, panel_w=UNIT_PANEL_W, no_source=[card])
        canvas = Image.fromarray(plate)

    # Ability tooltips in the user's order (else card order), nested ones under their parent.
    order = [norm(a) for a in unit["abilities"]]
    tips = [e for e in manifest["tooltips"] if e["kind"] != "sub"]
    tips.sort(key=lambda e: order.index(norm(e["name"])) if norm(e["name"]) in order else len(order))
    # Unit rank: only its chosen rewards are shown, each on its own, after the abilities.
    groups = [[Image.open(folder / x["file"]).convert("RGB")
               for x in [e] + [x for x in manifest["tooltips"] if x.get("parent") == e["name"]]]
              for e in tips if e["kind"] != "rank"]
    groups += [[Image.open(folder / x["file"]).convert("RGB")] for e in tips if e["kind"] == "rank"
               for x in manifest["tooltips"] if x.get("parent") == e["name"]]

    # Free space: left of the model, and below it (up to the stat card).
    mx0, my0, mx1, my1 = model_box(plate, int(0.2 * W), card_left)
    pad = int(PAD * s)
    margin = int(CARD_MARGIN * s)  # same gap to the screen edge as the stat card on the right
    left = (margin, pad, mx0 - GAP, H - pad)
    below = (pad, my1 + GAP, card_left - 2 * GAP, H - pad)
    def fit(arrange):
        if unit.get("tooltip_scale"):  # the user's fixed size: may reach past the model's edge
            k = unit["tooltip_scale"]
            return place_balanced([[scaled(i, k) for i in g] for g in groups], left, overflow=True), k
        k = 1.0
        while groups and k >= 0.4:
            layout = arrange([[scaled(i, k) for i in g] for g in groups])
            if layout:
                return layout, k
            k -= 0.01
        return None, 0
    # Even columns read best; take them unless overflowing below the model is much larger.
    layout, k = fit(lambda g: place_balanced(g, left))
    packed, pk = fit(lambda g: place(g, left, below))
    if pk > k + 0.05:
        layout, k = packed, pk
    if groups and not layout:
        print(f"  WARNING: {len(groups)} tooltips don't fit around the model - try fewer abilities")
    for img, x, y in layout or []:
        paste_with_shadow(canvas, img, x, y)
    path = final_dir(cfg) / f"{file_name(unit['name'])}.png"
    canvas.resize(size, Image.LANCZOS).save(path)
    print(f"  {path}" + (f"  ({len(groups)} tooltips at {k:.0%})" if layout else ""))


BODY_COLUMN = 0.38


def model_box(plate, x0, x1):
    """Bounding box of the unit model: the big busy/bright blobs between x0 and x1."""
    mask = _content_mask(plate.astype(np.float32))
    mask[:, :x0] = 0
    mask[:, x1:] = 0
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    big = [st for st in stats[1:n] if st[cv2.CC_STAT_AREA] > 0.01 * mask.size]
    if not big:
        h, w = mask.shape
        return int(0.35 * w), int(0.15 * h), int(0.65 * w), int(0.85 * h)
    top, bottom = min(b[1] for b in big), max(b[1] + b[3] for b in big)
    # Left edge: first column with substantial mass, so thin tails/wisps don't count.
    cols = (mask[top:bottom] > 0).sum(axis=0)
    solid = np.flatnonzero(cols >= BODY_COLUMN * (bottom - top))
    left = int(solid[0]) if len(solid) else min(b[0] for b in big)
    return left, top, max(b[0] + b[2] for b in big), bottom


def place_balanced(groups, left, overflow=False):
    """Positions for tooltip groups in columns left of the model, split (in
    order, nearest column first) so the columns are about equally tall, each
    centred vertically, the block from the left edge. overflow: may reach
    past the right edge. None if they don't fit."""
    lx0, ly0, lx1, ly1 = left
    size = [(max(i.width for i in g), sum(i.height for i in g) + GAP * (len(g) - 1)) for g in groups]

    def height(c):
        return sum(size[i][1] for i in c) + GAP * (len(c) - 1)

    for n in range(1, len(groups) + 1):
        # Contiguous split into n columns with the lowest tallest column.
        best = None
        for cuts in itertools.combinations(range(1, len(groups)), n - 1):
            bounds = (0,) + cuts + (len(groups),)
            cols = [range(a, b) for a, b in zip(bounds, bounds[1:])]
            tallest = max(height(c) for c in cols)
            if best is None or tallest < best[0]:
                best = (tallest, cols)
        tallest, cols = best
        width = sum(max(size[i][0] for i in c) for c in cols) + GAP * (n - 1)
        if tallest > ly1 - ly0 or (width > lx1 - lx0 and not overflow):
            continue
        out, right = [], lx0 + width  # from the left edge, mirroring the stat card's margin
        for c in cols:
            cw = max(size[i][0] for i in c)
            y = ly0 + (ly1 - ly0 - height(c)) // 2
            for i in c:
                for img in groups[i]:
                    out.append((img, right - cw, y))
                    y += img.height + GAP
            right -= cw + GAP
        return out
    return None


def place(groups, left, below):
    """Positions [(img, x, y)] for tooltip groups: columns in `left`, filled
    from the model outwards (each centred vertically), overflow in a row in
    `below`. None if they don't fit."""
    lx0, ly0, lx1, ly1 = left
    bx0, by0, bx1, by1 = below
    columns, row = [[]], []
    col_right, col_w, y, x = lx1, 0, ly0, bx0
    for g in groups:
        gw, gh = max(i.width for i in g), sum(i.height for i in g) + GAP * (len(g) - 1)
        if not row and gh <= ly1 - ly0:
            if y + gh > ly1 and columns[-1]:  # column full: start the next one further left
                col_right, col_w, y = col_right - col_w - GAP, 0, ly0
                columns.append([])
            if col_right - gw >= lx0:
                columns[-1].append((g, col_right - gw, y, gh))
                col_w, y = max(col_w, gw), y + gh + GAP
                continue
        if gw <= bx1 - x and gh <= by1 - by0:
            row.append((g, x, by0))
            x += gw + GAP
        else:
            return None
    out = []
    for col in columns:
        used = sum(gh for *_, gh in col) + GAP * (len(col) - 1)
        shift = (ly1 - ly0 - used) // 2
        for g, gx, gy, _ in col:
            for img in g:
                out.append((img, gx, gy + shift))
                gy += img.height + GAP
    for g, gx, gy in row:
        for img in g:
            out.append((img, gx, gy))
            gy += img.height + GAP
    return out


def tooltips_image(folder, shown, icons, plain, size, path):
    """Tooltips in columns (sub-tooltips under their parent, icons beside them)
    on a plain background, as large as fits."""
    if not shown:
        return
    space = ICON + ICON_GAP if icons else 0
    units = []
    for e in shown:
        if e["kind"] == "sub":
            continue
        group = [e] + [x for x in shown if x.get("parent") == e["name"]]
        units.append({"anchor": e["anchor"], "icon_space": space,
                      "imgs": [Image.open(folder / x["file"]).convert("RGB") for x in group],
                      "icons": [icons.get(x["name"]) for x in group]})
    k, columns = arrange(units, size)
    canvas = Image.fromarray(plain).resize(size, Image.LANCZOS)
    space_k = round(space * k)
    col_items = [[(scaled(i, k), ic) for u in c for i, ic in zip(u["imgs"], u["icons"])] for c in columns]
    col_w = [max(i.width for i, _ in c) + space_k for c in col_items]
    x = (size[0] - sum(col_w) - GAP * (len(col_w) - 1)) // 2
    for items, w in zip(col_items, col_w):
        y = (size[1] - sum(i.height for i, _ in items) - GAP * (len(items) - 1)) // 2
        for img, icon in items:
            if icon is not None:
                paste_icon(canvas, icon, x, y, round(ICON * k))
            paste_with_shadow(canvas, img, x + space_k, y)
            y += img.height + GAP
        x += w + GAP
    canvas.save(path)
    print(f"  {path}  ({len(columns)} columns, scale {k:.0%})")
