"""Cut tooltips out of screenshots: compare a frame with and without the
tooltip, then snap the crop to the tooltip's own border."""
import cv2
import numpy as np

from .locate import norm
from .ocr import read_lines

DIFF_THRESHOLD = 30    # per-channel change that counts as "tooltip pixel"
MIN_TOOLTIP_AREA = 3000


def find_tooltip(base, hovered):
    """Bounding box (with a small margin) of the biggest region that changed."""
    a = np.asarray(base, dtype=np.int16)
    b = np.asarray(hovered, dtype=np.int16)
    mask = (np.abs(a - b).max(axis=2) > DIFF_THRESHOLD).astype(np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h, area = stats[i]
    if area < MIN_TOOLTIP_AREA:
        return None
    # Trim edges that are only partly changed (hover glow, animated background)...
    sub = labels[y:y + h, x:x + w] == i
    x0, x1 = _solid_span(sub.mean(axis=0))
    y0, y1 = _solid_span(sub.mean(axis=1))
    # ...but leave a margin: a border drawn over a similar colour barely "changes"
    # and would get trimmed; snap_to_border then finds the real edge.
    m = 12
    H, W = mask.shape
    return (max(int(x + x0) - m, 0), max(int(y + y0) - m, 0),
            min(int(x + x1) + m, W), min(int(y + y1) + m, H))


def _solid_span(fractions, solid=0.6):
    idx = np.flatnonzero(fractions >= solid)
    return (int(idx[0]), int(idx[-1]) + 1) if len(idx) else (0, len(fractions))


def _ridge(lum, axis):
    """Per row (axis 0) / column (axis 1): how much a thin line stands out."""
    med = np.median(lum if axis == 0 else lum.T, axis=1)
    r = np.zeros_like(med)
    r[2:-2] = med[2:-2] - (med[:-4] + med[4:]) / 2
    return r


def snap_to_border(img, search=40, strength=6):
    """Shrink a crop to the tooltip's own thin border line.

    A border is a 1-2 px line along the whole edge, so it shows up as a peak in
    the *median* row/column brightness, which text and icons can't fake. Near
    each edge the strongest such line wins.
    """
    lum = np.asarray(img.convert("L"), dtype=np.float32)
    rows, cols = _ridge(lum, 0), _ridge(lum, 1)

    def strongest(r, lo, hi):
        lo, hi = max(lo, 0), min(hi, len(r))
        if hi <= lo:
            return None
        i = lo + int(np.argmax(r[lo:hi]))
        return i if r[i] > strength else None

    box = [0, 0, img.width, img.height]
    if (t := strongest(rows, 0, search)) is not None:
        box[1] = t
    if (b := strongest(rows, img.height - search, img.height)) is not None:
        box[3] = b + 2
    if (l := strongest(cols, 0, search)) is not None:
        box[0] = l
    if (r := strongest(cols, img.width - search, img.width)) is not None:
        box[2] = r + 2
    return img.crop(box)


def cut_at_bottom_border(img, strength=30):
    """Sub-tooltips open on top of their parent, which changes slightly too, so
    the crop can run on into the parent. Cut at the sub-tooltip's own bottom
    border: the strongest full-width line below its header."""
    rows = _ridge(np.asarray(img.convert("L"), dtype=np.float32), 0)
    start = int(len(rows) * 0.35)  # skip the header separator
    if len(rows) <= start:
        return img
    y = start + int(np.argmax(rows[start:]))
    return img.crop((0, 0, img.width, y + 4)) if rows[y] >= strength else img


def _border_segments(img):
    """Thin bright horizontal and vertical lines (tooltip borders) as boxes."""
    g = np.asarray(img.convert("L"), dtype=np.float32)
    mask = ((g - cv2.GaussianBlur(g, (0, 0), 3)) > 10).astype(np.uint8)
    found = []
    for size in ((60, 1), (1, 30)):
        lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, size))
        n, _, st, _ = cv2.connectedComponentsWithStats(lines)
        found.append([(x, y, x + w, y + h) for x, y, w, h, _ in st[1:n]])
    return found


def sub_tooltip(img, title):
    """Crop a sub-tooltip out of a capture that also caught bits of its parent
    (the parent can shift when the nested tooltip opens): find the sub-tooltip's
    all-caps title and take the bordered box around it."""
    want = norm(title)
    head = next((b for t, b in read_lines(img) if want in norm(t) and t.upper() == t), None)
    if not head:
        return cut_at_bottom_border(img)
    horizontal, vertical = _border_segments(img)
    tx0, ty0, tx1, ty1 = head
    cy = (ty0 + ty1) / 2
    left = [x1 for x0, y0, x1, y1 in vertical if x1 <= tx0 and y0 <= cy <= y1]
    right = [x0 for x0, y0, x1, y1 in vertical if x0 >= tx1 and y0 <= cy <= y1]
    L = max(left) - 2 if left else 0
    R = min(right) + 2 if right else img.width
    top = [y1 for x0, y0, x1, y1 in horizontal if y1 <= ty0 and x0 <= tx0 and x1 >= tx1]
    T = max(top) - 2 if top else 0
    # The bottom border spans the whole box; the parent's lines don't line up with it.
    span = 0.05 * (R - L)
    bottom = [y0 for x0, y0, x1, y1 in horizontal if y0 > ty1 and x0 <= L + span and x1 >= R - span]
    B = max(bottom) + 2 if bottom else img.height
    return img.crop((max(L, 0), max(T, 0), min(R, img.width), min(B, img.height)))


def find_link(frame, box, link):
    """Centre of the hyperlink text `link` inside the tooltip at `box`, or None.
    Skips the all-caps title line, which usually repeats the same name."""
    x0, y0 = box[:2]
    want = norm(link)
    lines = [(text, b) for text, b in read_lines(frame.crop(box)) if text != text.upper()]
    for text, (bx0, by0, bx1, by1) in lines:
        t = norm(text)
        i = t.find(want)
        if i >= 0:
            mid = (i + len(want) / 2) / len(t)  # where in the line the link sits
            return x0 + bx0 + round((bx1 - bx0) * mid), y0 + (by0 + by1) // 2
    # A link can wrap: "...damage from Domain of" / "Endless Winter at...".
    # Hover the part at the end of the first line.
    for text, (bx0, by0, bx1, by1) in lines:
        t = norm(text)
        for n in range(len(want) - 1, 5, -1):
            if t.endswith(want[:n]):
                mid = 1 - (n / 2) / len(t)
                return x0 + bx0 + round((bx1 - bx0) * mid), y0 + (by0 + by1) // 2
    return None
