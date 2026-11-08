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
UNIT_PANEL_W = 392  # unit pages add a parchment strip (and its shadow) along the panel's edge


def build_plate(frame, scale=1.0, small_boxes=(), remove_content=False, panel_w=PANEL_W, no_source=()):
    """frame: PIL RGB screenshot. small_boxes: extra bits of UI (x0, y0, x1, y1)
    such as the FPS counter, given a plain fill. remove_content: also remove the
    page itself (book, scroll, text) for a plain background. panel_w: width of
    the left panel at 100% UI scale (UNIT_PANEL_W on unit pages). no_source:
    boxes never to copy background from (e.g. a unit's stat card)."""
    img = np.asarray(frame).astype(np.float32)
    h, w = img.shape[:2]
    s = scale
    ui = np.ones((h, w), np.uint8)
    ui[:, :int(panel_w * s)] = 0
    ui[h - int(ORNAMENT_H * s):, :int((ORNAMENT_W + panel_w - PANEL_W) * s)] = 0
    ui[:int(TABS_H * s), :int(TABS_W * s)] = 0
    small = np.ones((h, w), np.uint8)
    for x0, y0, x1, y1 in small_boxes:
        small[max(int(y0), 0):int(y1), max(int(x0), 0):int(x1)] = 0
    source = ui & small
    for x0, y0, x1, y1 in no_source:
        source[max(int(y0), 0):int(y1), max(int(x0), 0):int(x1)] = 0

    img = _mirror_fill(img, ui, source, int(panel_w * s), int(TABS_H * s))
    img = _relight(img, ui & small)
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


def _mirror_fill(img, known, clean, panel_x, tabs_y, fade=0.5):
    """Replace the removed UI (known == 0) with real starfield, Poisson-blended
    so it meets the background without seams.

    Removed pixels take the plain starfield from the flipped opposite side of
    the screen. Where that side isn't plain (a unit's stat card), they take the
    starfield reflected across the panel's edge instead - near the edge only,
    so the clouds continue across the seam - fading out (over `fade` x the
    panel width) into a soft fill from the surrounding clouds, so no obvious
    mirror image shows. `clean`: pixels allowed as a source.
    """
    h, w = known.shape
    hole = (1 - known).astype(bool)
    plain = clean.astype(bool) & ~_content_mask(img).astype(bool)
    plain = cv2.erode(plain.astype(np.uint8), np.ones((15, 15), np.uint8)).astype(bool)

    # The flipped screen, with its own non-plain bits filled from its clouds.
    far_ok = plain[:, ::-1]
    src = _fill(np.ascontiguousarray(img[:, ::-1]), far_ok.astype(np.uint8)).astype(np.float32)

    # Where the flipped side is unusable over a wide area (not just a small box
    # such as the Initial Bonus), reflect across the panel's right edge and the
    # tab row's bottom edge instead, weighted by closeness to that edge.
    lacking = 1 - cv2.GaussianBlur(far_ok.astype(np.float32), (0, 0), 60)
    weight = np.zeros((h, w), np.float32)
    near = src.copy()
    if panel_x:
        # Mirror about lines a little past the edges: the content mask's
        # dilation marks the strip right beside the UI as not plain.
        edge = panel_x + 32
        cols = np.clip(2 * edge - 1 - np.arange(w), 0, w - 1)
        ramp = np.clip(1 - (panel_x - np.arange(w)) / (fade * panel_x), 0, 1) * (np.arange(w) < panel_x)
        ok = hole & plain[:, cols] & ~far_ok
        near = np.where(ok[..., None], img[:, cols], near)
        weight = np.maximum(weight, ok * ramp[None, :])
    if tabs_y:
        rows = np.clip(2 * (tabs_y + 32) - 1 - np.arange(h), 0, h - 1)
        ok = hole & plain[rows, :] & ~far_ok & (weight == 0)
        near = np.where(ok[..., None], img[rows, :], near)
        weight = np.maximum(weight, ok * (np.arange(h) < tabs_y)[:, None])
    weight = cv2.GaussianBlur(weight * lacking ** 2, (0, 0), 30)[..., None]
    src = near * weight + src * (1 - weight)

    mask = cv2.dilate(hole.astype(np.uint8), np.ones((9, 9), np.uint8))  # take the seam itself too
    dst = np.where(hole[..., None], src, img)
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


def _relight(img, known, sigma=24):
    """Inside the filled-in areas (known == 0) keep the fine detail (stars,
    wisps) but take the broad nebula colour from the real surroundings, so no
    patch or step shows where different fill sources meet."""
    detail = img - cv2.GaussianBlur(img, (0, 0), sigma)
    relit = _smooth_fill(img, known) + detail
    inside = cv2.GaussianBlur(cv2.erode(1 - known, np.ones((9, 9), np.uint8)).astype(np.float32), (0, 0), 8)[..., None]
    return img * (1 - inside) + relit * inside


def _smooth_fill(img, known, f=16):
    """The nebula colours of the known area smoothly continued into the rest:
    inpaint a heavily downscaled copy, scale back up, blur."""
    h, w = img.shape[:2]
    small = cv2.resize(img, (w // f, h // f), interpolation=cv2.INTER_AREA)
    small_unknown = (cv2.resize(1 - known, (w // f, h // f), interpolation=cv2.INTER_AREA) > 0).astype(np.uint8)
    small = cv2.inpaint(np.clip(small, 0, 255).astype(np.uint8), small_unknown, 6, cv2.INPAINT_TELEA)
    return cv2.GaussianBlur(cv2.resize(small.astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC), (0, 0), 24)


def _fill(img, known):
    """Fill pixels where known == 0 from the surrounding background."""
    h, w = img.shape[:2]
    # (a) Smooth nebula continued from the surroundings.
    smooth = _smooth_fill(img, known)

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
