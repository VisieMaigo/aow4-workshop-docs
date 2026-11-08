"""Project settings: one JSON file per mod in projects/."""
import json
import re
from pathlib import Path

from . import po

ROOT = Path(__file__).resolve().parent.parent
PROJECTS = ROOT / "projects"
OUTPUT = ROOT / "output"

TOME_DEFAULTS = {
    "icon_folder": "",          # folder with the mod's icon PNGs (optional)
    "icons": {},                # {"Skill name": "file.png"} when automatic matching gets it wrong
    "subtooltips": [],          # [{"parent": "Skill name", "link": "Link text inside its tooltip"}]
    "hide_in_tooltips_image": [],  # skill names to leave out of the tooltips image
    "skip": [],                 # names not to hover at all
    "extra_hovers": [],         # base-game names on the page that should be captured too
}

UNIT_DEFAULTS = {
    "form": "",                 # racial units: form to show, e.g. "Orcoid" (default: the game's, Human)
    "abilities": [],            # abilities to capture, in display order; empty = attacks + the mod's own abilities
    "subtooltips": [],          # [{"parent": "Ability name", "link": "Link text inside its tooltip"}]
    "rank_rewards": [],         # unit rank rewards to capture, e.g. ["Champion Arcfire Strike"]
    "tooltip_scale": None,      # fixed tooltip size, e.g. 0.9; default: as large as fits beside the model
    "base_image": "",           # own finished background (UI already removed): only the tooltips are added
    "page_image": "",           # own 1920x1080 screenshot of the unit page (no tooltip) to use instead of the captured one
}


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def init(mod_folder, name=None, language="EN"):
    """Create projects/<name>.json listing the tomes found in the mod's .po files."""
    mod_folder = Path(mod_folder)
    strings, _ = po.load_mod_strings(mod_folder, language)
    if not strings:
        raise SystemExit(f"No .po files found in {mod_folder / 'Language' / language}")
    tomes = po.find_tomes(strings)
    units = po.find_units(strings)
    name = name or slug(mod_folder.name)
    cfg = {
        "mod_folder": str(mod_folder),
        "language": language,
        "output_size": [1920, 1080],
        "tomes": [{"name": t, **json.loads(json.dumps(TOME_DEFAULTS))} for t in tomes],
        "units": [{"name": u, **json.loads(json.dumps(UNIT_DEFAULTS))} for u in units],
    }
    PROJECTS.mkdir(exist_ok=True)
    path = PROJECTS / f"{name}.json"
    if path.exists():
        raise SystemExit(f"{path} already exists - edit it, or delete it to start over.")
    path.write_text(json.dumps(cfg, indent=2))
    return path, tomes, units


def load(name):
    path = PROJECTS / f"{name}.json"
    if not path.exists():
        known = ", ".join(p.stem for p in PROJECTS.glob("*.json")) or "none yet"
        raise SystemExit(f"No project '{name}' (known: {known}). Create one with: moddocs.py init <mod folder>")
    cfg = json.loads(path.read_text())
    cfg["name"] = name
    cfg["tomes"] = [{**TOME_DEFAULTS, **t} for t in cfg["tomes"]]
    cfg["units"] = [{**UNIT_DEFAULTS, **u} for u in cfg.get("units", [])]
    return cfg


def pick(cfg, tomes, units):
    """(tomes, units) from the config, filtered by --tome / --unit (partial names).
    Naming only one kind leaves the other out; naming neither means everything."""
    def select(items, wanted, kind):
        out = [x for x in items if any(w.lower() in x["name"].lower() for w in wanted)]
        if not out:
            raise SystemExit(f"No {kind} matching {wanted}. Known: {[x['name'] for x in items]}")
        return out
    if not tomes and not units:
        return cfg["tomes"], cfg["units"]
    return (select(cfg["tomes"], tomes, "tome") if tomes else [],
            select(cfg["units"], units, "unit") if units else [])


def final_dir(cfg):
    """Where the finished images and descriptions go: output/<project>/."""
    path = OUTPUT / cfg["name"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def tome_dir(cfg, tome):
    """Working files for one tome (page shot, tooltip crops, manifest)."""
    return OUTPUT / cfg["name"] / "_captures" / slug(tome["name"])


def unit_dir(cfg, unit):
    """Working files for one unit."""
    return OUTPUT / cfg["name"] / "_captures" / ("unit_" + slug(unit["name"]))


def file_name(text):
    """Windows-safe file name part."""
    return re.sub(r'[<>:"/\\|?*]', "", text).strip()
