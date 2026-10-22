"""Offline photographic ocean motion for the touch board's WAVE capability.

One compact native-resolution texture travels with the page. The device samples
it continuously; foreground pixels remain exact. No video uploads or new deps.
"""

import math
import struct
from functools import lru_cache

from PIL import Image

W, H, TOP = 320, 240, 124
ROWS, STEPS, STEP_MS = H - TOP, 64, 100
SHORE = ((124, 173), (132, 158), (144, 146), (152, 126),
         (160, 123), (170, 108), (180, 104), (190, 94),
         (200, 78), (210, 72), (220, 78), (239, 77))
SIN = tuple(round(128 * math.sin(math.tau * i / 128)) for i in range(128))
HEADER = struct.Struct("<BBHHHHH")


def edge(y):
    for (y0, x0), (y1, x1) in zip(SHORE, SHORE[1:]):
        if y <= y1:
            return x0 + (x1 - x0) * (y - y0) // (y1 - y0)
    return SHORE[-1][1]


def word(rgb):
    r, g, b = rgb[:3]
    return (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)


def rgb(c):
    return ((c >> 11) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31)


def blend(bg, fg, alpha):
    return (((((bg >> 11) & 31) * (255-alpha) + ((fg >> 11) & 31) * alpha) // 255) << 11
            | ((((bg >> 5) & 63) * (255-alpha) + ((fg >> 5) & 63) * alpha) // 255) << 5
            | ((bg & 31) * (255-alpha) + (fg & 31) * alpha) // 255)


def bits(values):
    out = bytearray((len(values) + 7) // 8)
    for i, value in enumerate(values):
        if value:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


@lru_cache(maxsize=1)
def texture():
    from token_tv.board_paradise import _landscape
    photo = _landscape()
    starts = tuple(max(0, edge(TOP+y) - (10 + 36*y//(ROWS-1)) - 8) for y in range(ROWS))
    values = [photo.getpixel((x, TOP+y)) for y, start in enumerate(starts) for x in range(start, W)]
    strip = Image.new("RGB", (len(values), 1))
    strip.putdata(values)
    indexed = strip.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = indexed.getpalette()
    words = tuple(word(palette[i:i+3]) for i in range(0, 768, 3))
    return starts, words, indexed.tobytes()


def encode(image, glass_only, glass_alpha):
    """Freeze every ink pixel and antialiased panel edge, including unknown data."""
    starts, palette, indices = texture()
    crop = (0, TOP, W, H)
    bg = [word(c) for c in image.crop(crop).getdata()]
    no_ink = [word(c) for c in glass_only.crop(crop).getdata()]
    alphas = list(glass_alpha.crop(crop).getdata())
    keep = bits([a != b or alpha not in (0, 156) for a, b, alpha in zip(bg, no_ink, alphas)])
    glass = bits([alpha == 156 for alpha in alphas])
    payload = (HEADER.pack(1, 0, TOP, ROWS, STEP_MS, STEPS, word((242, 247, 226)))
               + struct.pack(f"<{ROWS}H", *starts) + struct.pack("<256H", *palette)
               + indices + keep + glass)
    if len(payload) > 40000:
        raise ValueError("Photographic ocean exceeds the board's trailer budget")
    return payload


def decode(payload):
    if len(payload) < HEADER.size:
        raise ValueError("Truncated WAVE header")
    version, flags, top, rows, ms, steps, glass_colour = HEADER.unpack_from(payload)
    if (version, flags, top, rows, ms, steps) != (1, 0, TOP, ROWS, STEP_MS, STEPS):
        raise ValueError("Unsupported photographic ocean")
    at = HEADER.size
    starts = struct.unpack_from(f"<{ROWS}H", payload, at)
    if any(x >= W for x in starts):
        raise ValueError("Invalid ocean row")
    at += ROWS*2
    palette = struct.unpack_from("<256H", payload, at)
    at += 512
    size = sum(W-x for x in starts)
    mask_size = W*ROWS//8
    if len(payload) != at + size + 2*mask_size or len(payload) > 40000:
        raise ValueError("Invalid ocean length")
    offsets, offset = [], 0
    for start in starts:
        offsets.append(offset)
        offset += W-start
    return dict(starts=starts, offsets=offsets, palette=palette, indices=payload[at:at+size],
                keep=payload[at+size:at+size+mask_size], glass=payload[at+size+mask_size:],
                glass_colour=glass_colour)


def sample(ocean, xq, yq):
    yq = max(0, min((ROWS-1)*256, yq))
    yy, fy = divmod(yq, 256)
    y1 = min(ROWS-1, yy+1)
    xq = max(max(ocean['starts'][yy], ocean['starts'][y1])*256, min(319*256, xq))
    xx, fx = divmod(xq, 256)
    x1 = min(319, xx+1)
    def pixel(x, y):
        return ocean['palette'][ocean['indices'][ocean['offsets'][y]+x-ocean['starts'][y]]]
    a, b, c, d = pixel(xx, yy), pixel(x1, yy), pixel(xx, y1), pixel(x1, y1)
    out = 0
    for shift, mask in ((11, 31), (5, 63), (0, 31)):
        ab = ((a >> shift)&mask)*(256-fx) + ((b >> shift)&mask)*fx
        cd = ((c >> shift)&mask)*(256-fx) + ((d >> shift)&mask)*fx
        out |= ((ab*(256-fy)+cd*fy+32768)//65536) << shift
    return out


def render_words(background, ocean, step):
    """Integer reference for the native engine, not a runtime PC animation loop."""
    out = list(background)
    step %= STEPS
    if step == 0:
        return out
    cosine = SIN[(step*2+32)&127]
    for yy in range(ROWS):
        y = TOP+yy
        shore = edge(y)
        tide = (128-cosine)*(10+36*yy//(ROWS-1))
        carrier = round(math.sqrt(yy/(ROWS-1))*320)
        ripple = 80 + 720*yy//(ROWS-1)
        for x in range(max(0, shore-54), W):
            idx = yy*W+x
            if ocean['keep'][idx//8] & (1 << (idx%8)):
                continue
            distance = max(0, x-shore)
            near = max(64, 256-distance*3)
            k = (carrier+x//18)&127
            dx = tide*near//256 + ripple*(SIN[(k-step*2)&127]-SIN[k])//128
            dy = ripple*(SIN[(k-step*2+32)&127]-SIN[(k+32)&127])//160
            wet = max(0, min(255, ((x-shore)*256+dx+768)*255//1536))
            wet = wet*wet*(765-2*wet)//65025
            if not wet:
                continue
            c = sample(ocean, x*256+dx, yy*256+dy)
            if ocean['glass'][idx//8] & (1 << (idx%8)):
                c = blend(c, ocean['glass_colour'], 156)
            at = y*W+x
            out[at] = blend(background[at], c, wet)
    return out
