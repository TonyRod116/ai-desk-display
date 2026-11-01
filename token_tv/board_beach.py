"""A private, stabilised beach film for newer touch boards.

The source stays on this computer. The board receives an indexed animation
and adds its colour changes to the sharp still. Newer boards can use a
compressed 48-position loop; older boards retain the eight-frame format.
"""

from functools import lru_cache
from pathlib import Path
import struct

from PIL import Image

TOP, ROWS = 132, 108
WIDTH, HEIGHT, FRAMES = 160, ROWS // 2, 8
SMOOTH_FRAMES, BANDS, MAX_PAYLOAD = 48, 7, 80000
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
        smooth = None
        try:
            with Image.open(ART_DIRECTORY / 'water48.png') as source:
                palette = source.getpalette()
                if (source.size == (WIDTH, HEIGHT * SMOOTH_FRAMES) and source.mode == 'P'
                        and palette is not None and len(palette) >= 768):
                    smooth = (tuple(_word(palette[i:i+3]) for i in range(0, 768, 3)), source.tobytes())
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
        return background, words, frames, boat, smooth
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _pack_frame(data):
    """Bounded run-length packets: the still parts of a shoreline compress well."""
    out = bytearray()
    i = 0
    while i < len(data):
        j = i + 1
        while j < len(data) and j - i < 128 and data[j] == data[i]:
            j += 1
        if j - i >= 3:
            out.extend((0x80 | (j - i - 1), data[i]))
            i = j
            continue
        start, i = i, j
        while i < len(data) and i - start < 128:
            j = i + 1
            while j < len(data) and j - i < 128 and data[j] == data[i]:
                j += 1
            if j - i >= 3:
                break
            i = min(j, start + 128)
        out.append(i - start - 1)
        out.extend(data[start:i])
    return bytes(out)


def _unpack_frame(data):
    out = bytearray()
    pos = 0
    while pos < len(data):
        control = data[pos]
        pos += 1
        count = (control & 127) + 1
        if len(out) + count > WIDTH * HEIGHT:
            raise ValueError('Invalid compressed beach frame')
        if control & 128:
            if pos >= len(data):
                raise ValueError('Invalid compressed beach frame')
            out.extend(bytes((data[pos],)) * count)
            pos += 1
        else:
            if pos + count > len(data):
                raise ValueError('Invalid compressed beach frame')
            out.extend(data[pos:pos + count])
            pos += count
    if len(out) != WIDTH * HEIGHT:
        raise ValueError('Invalid compressed beach frame')
    return bytes(out)


@lru_cache(maxsize=1)
def _encode_smooth(palette, frames):
    stride = WIDTH * HEIGHT
    if len(palette) != 256 or len(frames) != stride * SMOOTH_FRAMES:
        raise ValueError('Invalid smooth beach animation')
    bounds = [[320, 0] for _ in range(BANDS)]
    zero = frames[:stride]
    for phase in range(1, SMOOTH_FRAMES):
        frame = frames[phase * stride:(phase + 1) * stride]
        for pos, value in enumerate(frame):
            if palette[value] != palette[zero[pos]]:
                y, x = divmod(pos, WIDTH)
                band = y // 8
                bounds[band][0] = min(bounds[band][0], x * 2)
                bounds[band][1] = max(bounds[band][1], x * 2 + 2)
    header = HEADER.pack(4, 0, TOP, ROWS, STEP_MS, STEPS, SMOOTH_FRAMES)
    metadata = header + struct.pack('<256H', *palette) + b''.join(struct.pack('<HH', *b) for b in bounds)
    cursor = len(metadata) + SMOOTH_FRAMES * 6
    table, blobs, seen = [], [], {}
    for phase in range(SMOOTH_FRAMES):
        frame = frames[phase * stride:(phase + 1) * stride]
        if frame not in seen:
            blob = _pack_frame(frame)
            seen[frame] = (cursor, len(blob))
            blobs.append(blob)
            cursor += len(blob)
        table.append(struct.pack('<IH', *seen[frame]))
    result = metadata + b''.join(table) + b''.join(blobs)
    if len(result) > MAX_PAYLOAD:
        raise ValueError('Smooth beach animation exceeds board capacity')
    return result


