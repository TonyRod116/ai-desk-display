"""PARADISE: a locally prepared beach photo and stable weekly readings.

The user explicitly authorized a clean crop of his photo and offline processing.
Build 8 moves the whole photographic sea, including behind translucent panels,
while preserving every foreground pixel. Build 7 keeps the advancing surf and
gently swaying palm fallback. No repeated uploads, per-frame flash writes, clock
dependency or external image service.
"""

from functools import lru_cache
from pathlib import Path
import math

from PIL import Image

from token_tv import board_anim, board_reset_icons as icons
from token_tv.board_art import SS, Scene, _row
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace

W, H = 320, 240
STEP_MS = 200
SURF_SCRIPT = (
    (0, 0, 0),
    (1, 2, 0), (1, 0, 0), (1, -2, 0),
    (2, 2, 0), (2, 0, 0), (2, -2, 0),
    (3, 2, 0), (3, 0, 0), (3, -2, 0),
    (3, -2, 0), (3, -2, 0),
    (3, 0, 0), (3, 2, 0),
    (2, -2, 0), (2, 0, 0), (2, 2, 0),
    (1, -2, 0), (1, 0, 0), (1, 2, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
)
SURF_BOX = (42, 160, 184, 236)
PALM_BOX = (54, 30, 130, 58)
COLORS = {"codex": "#4e3404", "claude": "#34392f"}
INK, MUTED, TRACK, PAPER = "#153e45", "#2e3e34", "#cfdfce", "#f2f5df"
GLASS = (242, 247, 226, 156)


@lru_cache(maxsize=1)
def _landscape():
    """Packaged clean photo crop; no original-file dependency in the monitor."""
    with Image.open(
        Path(__file__).with_name("assets") / "paradise-landscape.png"
    ) as image:
        return image.convert("RGB")


@lru_cache(maxsize=1)
def _motion():
    sprites = []
    palm_script = [(frame, 0, 0) for frame, _, _ in SURF_SCRIPT]
    with Image.open(
        Path(__file__).with_name("assets") / "paradise-motion.png"
    ) as atlas:
        cursor = 0
        for box, script in ((SURF_BOX, SURF_SCRIPT), (PALM_BOX, palm_script)):
            w, h = (box[2] - box[0]) // 2, (box[3] - box[1]) // 2
            frames = []
            for _ in range(4):
                frames.append(atlas.crop((0, cursor, w, cursor + h)).convert("RGBA"))
                cursor += h
            sprites.append(
                {
                    "x": box[0],
                    "y": box[1],
                    "frames": frames,
                    "script": script,
                    "step_ms": STEP_MS,
                }
            )
        if cursor != atlas.height:
            raise ValueError("PARADISE motion atlas has unexpected dimensions")
    return tuple(sprites), board_anim.encode(sprites)


def _heart(scene, x, y, filled, colour, old):
    """A little scallop shell for each saved reset (was a heart): ribbed and scalloped, solid when available and an outline
    when not. Drawn smooth at the scene's supersampling, in the 8x8 box where the hearts were."""
    cx, cy = x + 4, y + 6.2
    arc = []
    for index in range(41):
        u = index / 40
        theta = math.pi + math.pi * u
        radius = 3.35 + .75 * abs(math.sin(5 * math.pi * u))
        arc.append((cx + radius * math.cos(theta) * 1.02, cy + radius * math.sin(theta)))
    shell = [(cx, cy + 1.1), *arc]
    stem = [(cx - 1.1, cy + .3), (cx + 1.1, cy + .3), (cx + .7, cy + 1.7), (cx - .7, cy + 1.7)]
    ink = MUTED if old else colour
    scaled = lambda points: [(round(a * SS), round(b * SS)) for a, b in points]
    fill = ink if filled else PAPER
    scene.d.polygon(scaled(stem), fill=fill)
    scene.d.polygon(scaled(shell), fill=fill)
    if filled:                                          # ribs run from the hinge to each notch of the edge
        for index in (8, 16, 24, 32):
            a, b = (cx, cy + .6), arc[index]
            scene.d.line(scaled([a, b]), fill=PAPER, width=max(1, round(SS * .55)))
    scene.d.line(scaled(shell + [shell[0]]), fill=ink, width=SS, joint='curve')


def _instrument(scene, row, provider, y):
    colour = COLORS[provider]
    value, _, old, reset = remaining_reading(row)
    count, old_hearts = banked_hearts(row)
    bottom = y + (101 if provider == "claude" else 93)
    scene.rect((190, y - 5, 315, bottom), fill=GLASS, radius=11)
    scene.text((200, y), provider.upper(), "manrope.ttf", 13, colour, anchor="lt")
    have = count if count is not None else 0
    for index in range(3):
        _heart(scene, 267 + 12 * index, y + 3, have > index, colour, old_hearts)
    if icons.marked(count, old_hearts):  # unknown or old: one faint dot at the end of the row, no ? and no OLD (the user, 2026-10-20)
        scene.dot((303.5, y + 6.6), 1.0, MUTED, glow=False)
    if icons.mark(count, old_hearts):
        scene.text((312, y + 3), "+", "manrope.ttf", 9, colour, anchor="rt")
    scene.text(
        (199, y + 17),
        "--" if value is None else str(round(value)),
        "manrope.ttf",
        38,
        colour,
        anchor="lt",
    )
    if value is not None:
        scene.text((308, y + 34), "%", "manrope.ttf", 18, colour, anchor="rt")
    if old:
        scene.text((308, y + 22), "OLD", "manrope.ttf", 8, MUTED, anchor="rt")
    lit = 0 if value is None else math.ceil(value / 5)
    for index in range(20):
        left = 200 + index * 5.5
        scene.rect(
            (left, y + 56, left + 3.5, y + 66),
            fill=colour if index < lit else TRACK,
            radius=0.8,
        )
    pace = session_pace(row) if provider == "claude" else None
    if pace is not None:
        for line, units in enumerate(
            (math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)
        ):
            yy = y + 70 + line * 6
            for index in range(5):
                left = 216 + index * 16
                scene.rect((left, yy, left + 12, yy + 3), fill=TRACK, radius=0.7)
                amount = max(0, min(1, units - index))
                if amount:
                    scene.rect(
                        (left, yy, left + 12 * amount, yy + 3), fill=colour, radius=0.7
                    )
    reset_y = y + (80 if provider == "claude" else 72)
    scene.text((200, reset_y + 4), "RESET", "manrope.ttf", 9, MUTED, anchor="lt")
    scene.text(
        (308, reset_y),
        reset.upper().replace(" ", ""),
        "manrope.ttf",
        17,
        INK,
        anchor="rt",
    )


@lru_cache(maxsize=1)
def _glass_background():
    """Identical photo/panels without ink, to identify pixels that must not move."""
    scene = Scene()
    scene.base = _landscape().convert("RGBA").resize((W*SS, H*SS), Image.Resampling.BICUBIC)
    for provider, y in (("codex", 37), ("claude", 137)):
        bottom = y + (101 if provider == "claude" else 93)
        scene.rect((190, y-5, 315, bottom), fill=GLASS, radius=11)
    image = scene.finish(blur=0)
    image.paste(_landscape().crop((0, 30, 184, H)), (0, 30))
    return image, scene.ink.getchannel("A").resize((W, H), Image.Resampling.LANCZOS)


def render_paradise(snapshot, animated=False, waves=False):
    scene = Scene()
    scene.base = (
        _landscape().convert("RGBA").resize((W * SS, H * SS), Image.Resampling.BICUBIC)
    )
    scene.text((12, 8), "PARADISE", "manrope.ttf", 20, "#ecfff7", anchor="lt")
    # Weekly readings retain the same scale/alignment; only the photo moves.
    _instrument(scene, _row(snapshot, "codex"), "codex", 37)
    _instrument(scene, _row(snapshot, "claude"), "claude", 137)
    image = scene.finish(blur=0)
    # Supersample the text/panels, but keep the untouched photograph at its native
    # resolution below the title. Avoid softening fine sand and water reflections.
    image.paste(_landscape().crop((0, 30, 184, H)), (0, 30))
    if waves:
        from token_tv.board_wave import encode
        return image, encode(image, *_glass_background())
    sprites, payload = _motion()
    if not animated:
        for sprite in sprites:
            frame = sprite["frames"][0]
            tile = frame.resize(
                (frame.width * 2, frame.height * 2), Image.Resampling.NEAREST
            )
            image.paste(
                tile,
                (sprite["x"], sprite["y"]),
                tile,
            )
    return (image, payload) if animated else image
