"""The ANIM trailer of a board page: a clean background plus things the board moves over it.

A page may end with b'ANIM' + payload length (u32 LE) + payload (see firmware/board/src/main.cpp for the
reader). The board draws the background once, then moves small sprites over it (each sprite pixel is shown as
a 2x2 block), twinkles a few stars and sends a shooting star across. What a sprite uncovers is read back from
the stored page itself, so nothing is written to the board's flash while it animates.

Payload, little endian:
    u8 sprites, u8 stars, u8 meteor, u8 0
    meteor (if 1): i16 x0 y0 x1 y1, u16 period_ms, u16 head, u16 tail, u8 length, u8 speed
    stars:   i16 x, i16 y, u16 base, u16 bright, u16 dim
    sprites: u16 w, u16 h, i16 x, i16 y, u8 frames, u8 steps, u16 step_ms,
             steps * (u8 frame, i8 dx, i8 dy), frames * w * h RGB565 (0xF81F = transparent)
"""
import struct

KEY = 0xF81F
MAX_PAYLOAD = 80000
MAX_FRAMES = 8  # firmware 14+; older boards receive a static Token Run page
MAX_SPRITES, MAX_STARS, MAX_STEPS = 4, 48, 32


def rgb565(rgb):
    r, g, b = rgb[:3]
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def sprite_words(image):
    """RGB565 words of an RGBA image; pixels that are mostly transparent become the key colour."""
    image = image.convert('RGBA')
    words = []
    for r, g, b, a in zip(*(image.tobytes()[i::4] for i in range(4))):
        word = rgb565((r, g, b)) if a >= 128 else KEY
        words.append(word if word != KEY or a < 128 else KEY ^ 1)   # a real pixel must never read as transparent
    return words


def encode(sprites=(), stars=(), meteor=None):
    """`sprites`: dicts x, y (final px), frames (RGBA images of one size), script [(frame, dx, dy)], step_ms.
    `stars`: (x, y, base, bright, dim) in RGB565. `meteor`: dict x0 y0 x1 y1 period_ms head tail length speed."""
    sprites, stars = list(sprites), list(stars)
    if len(sprites) > MAX_SPRITES or len(stars) > MAX_STARS:
        raise ValueError('Too many animated things for one page')
    out = bytearray(struct.pack('<BBBB', len(sprites), len(stars), 1 if meteor else 0, 0))
    if meteor:
        out += struct.pack('<hhhhHHHBB', meteor['x0'], meteor['y0'], meteor['x1'], meteor['y1'],
                           meteor['period_ms'], meteor['head'], meteor['tail'], meteor['length'], meteor['speed'])
    for star in stars:
        out += struct.pack('<hhHHH', *star)
    for sprite in sprites:
        frames = sprite['frames']
        w, h = frames[0].size
        script = sprite['script']
        if not 1 <= len(frames) <= MAX_FRAMES or not 1 <= len(script) <= MAX_STEPS or any(f.size != (w, h) for f in frames):
            raise ValueError('Unexpected sprite')
        if any(not 0 <= frame < len(frames) or not -128 <= dx <= 127 or not -128 <= dy <= 127
               for frame, dx, dy in script):
            raise ValueError('Unexpected sprite step')
        out += struct.pack('<HHhhBBH', w, h, sprite['x'], sprite['y'], len(frames), len(script), sprite['step_ms'])
        for frame, dx, dy in script:
            out += struct.pack('<Bbb', frame, dx, dy)
        for image in frames:
            out += struct.pack(f'<{w * h}H', *sprite_words(image))
    if len(out) > MAX_PAYLOAD:
        raise ValueError('Animation too large for the board')
    return bytes(out)


def trailer(payload):
    return b'ANIM' + struct.pack('<I', len(payload)) + payload


def decode(payload):
    """The inverse of encode(): a dict with sprites (frames as RGB565 word lists), stars and meteor."""
    sprites_n, stars_n, has_meteor, _ = struct.unpack_from('<BBBB', payload, 0)
    at = 4
    meteor = None
    if has_meteor:
        keys = ('x0', 'y0', 'x1', 'y1', 'period_ms', 'head', 'tail', 'length', 'speed')
        meteor = dict(zip(keys, struct.unpack_from('<hhhhHHHBB', payload, at)))
        at += 16
    stars = []
    for _ in range(stars_n):
        stars.append(struct.unpack_from('<hhHHH', payload, at))
        at += 10
    sprites = []
    for _ in range(sprites_n):
        w, h, x, y, frames, steps, step_ms = struct.unpack_from('<HHhhBBH', payload, at)
        at += 12
        script = [struct.unpack_from('<Bbb', payload, at + 3 * k) for k in range(steps)]
        at += 3 * steps
        words = []
        for _ in range(frames):
            words.append(list(struct.unpack_from(f'<{w * h}H', payload, at)))
            at += w * h * 2
        sprites.append({'w': w, 'h': h, 'x': x, 'y': y, 'script': script, 'step_ms': step_ms, 'frames': words})
    if at != len(payload):
        raise ValueError('Trailing bytes in the animation payload')
    return {'sprites': sprites, 'stars': stars, 'meteor': meteor}
