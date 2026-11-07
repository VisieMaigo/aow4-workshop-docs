"""Build a clean full-size background plate from an encyclopedia screenshot.

Removes the encyclopedia UI (left panel, tab row, FPS counter) and, for the
tooltips image, the page content too. Removed UI is replaced by a mirrored copy
of the opposite side of the screen, Poisson-blended so no seams show; anything
left is filled with (a) the nebula colours smoothly continued from the
surroundings and (b) real stars copied from empty areas.
"""
import cv2
import numpy as np

# Encyclopedia UI to remove, in pixels at 1920x1080 / 100% UI scale (multiplied
# by the measured UI scale): the left list panel incl. its edge line, the
# ornament at its foot, and the tab row with the dark vines beside it.
PANEL_W, ORNAMENT_W, ORNAMENT_H, TABS_W, TABS_H = 346, 362, 40, 560, 72


def build_plate(frame, scale=1.0, small_boxes=(), remove_content=False):
    """frame: PIL RGB screenshot. small_boxes: extra bits of UI (x0, y0, x1, y1)
    such as the FPS counter, given a plain fill. remove_content: also remove the
    page itself (book, scroll, text) for a plain background."""
    img = np.asarray(frame).astype(np.float32)
    h, w = img.shape[:2]
    s = scale
    ui = np.ones((h, w), np.uint8)
    ui[:, :int(PANEL_W * s)] = 0
    ui[h - int(ORNAMENT_H * s):, :int(ORNAMENT_W * s)] = 0
    ui[:int(TABS_H * s), :int(TABS_W * s)] = 0
    small = np.ones((h, w), np.uint8)
    for x0, y0, x1, y1 in small_boxes:
        small[max(int(y0), 0):int(y1), max(int(x0), 0):int(x1)] = 0

    img = _mirror_fill(img, ui, ui & small)
    known = small
    if remove_content:
        x0, y0, x1, y1 = _content_box(img, ui & small)
        pad = int(60 * s)  # also removes the faint rune circle around the book
        known = known.copy()
        known[max(y0 - pad, 0):y1 + pad, max(x0 - pad, 0):x1 + pad] = 0
    return _fill(img, known)


def _content_box(img, usable):
    """Bounding box of the page content: the big bright/busy blobs."""
    mask = _content_mask(img) & usable
    n, _, stats, _ = cv2.connectedComponentsWithStats(mask)
    big = [stats[i] for i in range(1, n) if stats[i][cv2.CC_STAT_AREA] > 0.01 * mask.size]
    if not big:
        return 0, 0, 0, 0
    x0 = min(b[0] for b in big)
    y0 = min(b[1] for b in big)
    x1 = max(b[0] + b[2] for b in big)
    y1 = max(b[1] + b[3] for b in big)
    return x0, y0, x1, y1