def encode(art, version=2):
    _, palette, frames = art[:3]
    if version == 4:
        if len(art) < 5 or art[4] is None or art[3] is not None:
            raise ValueError('Smooth beach requires a film and a still boat')
        return _encode_smooth(*art[4])
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
    if payload and payload[0] == 4:
        metadata_end = HEADER.size + 512 + BANDS * 4
        table_end = metadata_end + SMOOTH_FRAMES * 6
        if len(payload) < table_end or len(payload) > MAX_PAYLOAD:
            raise ValueError('Invalid smooth beach animation')
        if HEADER.unpack_from(payload) != (4, 0, TOP, ROWS, STEP_MS, STEPS, SMOOTH_FRAMES):
            raise ValueError('Invalid smooth beach animation')
        for band in range(BANDS):
            left, right = struct.unpack_from('<HH', payload, HEADER.size + 512 + band * 4)
            if left > 320 or right > 320 or left % 2 or right % 2 or (right and left >= right):
                raise ValueError('Invalid smooth beach region')
        decoded, frames = {}, []
        for phase in range(SMOOTH_FRAMES):
            offset, size = struct.unpack_from('<IH', payload, metadata_end + phase * 6)
            if (offset < table_end or not size or size > WIDTH * HEIGHT + WIDTH * HEIGHT // 128 + 2
                    or offset + size > len(payload)):
                raise ValueError('Invalid smooth beach frame offset')
            key = offset, size
            if key not in decoded:
                decoded[key] = _unpack_frame(payload[offset:offset + size])
            frames.append(decoded[key])
        if max(offset + size for offset, size in decoded) != len(payload):
            raise ValueError('Invalid smooth beach length')
        return {'version': 4, 'palette': struct.unpack_from('<256H', payload, HEADER.size),
                'frames': b''.join(frames), 'frame_count': SMOOTH_FRAMES}
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


def render_words(background, beach, step, boat_step=None, *, water_substeps=8):
    """Integer reference for the board; preserve the sharp photo's detail.

    Newer firmware can use finer water positions between source frames. The
    boat remains on its own unchanged 64-step clock.
    """
    if water_substeps not in (8, 16, 128):
        raise ValueError('Unsupported water interpolation')
    out = list(background)
    frames, palette = beach['frames'], beach['palette']
    stride = WIDTH * HEIGHT
    frame_count = beach.get('frame_count', FRAMES)
    step %= frame_count * water_substeps
    first, mix = divmod(step, water_substeps)
    for yy in range(HEIGHT):
        for xx in range(WIDTH):
            pos = yy * WIDTH + xx
            c0 = palette[frames[pos]]
            ca = palette[frames[first * stride + pos]]
            cb = palette[frames[((first + 1) % frame_count) * stride + pos]]
            # Match the board's stable spatial thresholds. Small colour
            # changes then progress across the sea rather than jump in sync.
            bias = (((pos * 73 + 19) & 127) * water_substeps // 128
                    if beach['version'] >= 3 else water_substeps // 2)
            for ry in (0, 1):
                for rx in (0, 1):
                    at = (TOP + yy * 2 + ry) * 320 + xx * 2 + rx
                    original = background[at]
                    result = 0
                    for shift, mask in ((11, 31), (5, 63), (0, 31)):
                        a, b, base = (ca >> shift) & mask, (cb >> shift) & mask, (c0 >> shift) & mask
                        delta = (a * (water_substeps - mix) + b * mix + bias) // water_substeps - base
                        # Fade into the fixed horizon without a moving seam.
                        fade = min(8, yy)
                        delta = (delta * fade // 8 if delta >= 0 else -((-delta * fade) // 8))
                        result |= max(0, min(mask, ((original >> shift) & mask) + delta)) << shift
                    out[at] = result
    if 'boat_frames' in beach:
        boat_step = (step * 8 // water_substeps if boat_step is None else boat_step) % STEPS
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
