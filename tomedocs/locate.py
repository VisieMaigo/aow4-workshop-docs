"""Find things on screen: buttons (image templates), text (OCR), and the
skill icons on a tome page. Everything is scale-aware, so different
resolutions and UI scale settings work."""
import difflib
import re
from pathlib import Path

import cv2
import numpy as np

from .ocr import read_lines

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
# Templates were cut from a 1920x1080 screen at 100% UI scale.


def _bgr(img):
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def find_template(img, name, region=None, scales=None, threshold=0.75):
    """Best match of templates/<name>.png: (cx, cy, scale, score) or None.

    region: (x0, y0, x1, y1) to search in; scales: candidate UI scales.
    """
    tpl = cv2.imread(str(TEMPLATES / f"{name}.png"))
    scr = _bgr(img)
    ox = oy = 0
    if region:
        x0, y0, x1, y1 = (int(v) for v in region)
        scr, ox, oy = scr[y0:y1, x0:x1], x0, y0
    best = None
    for s in scales or np.arange(0.6, 2.05, 0.05):
        t = cv2.resize(tpl, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
        if t.shape[0] > scr.shape[0] or t.shape[1] > scr.shape[1]:
            continue
        res = cv2.matchTemplate(scr, t, cv2.TM_CCOEFF_NORMED)
        _, score, _, (x, y) = cv2.minMaxLoc(res)
        if best is None or score > best[3]:
            best = (ox + x + t.shape[1] // 2, oy + y + t.shape[0] // 2, float(s), float(score))
    return best if best and best[3] >= threshold else None


def norm(text):
    return re.sub(r"[^a-z0-9]", "", text.lower())


def find_text(lines, query, region=None):
    """OCR lines containing `query` (case/punctuation-insensitive), best first."""
    q = norm(query)
    hits = []
    for text, box in lines:
        if region and not (region[0] <= box[0] and box[2] <= region[2] and region[1] <= box[1] and box[3] <= region[3]):
            continue
        if q and q in norm(text):
            hits.append((text, box))
    return sorted(hits, key=lambda h: len(h[0]))


def match_name(text, names, cutoff=0.86):
    """The known name this OCR'd text is (allowing small OCR errors), or None."""
    n = norm(text)
    if len(n) < 3:
        return None
    table = {norm(k): k for k in names}
    if n in table:
        return table[n]
    close = difflib.get_close_matches(n, list(table), n=1, cutoff=cutoff)
    return table[close[0]] if close else None


def icon_above(img, box, scale):
    """Centre of the round skill icon just above a label, or None (for text links)."""
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    r_min, r_max = int(20 * scale), int(42 * scale)
    top = max(int(y0 - 130 * scale), 0)
    left = max(int(cx - 90 * scale), 0)
    crop = cv2.cvtColor(_bgr(img)[top:y0, left:int(cx + 90 * scale)], cv2.COLOR_BGR2GRAY)
    if crop.size == 0:
        return None
    circles = cv2.HoughCircles(cv2.medianBlur(crop, 5), cv2.HOUGH_GRADIENT, dp=1.2, minDist=40 * scale,
                               param1=80, param2=50, minRadius=r_min, maxRadius=r_max)
    if circles is None:
        return None
    # The icon sits centred over its label: take the circle nearest that spot.
    best = min(circles[0], key=lambda c: abs(c[0] + left - cx) + 0.5 * abs(c[1] + top - (y0 - 55 * scale)))
    x, y = int(best[0] + left), int(best[1] + top)
    return (x, y) if abs(x - cx) < 40 * scale else None


def hover_targets(img, names, exclude=(), scale=1.0, lines=None):
    """Things to hover on a tome page: every label that is one of the mod's own
    names (skills on the scroll, improvements in the Initial Bonus box...).

    Returns [(name, (x, y), kind)] where kind is "icon" or "link".
    """
    lines = sorted(lines if lines is not None else read_lines(img), key=lambda l: (l[1][1], l[1][0]))
    excluded = {norm(e) for e in exclude}
    found, seen = [], set()
    for i, (text, box) in enumerate(lines):
        name = match_name(text, names)
        if not name:
            # Long skill labels wrap: "Domain of Endless" / "Winter" centred below.
            below = _wrapped_line(lines, i, scale)
            name = below and match_name(f"{text} {below}", names)
        if not name or norm(name) in excluded or name in seen:
            continue
        seen.add(name)
        icon = icon_above(img, box, scale)
        if icon:
            found.append((name, icon, "icon"))
        else:
            found.append((name, ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), "link"))
    return found


def _wrapped_line(lines, i, scale):
    """Text of the line directly under lines[i] and centred with it, if any."""
    _, (x0, y0, x1, y1) = lines[i]
    cx, h = (x0 + x1) / 2, y1 - y0
    for text, (bx0, by0, bx1, by1) in lines[i + 1:]:
        if by0 - y1 > 2 * h:
            break
        if by0 > y1 and abs((bx0 + bx1) / 2 - cx) < 30 * scale:
            return text
    return None


def unit_abilities(img, names, scale=1.0, lines=None):
    """Abilities listed on a unit page's card (the panel on the right).

    Returns [(name, (x, y), is_attack, is_mod)] in card order. Ability names sit
    in one column under the stats; an ability with damage numbers to its right
    is an attack; is_mod = the name is one of the mod's own (.po) names.
    """
    w = img.width
    lines = sorted(lines if lines is not None else read_lines(img), key=lambda l: (l[1][1], l[1][0]))
    card = [(t, b) for t, b in lines if b[0] > 0.74 * w]
    tier = next((b for t, b in card if re.search(r"\bTier\b", t)), None)
    if not tier:
        return []
    below = [(t, b) for t, b in card if b[1] > tier[3] + 60 * scale and re.search(r"[A-Za-z]{3}", t)]
    if not below:
        return []
    # The ability column: the left edge most of these lines share.
    lefts = sorted(b[0] for _, b in below)
    column = max(lefts, key=lambda x: sum(abs(x - o) <= 12 * scale for o in lefts))
    rows = []
    for text, b in below:
        if abs(b[0] - column) > 12 * scale:
            continue
        if rows and b[1] - rows[-1][1][3] < 12 * scale:  # wrapped name: "Status Effect Immunity:" / "Chilled"
            t0, b0 = rows[-1]
            rows[-1] = (f"{t0} {text}", (b0[0], b0[1], max(b0[2], b[2]), b[3]))
        else:
            rows.append((text, b))
    found = []
    for text, (x0, y0, x1, y1) in rows:
        cy = (y0 + y1) / 2
        attack = any(re.search(r"\d", t) and b[0] > x1 + 20 * scale and abs((b[1] + b[3]) / 2 - cy) < 12 * scale
                     for t, b in card)
        name = match_name(text, names)
        found.append((name or text.strip(), ((x0 + x1) // 2, int(cy)), attack, bool(name)))
    return found
