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


def animated_details(art, codex_down, claude_down, step_ms, max_frames=4):
    """Keep both independent mascots and animate the supplied backdrop locally."""
    _, effects = art
    codex_pace = 180 if max_frames >= 8 else step_ms
    claude_pace = 220 if max_frames >= 8 else step_ms * 4 // 3
    sprites = [stage._stance_sprite('codex', codex_down, codex_pace, max_frames),
               stage._stance_sprite('claude', claude_down, claude_pace, max_frames)]
    for (x, y, _, _), frames in zip(EFFECTS, effects):
        sprites.append({'x': x, 'y': y, 'frames': frames,
                        'script': [(i, 0, 0) for i in (0, 1, 2, 3, 2, 1)],
                        'step_ms': step_ms * 2})
    return sprites
