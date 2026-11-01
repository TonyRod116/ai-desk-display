"""Small, local animated previews of the frames already made for the display.

The web browser never asks the board for animation frames. These previews are
created on demand from a copy of the existing page and kept only in memory.
"""
from collections import OrderedDict
from io import BytesIO
import hashlib
import math
import struct
import threading

from PIL import Image, ImageDraw

from token_tv import board_anim

SIZE = (320, 240)
PREVIEW_SIZE = (240, 180)
BASE = 8 + SIZE[0] * SIZE[1] * 2


def _sprite_frames(sprite):
    result = []
    size = sprite['w'], sprite['h']
    for words in sprite['frames']:
        raw = struct.pack(f'<{len(words)}H', *words)
        pose = Image.frombytes('RGB', size, raw, 'raw', 'BGR;16')
        mask = Image.frombytes('L', size, bytes(0 if c == board_anim.KEY else 255 for c in words))
        target = (size[0] * 2, size[1] * 2)
        result.append((pose.resize(target, Image.Resampling.NEAREST),
                       mask.resize(target, Image.Resampling.NEAREST)))
    return result


def _color(word):
    return ((word >> 11) * 255 // 31, ((word >> 5) & 63) * 255 // 63, (word & 31) * 255 // 31)


def _anim_frames(base, animation, count, duration):
    sprites = [(sprite, _sprite_frames(sprite)) for sprite in animation['sprites']]
    for i in range(count):
        elapsed = i * duration
        image = base.copy()
        d = ImageDraw.Draw(image)
        for j, (x, y, original, bright, dim) in enumerate(animation['stars']):
            d.point((x, y), fill=_color((original, bright, dim)[(elapsed // 450 + j) % 3]))
        meteor = animation['meteor']
        if meteor and 2500 <= elapsed < 3700:
            tick = (elapsed - 2500) // 50
            x = (meteor['x0'] + meteor['x1']) // 2 + tick * meteor['speed']
            y = (meteor['y0'] + meteor['y1']) // 2 + tick * meteor['speed'] // 2
            length = meteor['length']
            d.line((x-length*2, y-length, x, y), fill=_color(meteor['tail']), width=2)
            d.rectangle((x, y, x+1, y+1), fill=_color(meteor['head']))
        for sprite, poses in sprites:
            step = (elapsed // sprite['step_ms']) % len(sprite['script'])
            frame, dx, dy = sprite['script'][step]
            pose, mask = poses[frame]
            image.paste(pose, (sprite['x'] + dx, sprite['y'] + dy), mask)
        yield image


def _words_image(words):
    raw = struct.pack(f'<{len(words)}H', *words)
    return Image.frombytes('RGB', SIZE, raw, 'raw', 'BGR;16')


def _sequence(frame):
    from token_tv.board_control import preview_image
    from token_tv.board_pages import frame_size

    if frame_size(frame) != SIZE:
        return None, None
    base = Image.frombytes('RGB', SIZE, frame[8:BASE], 'raw', 'BGR;16')
    kind, payload = frame[BASE:BASE + 4], frame[BASE + 8:]
    if kind == b'ANIM':
        animation = board_anim.decode(payload)
        periods = [len(s['script']) * s['step_ms'] for s in animation['sprites']]
        period = math.lcm(*periods) if periods else 4000
        # Preserve slower, deterministic scenes when their full cycle fits in
        # a bounded thumbnail; otherwise a preview would jump back mid-cycle.
        if 8000 < period <= 32000 and not animation['stars'] and not animation['meteor']:
            step = math.gcd(*(s['step_ms'] for s in animation['sprites']))
            if step >= 80 and period // step <= 64:
                return _anim_frames(base, animation, period // step, step), step
        # Very long combined cycles would be too expensive for a thumbnail.
        if not 0 < period <= 8000:
            period = max(3200, min(6400, max(periods)))
        count = max(16, min(48, round(period / 160)))
        duration = max(80, round(period / count))
        return _anim_frames(base, animation, count, duration), duration
    if kind in (b'WAVE', b'SCRO'):
        background = struct.unpack(f'<{SIZE[0]*SIZE[1]}H', frame[8:BASE])
        if kind == b'WAVE':
            from token_tv import board_beach, board_wave
            spec = board_wave.decode(payload)
            beach = spec.get('version') in (2, 3, 4)
            render = board_beach.render_words if beach else board_wave.render_words
            # Newer beach previews get a 100 ms cadence; older formats retain
            # their existing, less expensive previews.
            count = 64 if spec.get('version') in (3, 4) else 32 if beach else 16
            def waves():
                for i in range(count):
                    step = i * 64 // count
                    # WAVE3 plays two water cycles during one boat cycle on
                    # the board. The preview must use that same clock.
                    if spec.get('version') == 4:
                        water_step = i * spec['frame_count'] * 8 * 2 // count
                    else:
                        water_step = (step * 2) % 64 if spec.get('version') == 3 else step
                    words = (render(background, spec, water_step, boat_step=step)
                             if beach else render(background, spec, water_step))
                    yield _words_image(words)
            return waves(), 6400 // count
        from token_tv import board_scroll
        spec = board_scroll.decode(payload)
        # One full world loop; tick 384 returns the level and the actor to their start.
        def scroll():
            for tick in range(0, 384, 4):
                yield _words_image(board_scroll.render_words(background, spec, tick))
        return scroll(), 240
    if kind == b'STAR':
        count = struct.unpack_from('<H', frame, BASE + 4)[0]
        stars = [struct.unpack_from('<HHH', frame, BASE + 6 + 6*i) for i in range(count)]
        def twinkle():
            for phase in range(20):
                image = base.copy()
                d = ImageDraw.Draw(image)
                for i, (x, y, colour) in enumerate(stars):
                    if (phase + i) % 5 == 0:
                        d.point((x, y), fill='white')
                    else:
                        d.point((x, y), fill=_color(colour))
                yield image
        return twinkle(), 200
    return iter((preview_image(frame),)), 200


def _encode(frame):
    sequence, duration = _sequence(frame)
    if sequence is None:
        return None
    images = [image.resize(PREVIEW_SIZE, Image.Resampling.LANCZOS) for image in sequence]
    out = BytesIO()
    images[0].save(out, format='WEBP', save_all=True, append_images=images[1:],
                   duration=duration, loop=0, quality=78, method=2)
    return out.getvalue(), 'image/webp'


class AnimatedPreviews:
    """Bound work and reuse the same encoded page across all browser views."""
    def __init__(self):
        self.lock = threading.Lock()
        self.cache = OrderedDict()

    def get(self, frame):
        if frame is None:
            return None
        key = hashlib.sha256(frame).digest()
        # Encode at most one preview at once, never under the board or publisher lock.
        with self.lock:
            if key not in self.cache:
                try:
                    result = _encode(frame)
                except (ValueError, IndexError, KeyError, OSError, struct.error, ZeroDivisionError):
                    # Older Pillow builds can lack animated WebP support.
                    from token_tv.board_control import preview_image
                    image = preview_image(frame)
                    if image is None:
                        return None
                    out = BytesIO()
                    image.save(out, format='PNG')
                    result = out.getvalue(), 'image/png'
                if result is None:
                    return None
                self.cache[key] = result
                while len(self.cache) > 32:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(key)
            return self.cache[key]
