"""PARADISE: a locally prepared beach photo and stable weekly readings.

Tony explicitly authorized a clean crop of his photo and offline processing.
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
from token_tv.credits import exhausted_credits, format_balance
from token_tv.themes import face

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


def _heart(scene, x, y, filled, colour, old, scale=1):
    """A little scallop shell for each saved reset (was a heart): ribbed and scalloped, solid when available and an outline
    when not. Drawn smooth at the scene's supersampling, in the 8x8 box where the hearts were; `scale` draws it bigger about the
    box's corner (the compact film panels use 1.5: Tony, 2026-11-03, "the shells are tiny")."""
    cx, cy = x + 4 * scale, y + 6.2 * scale
    arc = []
    for index in range(41):
        u = index / 40
        theta = math.pi + math.pi * u
        radius = (3.35 + .75 * abs(math.sin(5 * math.pi * u))) * scale
        arc.append((cx + radius * math.cos(theta) * 1.02, cy + radius * math.sin(theta)))
    shell = [(cx, cy + 1.1 * scale), *arc]
    stem = [(cx - 1.1 * scale, cy + .3 * scale), (cx + 1.1 * scale, cy + .3 * scale),
            (cx + .7 * scale, cy + 1.7 * scale), (cx - .7 * scale, cy + 1.7 * scale)]
    ink = MUTED if old else colour
    scaled = lambda points: [(round(a * SS), round(b * SS)) for a, b in points]
    fill = ink if filled else PAPER
    scene.d.polygon(scaled(stem), fill=fill)
    scene.d.polygon(scaled(shell), fill=fill)
    if filled:                                          # ribs run from the hinge to each notch of the edge
        for index in (8, 16, 24, 32):
            a, b = (cx, cy + .6 * scale), arc[index]
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
    if icons.marked(count, old_hearts):  # unknown or old: one faint dot at the end of the row, no ? and no OLD (Tony, 2026-10-20)
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


FILM_PANEL = {'codex': 51, 'claude': 58}     # height of each compact panel (they start at y=4); Claude's carries its two session rows
HUD_BOTTOM = 64                              # the photo below this row is pasted back exactly as it was supplied
SHELL = 1.5                                  # the film panels' shells are half as big again as the old ones


def _film_instrument(scene, row, provider, x):
    """Two compact panels leave the sailboat and the whole shore visible.

    Tony (2026-11-03): the panels covered a third of the picture (72 of 240 px) and the shells were tiny. The name and the three
    shells share the top row, the big number sits beside the weekly reset (the word above the time), then the weekly bar and,
    on Claude's, the two thin session rows; Codex's panel stops where its content does (51 px, Claude's 58)."""
    colour, track = COLORS[provider], '#a2b6a2'
    value, _, old, reset = remaining_reading(row)
    count, old_hearts = banked_hearts(row)
    scene.rect((x, 4, x + 152, 4 + FILM_PANEL[provider]), fill=(242, 247, 226, 210), radius=9)
    scene.text((x + 7, 8.5), provider.upper(), 'manrope.ttf', 12, colour, anchor='lt')
    for index in range(3):
        _heart(scene, x + 104 + 14 * index, 12.75 - 5 * SHELL, (count or 0) > index, colour, old_hearts, SHELL)
    if icons.marked(count, old_hearts):
        scene.dot((x + 148, 13), 1, MUTED, glow=False)
    if icons.mark(count, old_hearts):
        scene.text((x + 149, 8.5), '+', 'manrope.ttf', 9, colour, anchor='rt')
    credits = exhausted_credits(row) if provider == 'codex' else None
    if credits is not None:
        balance = format_balance(credits)
        scene.text((x + 7, 19.5), 'CREDITS', 'manrope.ttf', 8, colour, anchor='lt')
        for size in range(20, 5, -1):                       # the balance fills the number's place, never reaching the bar
            if scene.d.textlength(balance, font=face('manrope.ttf', size * SS)) <= 64 * SS:
                break
        scene.text((x + 7, 27.5), balance, 'manrope.ttf', size, colour, anchor='lt')
    else:
        figure = '--' if value is None else str(round(value))
        scene.text((x + 7, 19.5), figure, 'manrope.ttf', 30, colour, anchor='lt')
        if value is not None:                               # beside its number, not floating (Tony, 2026-11-03: "limpio")
            scene.text((x + 9 + scene.d.textlength(figure, font=face('manrope.ttf', 30 * SS)) / SS, 33), '%',
                       'manrope.ttf', 12, colour, anchor='lt')
    if old:
        scene.text((x + 65, 22), 'OLD', 'manrope.ttf', 7, MUTED, anchor='lt')
    scene.text((x + 145, 21.5), 'RESET', 'manrope.ttf', 9, MUTED, anchor='rt')
    scene.text((x + 145, 30.5), reset.upper().replace(' ', ''), 'manrope.ttf', 16, INK, anchor='rt')
    lit = 0 if value is None else math.ceil(value / 5)
    for index in range(20):
        left = x + 7 + index * 6.8
        scene.rect((left, 46, left + 5, 51), fill=colour if index < lit else track, radius=.5)
    pace = session_pace(row) if provider == 'claude' else None
    if pace is not None:
        for line, units in enumerate((math.ceil(pace[0] / 5) / 4, round(pace[1] * 4) / 4)):
            for index in range(5):
                left, yy = x + 10 + index * 27, 54 + line * 3
                scene.rect((left, yy, left + 22, yy + 2), fill=track, radius=.3)
                amount = max(0, min(1, units - index))
                if amount:
                    scene.rect((left, yy, left + 22 * amount, yy + 2), fill=colour, radius=.3)


def _film_page(snapshot, art):
    photo = art[0]
    scene = Scene()
    scene.base = photo.convert('RGBA').resize((W * SS, H * SS), Image.Resampling.BICUBIC)
    for provider, x in (('codex', 4), ('claude', 164)):
        _film_instrument(scene, _row(snapshot, provider), provider, x)
    image = scene.finish(blur=0)
    # Keep the boat, sea and sand as sharp as the supplied photographic still.
    image.paste(photo.crop((0, HUD_BOTTOM, W, H)), (0, HUD_BOTTOM))
    return image


def render_paradise(snapshot, animated=False, waves=False):
    if type(waves) is int and waves in (2, 3, 4):
        from token_tv import board_beach
        art = board_beach.load()
        if art:
            # Keep the existing moving-boat film and older prepared art usable.
            version = 4 if waves == 4 and len(art) >= 5 and art[4] and not art[3] else min(waves, 3)
            if version == 4:
                try:
                    payload = board_beach.encode(art, version=4)
                except ValueError:
                    payload = board_beach.encode(art, version=3)
            else:
                payload = board_beach.encode(art, version=version)
            return _film_page(snapshot, art), payload
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
