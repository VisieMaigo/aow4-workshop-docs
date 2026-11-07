"""Build the workshop images for a captured tome:

  <Tome> - Overview.png  the tome page as shown in game, encyclopedia UI blended away
  <Tome> - Tooltips.png  every tooltip (sub-tooltips stacked under their parent) with the
                mod's icon beside it, on the same starfield, as large as fits
"""
import json

from PIL import Image, ImageFilter

from . import icons as icon_match
from .background import build_plate
from .config import file_name, final_dir, tome_dir
from .describe import skill_type

PAD = 32          # outer border
GAP = 18          # between tooltips
SHADOW = 12       # blur radius of the drop shadow behind tooltips
ICON = 88         # size of the mod icon shown left of each tooltip
ICON_GAP = 10


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
    if not shown:
        return
    icons = find_icons(tome, shown, folder)
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

    plain = build_plate(page, s, manifest["small_boxes"], remove_content=True)
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
    path = final_dir(cfg) / output_name(tome, "Tooltips")
    canvas.save(path)
    print(f"  {path}  ({len(columns)} columns, scale {k:.0%})")
