"""Optional, user-supplied arcade scenery stored outside the repository.

The existing original-art stage remains the fallback. The board receives the
finished background and tiny resident sprites, never the source game or ROM.
"""
from pathlib import Path

from PIL import Image

from token_tv import board_arcade_stage as stage

ART_DIRECTORY = Path.home() / '.local/share/ai-desk-display/arcade-local'
EFFECTS = ((110, 80, 25, 14), (160, 80, 27, 14))
EFFECT_FRAMES = 4


def load():
    """Load only a complete, correctly sized set; invalid art is optional."""
    def image(name, size, mode):
        with Image.open(ART_DIRECTORY / name) as source:
            if source.size != size:
                raise ValueError('Invalid local arcade artwork dimensions')
            return source.convert(mode)

    try:
        background = image('stage.png', (320, 240), 'RGB')
        effects = [[image(f'ambient-{index}-{frame}.png', (w, h), 'RGBA')
                    for frame in range(EFFECT_FRAMES)]
                   for index, (_, _, w, h) in enumerate(EFFECTS)]
        return background, effects
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


AMBIENT_MS = 600                    # the supplied backdrop's own pace, whatever the fighters' beat is
AMBIENT_SCRIPT = [(i, 0, 0) for i in (0, 1, 2, 3, 2, 1)]


def animated_details(art, codex_down, claude_down, step_ms=None, max_frames=4):
    """Keep both independent mascots and animate the supplied backdrop locally.

    The two ambient pieces are neighbours with one timing, so a board with eight frames gets them as ONE sprite: that
    frees a slot for the middle box of the fighters' exchange without changing a single pixel of the backdrop."""
    _, effects = art
    sprites = stage.fighters.actor_sprites(codex_down, claude_down, max_frames)
    if max_frames < 8:
        for (x, y, _, _), frames in zip(EFFECTS, effects):
            sprites.append({'x': x, 'y': y, 'frames': frames, 'script': list(AMBIENT_SCRIPT), 'step_ms': AMBIENT_MS})
        return sprites
    (x0, y0, w0, h0), (x1, y1, w1, h1) = EFFECTS
    assert y0 == y1 and h0 == h1 and x0 + 2 * w0 == x1            # side by side on one row
    merged = []
    for first, second in zip(*effects):
        frame = Image.new('RGBA', (w0 + w1, h0), (0, 0, 0, 0))
        frame.paste(first, (0, 0))
        frame.paste(second, (w0, 0))
        merged.append(frame)
    sprites.append({'x': x0, 'y': y0, 'frames': merged, 'script': list(AMBIENT_SCRIPT), 'step_ms': AMBIENT_MS})
    return sprites
