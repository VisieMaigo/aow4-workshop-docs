"""Windows built-in OCR (Windows.Media.Ocr): find text on screen and where it is."""
import asyncio

from PIL import Image
from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
from winrt.windows.media.ocr import OcrEngine
from winrt.windows.storage.streams import DataWriter

_engine = OcrEngine.try_create_from_user_profile_languages()


async def _recognize(img):
    writer = DataWriter()
    writer.write_bytes(img.convert("RGBA").tobytes())
    bmp = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.RGBA8,
                                                 img.width, img.height)
    return await _engine.recognize_async(bmp)


def read_lines(img, scale=2.0):
    """OCR an image. Returns [(text, (x0, y0, x1, y1)), ...] per line, in img coordinates.

    Game UI text is small, so the image is upscaled and processed in tiles that
    fit OcrEngine.max_image_dimension.
    """
    limit = OcrEngine.max_image_dimension
    big = img.resize((round(img.width * scale), round(img.height * scale)), Image.LANCZOS)
    tile, overlap = limit, 200
    lines = []
    for ty in range(0, big.height, tile - overlap):
        for tx in range(0, big.width, tile - overlap):
            part = big.crop((tx, ty, min(tx + tile, big.width), min(ty + tile, big.height)))
            result = asyncio.run(_recognize(part))
            for line in result.lines:
                rects = [w.bounding_rect for w in line.words]
                x0 = min(r.x for r in rects) + tx
                y0 = min(r.y for r in rects) + ty
                x1 = max(r.x + r.width for r in rects) + tx
                y1 = max(r.y + r.height for r in rects) + ty
                box = tuple(round(v / scale) for v in (x0, y0, x1, y1))
                if not any(t == line.text and _overlaps(b, box) for t, b in lines):
                    lines.append((line.text, box))
            if tx + tile >= big.width:
                break
        if ty + tile >= big.height:
            break
    return lines


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def find_text(img, query, scale=2.0):
    """Lines containing `query` (case-insensitive), best (shortest) match first."""
    q = query.lower()
    hits = [(t, b) for t, b in read_lines(img, scale) if q in t.lower()]
    return sorted(hits, key=lambda h: len(h[0]))
