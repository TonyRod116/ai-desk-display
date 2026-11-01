"""An original sunset driving scene for Cockpit: four stored poses, no frame streaming.

Everything is drawn in logical pixels. The caller masks the instrument panel before sending two
disjoint 80px-wide sprites to firmware 7; composing the car into the road avoids sprites erasing
one another. The CRT scanlines stay at the same screen coordinates in every pose.
"""
from functools import lru_cache
import math

from PIL import Image, ImageDraw

WIDTH, TOP, HEIGHT = 160, 65, 27
STEP_MS = 160


def sunset(draw):
    """Striped sunset through the windscreen, drawn behind the instruments."""
    draw.rectangle((4, 16, 155, 91), fill='#050d11')
    draw.rectangle((4, 42, 155, 64), fill='#0d1920')
    draw.ellipse((66, 16, 94, 44), fill='#25221b')
    colours = ('#f0be6b', '#dd9256', '#b85868', '#833d62')
    for y in range(19, 42):
        for x in range(69, 92):
            if math.hypot(x - 80, y - 30) > 11:
                continue
            if y >= 29 and (y - 29) % 4 == 0:
                continue
            draw.point((x, y), fill=colours[min(3, (y - 19) // 6)])
    draw.line((5, 64, 154, 64), fill='#327876')


def _palm(draw, x, bottom, size):
    crown = bottom - size
    draw.line((x, bottom, x + 1, crown), fill='#386969')
    for direction in (-1, 1):
        draw.line(((x + 1, crown), (x + 1 + direction * size // 2, crown - size // 4),
                   (x + 1 + direction * size, crown + size // 4)), fill='#386969')
        draw.line(((x + 1, crown), (x + 1 + direction * size // 2, crown + size // 3)), fill='#386969')


def _car(draw, phase):
    """Rear of a small convertible, deliberately original pixel art rather than a ripped sprite."""
    y = 79 - (phase == 2)
    draw.rectangle((69, y + 6, 91, y + 11), fill='#040808')           # tyres and shadow
    draw.polygon(((75, y), (85, y), (88, y + 4), (72, y + 4)), fill='#78b4a7')
    draw.polygon(((76, y + 1), (84, y + 1), (86, y + 3), (74, y + 3)), fill='#172d3b')
    draw.rectangle((76, y + 3, 78, y + 4), fill='#d3b9a1')          # two seats
    draw.rectangle((82, y + 3, 84, y + 4), fill='#d3b9a1')
    draw.polygon(((72, y + 4), (88, y + 4), (90, y + 6), (89, y + 10),
                  (71, y + 10), (70, y + 6)), fill='#c85656')
    draw.line((72, y + 5, 88, y + 5), fill='#f0be6b')
    draw.rectangle((73, y + 7, 76, y + 7), fill='#f0be6b')
    draw.rectangle((84, y + 7, 87, y + 7), fill='#f0be6b')
    draw.line((72, y + 9, 88, y + 9), fill='#833d62')
    draw.rectangle((78, y + 9, 82, y + 10), fill='#d3b9a1')


@lru_cache(maxsize=1)
def frames():
    """Four RGBA road poses at 160x27. No clock, snapshot, account or random input."""
    poses = []
    for phase in range(4):
        image = Image.new('RGBA', (WIDTH, HEIGHT), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        for y in range(HEIGHT):
            depth = y / (HEIGHT - 1)
            centre = 80 + round(4 * depth * (1 - depth))
            half = 3 + round(75 * depth * depth)
            stripe = (3 / (depth + .22) + phase / 4) % 1 < .45
            draw.line((4, y, 155, y), fill='#101c20')
            draw.line((max(4, centre - half), y, min(155, centre + half), y),
                      fill='#0c1823' if stripe else '#10212c')
            curb = max(1, round(depth * 3))
            for side in (-1, 1):
                x = centre + side * half
                draw.line((x, y, x + side * curb, y), fill='#b85868' if stripe else '#d3b9a1')
                draw.point((x + side * (curb + 1), y), fill='#327876')
                if stripe:
                    lane = centre + side * half // 3
                    draw.line((lane, y, lane + max(0, round(depth * 2) - 1), y), fill='#78b4a7')
        # Each cycle advances the identical pair of palms by one spacing; the loop has no backwards jump.
        for k in range(2):
            depth = (k / 2 + phase / 8) % 1
            bottom = round(depth * (HEIGHT - 2))
            distance = 9 + round(67 * depth * depth)
            size = max(1, round(13 * depth))
            for side in (-1, 1):
                _palm(draw, 80 + side * distance, bottom, size)
        # Car coordinates are in page pixels; this temporary layer translates them into the road strip.
        car = Image.new('RGBA', (WIDTH, 120), (0, 0, 0, 0))
        _car(ImageDraw.Draw(car), phase)
        image.alpha_composite(car.crop((0, TOP, WIDTH, TOP + HEIGHT)))
        # The dim row is fixed on the tube, so motion does not cause CRT lines to flash on and off.
        pixels = image.load()
        for y in range(HEIGHT):
            if (y + TOP - 6) % 5:
                continue
            for x in range(WIDTH):
                r, g, b, a = pixels[x, y]
                if a:
                    pixels[x, y] = (r * 3 // 4, g * 3 // 4, b * 3 // 4, a)
        poses.append(image)
    return tuple(poses)
