"""PRISM: luminous glass, a floating crystal and weekly instruments (page 4).

The crystal is ray-traced offline and kept at native resolution. Four masked
reflection poses run on firmware 7 without touching its fine silhouette or any
reading. No streaming, telemetry, randomness or PC-clock animation.
"""
from functools import lru_cache
import math

from pathlib import Path

from PIL import Image

from token_tv import board_anim
from token_tv.board_art import CLAUDE, CODEX, SS, Scene, _mix, _row
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace

W, H = 320, 240
INK, WHITE, MUTED = '#060a15', '#e6f7ff', '#8198af'
COLORS = {'codex': CODEX, 'claude': CLAUDE}
CRYSTAL_BOX = (168, 42, 312, 170)
STEP_MS = 420


@lru_cache(maxsize=1)
def _atmosphere():
    """A quiet aurora, with no starfield, fine grid or time-dependent decoration."""
    image = Image.new('RGBA', (W, H))
    pixels = []
    for y in range(H):
        for x in range(W):
            cyan = math.exp(-((x - 248) / 76) ** 2 - ((y - 96) / 100) ** 2)
            violet = math.exp(-((x - 266) / 102) ** 2 - ((y - 190) / 57) ** 2)
            veil = math.exp(-((y - 164 + (x - 200) * .4) / 19) ** 2) * (x / W) ** 2
            pixels.append((round(5 + 14 * violet + 3 * cyan + 3 * veil),
                           round(9 + 19 * cyan + 3 * violet + 7 * veil),
                           round(20 + 28 * cyan + 25 * violet + 12 * veil), 255))
    image.putdata(pixels)
    return image


def _polygon(scene, points, fill, outline=None, glow=False):
    points = [(x * SS, y * SS) for x, y in points]
    scene.d.polygon(points, fill=fill)
    if outline:
        scene.d.line(points + [points[0]], fill=outline, width=SS, joint='curve')
        if glow:
            scene.g.line(points + [points[0]], fill=outline, width=SS, joint='curve')


@lru_cache(maxsize=1)
def _gallery():
    scene = Scene()
    scene.base = _atmosphere().resize((W * SS, H * SS), Image.Resampling.BICUBIC)
    # A single glass instrument column, rather than a pair of conventional cards.
    _polygon(scene, ((9, 47), (15, 41), (150, 41), (156, 47), (156, 233),
                     (150, 239), (15, 239), (9, 233)), (8, 16, 28, 228), '#293a4b')
    scene.line((18, 42), (145, 42), '#527181')
    scene.line((11, 56), (11, 130), '#a0e2cb', glow=True)
    scene.line((11, 150), (11, 224), '#706fa6', glow=True)
    scene.line((20, 139), (146, 139), '#26394c')
    scene.text((16, 12), 'PRISM', 'orbitron.ttf', 23, WHITE, anchor='lt')
    return scene.finish(blur=6)


def _heart(scene, x, y, filled, color, old):
    points = []
    for i in range(48):
        t = math.tau * i / 48
        px = 16 * math.sin(t) ** 3
        py = -(13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t))
        points.append((x + 4 + px / 4, y + 3 + py / 4))
    edge = _mix(color, INK, .42 if old else .16)
    _polygon(scene, points, edge if filled else '#0b1723', edge)


def _instrument(scene, row, provider, y):
    color = COLORS[provider]
    remaining, _, old, reset = remaining_reading(row)
    count, old_hearts = banked_hearts(row)
    scene.text((20, y), provider.upper(), 'orbitron.ttf', 13, color, anchor='lt')
    for index in range(3):
        _heart(scene, 90 + 11 * index, y + 3, count is not None and count > index, color, old_hearts)
    mark = '?' if count is None else ('+' if count > 3 else '') + ('OLD' if old_hearts else '')
    if mark:
        scene.text((127, y + 1), mark, 'manrope.ttf', 10, MUTED, anchor='lt')
    scene.text((18, y + 17), '--' if remaining is None else str(round(remaining)),
               'orbitron.ttf', 38, _mix(color, WHITE, .36), anchor='lt')
    if remaining is not None:
        scene.text((149, y + 33), '%', 'manrope.ttf', 19, color, anchor='rt')
    if old:
        scene.text((148, y + 17), 'OLD', 'manrope.ttf', 9, MUTED, anchor='rt')
    lit = 0 if remaining is None else math.ceil(remaining / 5)
    for index in range(20):
        left = 20 + index * 6.3
        active = index < lit
        fill = (WHITE if index == lit - 1 else color) if active else '#243244'
        scene.rect((left, y + 60, left + 4.3, y + 66), fill=fill, radius=1, glow=active)
    pace = session_pace(row) if provider == 'claude' else None
    if pace is not None:
        for line, units in enumerate((math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)):
            top = y + 70 + line * 4
            for index in range(5):
                left = 20 + index * 25.2
                scene.rect((left, top, left + 21, top + 2), fill='#27323c')
                amount = max(0, min(1, units - index))
                if amount:
                    scene.rect((left, top, left + max(1, round(21 * amount)) - 1, top + 2),
                               fill=color if line == 0 else '#948b7e')
    reset_y = y + (78 if provider == 'claude' else 73)
    scene.text((20, reset_y + 4), 'RESET', 'manrope.ttf', 10, MUTED, anchor='lt')
    scene.text((149, reset_y), reset.upper(), 'manrope.ttf', 17, WHITE, anchor='rt')


@lru_cache(maxsize=1)
def _optics():
    with Image.open(Path(__file__).with_name('assets') / 'prism-optics.png') as source:
        if source.size != (160, 240):
            raise ValueError('PRISM requires its native optical studio background')
        return source.convert('RGB')


@lru_cache(maxsize=1)
def _crystal():
    """The native silhouette stays fixed; only interior light reflections move."""
    with Image.open(Path(__file__).with_name('assets') / 'prism-reflections.png') as source:
        if source.size != (72, 256):
            raise ValueError('PRISM requires four compatible reflection poses')
        atlas = source.convert('RGBA')
    frames = [atlas.crop((0, phase * 64, 72, (phase + 1) * 64)) for phase in range(4)]
    sprites = ({'x': CRYSTAL_BOX[0], 'y': CRYSTAL_BOX[1], 'frames': frames,
                'script': [(i, 0, 0) for i in (0, 1, 2, 3, 2, 1)], 'step_ms': STEP_MS},)
    return sprites, board_anim.encode(sprites)


def render_prism(snapshot, animated=False):
    scene = Scene()
    scene.base = _gallery().convert('RGBA').resize((W * SS, H * SS), Image.Resampling.BICUBIC)
    _instrument(scene, _row(snapshot, 'codex'), 'codex', 47)
    _instrument(scene, _row(snapshot, 'claude'), 'claude', 144)
    image = scene.finish(blur=3)
    image.paste(_optics(), (160, 0))
    sprites, payload = _crystal()
    if not animated:
        for sprite in sprites:
            pose = sprite['frames'][0].resize((sprite['frames'][0].width * 2, sprite['frames'][0].height * 2),
                                               Image.Resampling.NEAREST)
            image.paste(pose, (sprite['x'], sprite['y']), pose)
    return (image, payload) if animated else image
