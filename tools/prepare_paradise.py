"""Prepare the reference explicitly authorized beach photo and motion entirely offline.

The source stays untouched and outside the repository. Only a clean crop is
packaged, with no phone/social UI, metadata or dependency on Downloads at runtime.
Pillow and the standard library are the only requirements; no network is used.
"""

import argparse
import math
from pathlib import Path

from PIL import Image, ImageOps


PHOTO_SIZE = (320, 240)
SURF_BOX = (42, 160, 184, 236)
PALM_BOX = (54, 30, 130, 58)
CROP = (0, 480, 596, 927)
# Approximate wet edge of this approved crop, in native screen coordinates.
# Only the wet bank and water move; the dry beach remains still.
SHORE = ((160, 123), (170, 108), (180, 104), (190, 94),
         (200, 78), (210, 72), (220, 78), (236, 77))


def landscape(source, crop):
    """A clean 4:3 crop fills the board without stretching the photograph."""
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        left, top, right, bottom = crop
        if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
            raise ValueError("Crop must be entirely inside the source photograph")
        photo = image.crop(crop).convert("RGB").resize(
            PHOTO_SIZE, Image.Resampling.LANCZOS
        )
    # A fresh image discards source metadata. The photo continues behind both
    # translucent instruments; there is no matte, blurred extension or side panel.
    result = Image.new("RGB", PHOTO_SIZE)
    result.paste(photo, (0, 0))
    return result


def sample(pixels, x, y):
    """Subpixel sampling of the actual photo, rather than drawn wave shapes."""
    x, y = max(0, min(319, x)), max(0, min(239, y))
    ix, iy = math.floor(x), math.floor(y)
    tx, ty = x - ix, y - iy
    a, b = pixels[ix, iy], pixels[min(319, ix + 1), iy]
    c, d = pixels[ix, min(239, iy + 1)], pixels[min(319, ix + 1), min(239, iy + 1)]
    return tuple(
        (a[k] * (1 - tx) + b[k] * tx) * (1 - ty)
        + (c[k] * (1 - tx) + d[k] * tx) * ty
        for k in range(3)
    )


def wet_edge(y):
    for (y0, x0), (y1, x1) in zip(SHORE, SHORE[1:]):
        if y <= y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    return SHORE[-1][1]


def motion(image):
    """A continuous advancing surf, made from the real photographic foam.

    Pose zero is completely transparent: it preserves every native photo pixel.
    The incoming foam reaches about 25 pixels onto the sand. The wet mask follows
    the advancing edge; attenuating at the original edge hid the previous wave.
    The board adds intermediate positions and reverses without accumulating drift.
    Tapering avoids rectangular seams, while the far dry sand stays unchanged.
    Two disjoint boxes use less memory than the previous three narrow regions.
    """
    pixels = image.load()
    atlas = Image.new("RGBA", (71, 208))
    cursor = 0
    for kind, box in (("surf", SURF_BOX), ("palm", PALM_BOX)):
        left, top, right, bottom = box
        w, h = (right - left) // 2, (bottom - top) // 2
        for phase in (0, 1 / 3, 2 / 3, 1):
            frame = Image.new("RGBA", (w, h))
            if phase:
                values = []
                for yy in range(h):
                    for xx in range(w):
                        x, y = left + 2 * xx + 0.5, top + 2 * yy + 0.5
                        edge = min(1, (x - left) / 6, (right - x) / 8)
                        edge *= min(1, (y - top) / 12, (bottom - y) / 6)
                        wet = 1
                        if kind == "surf":
                            depth = (y - top) / (bottom - top)
                            dx = phase * edge * (
                                12 + 16 * depth + 1.2 * math.sin(x / 16 + y / 11)
                            )
                            dy = phase * edge * (-1.3 + 0.9 * math.sin(x / 20 + y / 10))
                            wet = max(0, min(1, (x + dx - wet_edge(y) + 3) / 6))
                            wet = wet * wet * (3 - 2 * wet)
                        else:
                            dx = phase * edge * 1.8
                            dy = phase * edge * 0.65 * math.sin(x / 24)
                        base = [pixels[left + 2 * xx + ox, top + 2 * yy + oy]
                                for oy in (0, 1) for ox in (0, 1)]
                        old = tuple(sum(p[k] for p in base) / 4 for k in range(3))
                        if kind == "palm" and not (old[1] > old[0] and old[1] > old[2]):
                            values.append((0, 0, 0, 0))
                            continue
                        warped = [sample(pixels, left + 2 * xx + ox + dx,
                                         top + 2 * yy + oy + dy)
                                  for oy in (0, 1) for ox in (0, 1)]
                        new = tuple(round(old[k] * (1 - wet) + sum(p[k] for p in warped) / 4 * wet) for k in range(3))
                        changed = max(abs(new[k] - old[k]) for k in range(3)) >= 4
                        values.append((*new, 255) if changed else (0, 0, 0, 0))
                frame.putdata(values)
            atlas.paste(frame, (0, cursor))
            cursor += h
    assert cursor == atlas.height
    return atlas


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True, help="Authorized local beach image")
    parser.add_argument("--crop", type=int, nargs=4, default=CROP, metavar=("LEFT", "TOP", "RIGHT", "BOTTOM"))
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "token_tv" / "assets")
    args = parser.parse_args()
    if args.source.resolve() in {
        (args.out / name).resolve()
        for name in ("paradise-landscape.png", "paradise-motion.png")
    }:
        raise ValueError("Output must not overwrite the source photograph")
    background = landscape(args.source, tuple(args.crop))
    atlas = motion(background)
    args.out.mkdir(parents=True, exist_ok=True)
    background.save(args.out / "paradise-landscape.png")
    atlas.save(args.out / "paradise-motion.png")
    print("Photo prepared locally: clean 320x240 background and 71x208 advancing surf atlas; original unchanged.")


if __name__ == "__main__":
    main()
