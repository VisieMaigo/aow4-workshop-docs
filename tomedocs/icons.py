"""Match tooltips to the mod's own icon files.

File names are internal (UnitEnchantment_FrigidFocus) and often differ from the
in-game names, so matching is:
  1. by picture: the icon snapshot taken in game is compared with every file at
     several sizes (the picture the game shows wins, as folders can hold older,
     unused icons with similar names), else
  2. by name, for text links that have no icon in game: the name appears in the
     file name.
Set "icons": {"Skill name": "file.png"} in the project file to override.
"""
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from .locate import norm

MIN_SCORE = 0.6


def load_icons(folder):
    icons = {}
    if folder and Path(folder).is_dir():
        for f in sorted(Path(folder).glob("*.png")):
            img = Image.open(f)
            if max(img.size) <= 512:  # skip textures
                icons[f.name] = img.convert("RGBA")
    return icons


def _on_black(img):
    bg = Image.new("RGBA", img.size, (0, 0, 0, 255))
    return cv2.cvtColor(np.asarray(Image.alpha_composite(bg, img).convert("RGB")), cv2.COLOR_RGB2BGR)


def visual_match(snapshot, icons):
    """Best icon for an in-game snapshot centred on the icon: (file, score)."""
    snap = cv2.cvtColor(np.asarray(snapshot.convert("RGB")), cv2.COLOR_RGB2BGR)
    h, w = snap.shape[:2]
    r = max(h // 4, 8)
    core = snap[h // 2 - r:h // 2 + r, w // 2 - r:w // 2 + r]  # icon interior, no frame
    size_hint = h  # snapshot spans about one icon diameter
    best = (None, -1.0)
    for name, icon in icons.items():
        art = _on_black(icon)
        for f in np.arange(0.65, 1.35, 0.06):
            size = int(size_hint * f)
            if size <= core.shape[0]:
                continue
            res = cv2.matchTemplate(cv2.resize(art, (size, size), interpolation=cv2.INTER_AREA),
                                    core, cv2.TM_CCOEFF_NORMED)
            if (score := float(res.max())) > best[1]:
                best = (name, score)
    return best


def match(entry, folder, icons):
    """Icon file for a manifest tooltip entry, plus how it was found."""
    if entry.get("snapshot"):
        name, score = visual_match(Image.open(folder / entry["snapshot"]), icons)
        if score >= MIN_SCORE:
            return name, f"picture {score:.2f}"
        return None, "no matching picture"
    want = norm(entry["name"])
    hits = [f for f in icons if want in norm(Path(f).stem)]
    if hits:
        # Several files can share the name (CombatEnchantment_X, SpecialProvinceImprovement_X):
        # prefer the one whose prefix is the skill's type.
        kind = norm(entry.get("type", ""))
        return min(hits, key=lambda f: (not (kind and norm(Path(f).stem).startswith(kind)), len(f))), "name"
    return None, "no match"
