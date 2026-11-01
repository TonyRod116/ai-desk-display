"""A private, stabilised beach film for newer touch boards.

The source stays on this computer. The board receives one indexed strip of
eight low-resolution frames and adds their colour changes to the sharp still.
"""

from functools import lru_cache
from pathlib import Path
import struct

from PIL import Image

TOP, ROWS = 132, 108
WIDTH, HEIGHT, FRAMES = 160, ROWS // 2, 8
STEP_MS, STEPS = 100, 64
BOAT_X, BOAT_Y, BOAT_W, BOAT_H, BOAT_FRAMES = 199, 76, 40, 56, 4
HEADER = struct.Struct('<BBHHHHH')
ART_DIRECTORY = Path.home() / '.local/share/ai-desk-display/paradise-local'


def _word(rgb):
    r, g, b = rgb[:3]
    return (r >> 3) << 11 | (g >> 2) << 5 | (b >> 3)


@lru_cache(maxsize=1)
def load():
    """Use the prepared local art only when the complete pair is valid."""
    try:
        with Image.open(ART_DIRECTORY / 'background.png') as source:
            if source.size != (320, 240):
                return None
            background = source.convert('RGB')
        with Image.open(ART_DIRECTORY / 'water.png') as source:
            if source.size != (WIDTH, HEIGHT * FRAMES) or source.mode != 'P':
                return None
            palette = source.getpalette()
            if palette is None or len(palette) < 768:
                return None
            words = tuple(_word(palette[i:i+3]) for i in range(0, 768, 3))
            frames = source.tobytes()
        boat = None
        boat_path = ART_DIRECTORY / 'boat.png'
        if boat_path.is_file():
            try:
                with Image.open(boat_path) as source:
                    palette = source.getpalette()
                    if (source.size == (BOAT_W, BOAT_H * BOAT_FRAMES) and source.mode == 'P'
                            and palette is not None and len(palette) >= 768):
                        boat = (tuple(_word(palette[i:i+3]) for i in range(0, 768, 3)), source.tobytes())
            except (OSError, ValueError, Image.DecompressionBombError):
                pass  # The sea still works if the optional boat is damaged.
        return background, words, frames, boat
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def encode(art, version=2):
    _, palette, frames = art[:3]
    boat = art[3] if version == 3 and len(art) > 3 else None
    if version not in (2, 3) or len(palette) != 256 or len(frames) != WIDTH * HEIGHT * FRAMES:
        raise ValueError('Invalid private beach animation')
    payload = (HEADER.pack(version, int(boat is not None), TOP, ROWS, STEP_MS, STEPS, 2 if version == 3 else 0)
               + struct.pack('<256H', *palette) + frames)
    if boat is not None:
        boat_palette, boat_frames = boat
        if len(boat_palette) != 256 or len(boat_frames) != BOAT_W * BOAT_H * BOAT_FRAMES:
            raise ValueError('Invalid private boat animation')
        payload += struct.pack('<256H', *boat_palette) + boat_frames
    return payload


def decode(payload):
    size = HEADER.size + 512 + WIDTH * HEIGHT * FRAMES
    if len(payload) < size:
        raise ValueError('Invalid private beach animation')
    version, flags, top, rows, ms, steps, speed = HEADER.unpack_from(payload)
    if ((version, flags, top, rows, ms, steps, speed) not in
            ((2, 0, TOP, ROWS, STEP_MS, STEPS, 0), (3, 0, TOP, ROWS, STEP_MS, STEPS, 2),
             (3, 1, TOP, ROWS, STEP_MS, STEPS, 2))):
        raise ValueError('Invalid private beach animation')
    boat_size = 512 + BOAT_W * BOAT_H * BOAT_FRAMES if flags else 0
    if len(payload) != size + boat_size:
        raise ValueError('Invalid private beach animation')
    result = {'version': version, 'palette': struct.unpack_from('<256H', payload, HEADER.size),
              'frames': payload[HEADER.size+512:size]}
    if flags:
        result['boat_palette'] = struct.unpack_from('<256H', payload, size)
        result['boat_frames'] = payload[size+512:]
    return result


def render_words(background, beach, step, boat_step=None):
    """Integer reference for the board; preserve the sharp photo's detail."""
    out = list(background)
    frames, palette = beach['frames'], beach['palette']
    stride = WIDTH * HEIGHT
    step %= STEPS
    first, mix = divmod(step, 8)
    for yy in range(HEIGHT):
        for xx in range(WIDTH):
            pos = yy * WIDTH + xx
            c0 = palette[frames[pos]]
            ca = palette[frames[first * stride + pos]]
            cb = palette[frames[((first + 1) % FRAMES) * stride + pos]]
            for ry in (0, 1):
                for rx in (0, 1):
                    at = (TOP + yy * 2 + ry) * 320 + xx * 2 + rx
                    original = background[at]
                    result = 0
                    for shift, mask in ((11, 31), (5, 63), (0, 31)):
                        a, b, base = (ca >> shift) & mask, (cb >> shift) & mask, (c0 >> shift) & mask
                        delta = (a * (8 - mix) + b * mix + 4) // 8 - base
                        # Fade into the fixed horizon without a moving seam.
                        fade = min(8, yy)
                        delta = (delta * fade // 8 if delta >= 0 else -((-delta * fade) // 8))
                        result |= max(0, min(mask, ((original >> shift) & mask) + delta)) << shift
                    out[at] = result
    if 'boat_frames' in beach:
        boat_step = (step if boat_step is None else boat_step) % STEPS
        first, mix = divmod(boat_step, 16)
        frames, palette = beach['boat_frames'], beach['boat_palette']
        stride = BOAT_W * BOAT_H
        for y in range(BOAT_H):
            for x in range(BOAT_W):
                pos = y * BOAT_W + x
                c0 = palette[frames[pos]]
                ca = palette[frames[first * stride + pos]]
                cb = palette[frames[((first + 1) % BOAT_FRAMES) * stride + pos]]
                at = (BOAT_Y + y) * 320 + BOAT_X + x
                original = background[at]
                result = 0
                for shift, mask in ((11, 31), (5, 63), (0, 31)):
                    a, b, base = (ca >> shift) & mask, (cb >> shift) & mask, (c0 >> shift) & mask
                    delta = (a * (16 - mix) + b * mix + 8) // 16 - base
                    result |= max(0, min(mask, ((original >> shift) & mask) + delta)) << shift
                out[at] = result
    return out