def _mirror_fill(img, known, clean):
    """Replace the removed UI (known == 0) with the flipped opposite side of the
    screen, Poisson-blended so it meets the real background without seams.

    Where the flipped side has page content of its own (e.g. the Initial Bonus
    box), that bit is first filled from the surrounding flipped clouds.
    `clean`: pixels that are plain background (no UI at all) usable as source.
    """
    flipped = np.ascontiguousarray(img[:, ::-1])
    plain = (clean.astype(bool) & ~_content_mask(img).astype(bool))[:, ::-1]
    src = _fill(flipped, cv2.erode(plain.astype(np.uint8), np.ones((15, 15), np.uint8))).astype(np.float32)

    hole = (1 - known).astype(np.uint8)
    mask = cv2.dilate(hole, np.ones((9, 9), np.uint8))  # take the seam itself too
    dst = np.where(hole[..., None] > 0, src, img)
    # Pad so the mask never touches the image border (seamlessClone needs that);
    # the padding mirrors dst, so the outer edge adds no colour correction.
    p = 32
    src_p = cv2.copyMakeBorder(np.clip(src, 0, 255).astype(np.uint8), p, p, p, p, cv2.BORDER_REFLECT)
    dst_p = cv2.copyMakeBorder(np.clip(dst, 0, 255).astype(np.uint8), p, p, p, p, cv2.BORDER_REFLECT)
    mask_p = cv2.copyMakeBorder(mask * 255, p, p, p, p, cv2.BORDER_CONSTANT, value=0)
    ys, xs = np.nonzero(mask_p)
    centre = ((int(xs.min()) + int(xs.max()) + 1) // 2, (int(ys.min()) + int(ys.max()) + 1) // 2)
    out = cv2.seamlessClone(src_p, dst_p, mask_p, centre, cv2.NORMAL_CLONE)
    return out[p:-p, p:-p].astype(np.float32)


def _fill(img, known):
    """Fill pixels where known == 0 from the surrounding background."""
    h, w = img.shape[:2]
    # (a) Smooth nebula: inpaint a heavily downscaled copy, scale back up, blur.
    f = 16
    small = cv2.resize(img, (w // f, h // f), interpolation=cv2.INTER_AREA)
    small_unknown = (cv2.resize(1 - known, (w // f, h // f), interpolation=cv2.INTER_AREA) > 0).astype(np.uint8)
    small = cv2.inpaint(np.clip(small, 0, 255).astype(np.uint8), small_unknown, 6, cv2.INPAINT_TELEA)
    smooth = cv2.GaussianBlur(cv2.resize(small.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC), (0, 0), 24)

    # (b) Stars: the bright fine detail of the empty background, tiled over the gaps.
    detail = np.clip(img - cv2.GaussianBlur(img, (0, 0), 6), 0, None)
    stars = _tile_from_known(detail, known)

    filled = smooth + stars
    # Shrink the kept area before softening it, so nothing of the removed UI or
    # original overview bleeds back in through the soft edge.
    core = cv2.erode(known, np.ones((61, 61), np.uint8))
    blend = (cv2.GaussianBlur(core.astype(np.float32), (0, 0), 20) * known)[..., None]  # 0 inside removed areas
    plate = img * blend + filled * (1 - blend)
    return np.clip(plate, 0, 255).astype(np.uint8)


def _content_mask(img):
    """Page content (text, scroll, artwork) vs plain nebula: bright or busy areas."""
    lum = img.mean(axis=2)
    bright = cv2.GaussianBlur(lum, (0, 0), 4) > 85
    detail = np.abs(lum - cv2.GaussianBlur(lum, (0, 0), 3))
    busy = cv2.GaussianBlur(detail, (0, 0), 8) > 6
    return cv2.dilate((bright | busy).astype(np.uint8), np.ones((41, 41), np.uint8))


def _tile_from_known(detail, known, size=128, seed=1):
    """Cover the image with random fully-known detail patches (random flips)."""
    rng = np.random.default_rng(seed)
    h, w = known.shape
    ok = cv2.erode(known, np.ones((size, size), np.uint8), anchor=(0, 0))  # patch fits in known area
    # Only copy from the emptiest starfield: patches with little fine detail, so no
    # text, scroll edges or artwork from the page get copied around.
    energy = cv2.boxFilter(detail.mean(axis=2), -1, (size, size), anchor=(0, 0), normalize=True)
    ok = ok[: h - size, : w - size].astype(bool)
    if ok.any():
        ok &= energy[: h - size, : w - size] <= np.percentile(energy[: h - size, : w - size][ok], 15)
    ys, xs = np.nonzero(ok)
    out = np.zeros_like(detail)
    if not len(ys):
        return out
    for ty in range(0, h, size):
        for tx in range(0, w, size):
            i = rng.integers(len(ys))
            patch = detail[ys[i]:ys[i] + size, xs[i]:xs[i] + size]
            if rng.random() < 0.5:
                patch = patch[:, ::-1]
            if rng.random() < 0.5:
                patch = patch[::-1]
            ph, pw = min(size, h - ty), min(size, w - tx)
            out[ty:ty + ph, tx:tx + pw] = patch[:ph, :pw]
    return out
