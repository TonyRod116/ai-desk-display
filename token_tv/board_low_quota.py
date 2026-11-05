"""One quiet sign that a provider's quota is nearly spent, the same on every screen of the board.

Tony (2026-11-03): the board must look calmer, so there is no text, no blinking and no per-screen alarm: when a provider has
less than 15 % left of its week (Claude: or of its five-hour session) a thin amber line, 2 px high, lights on the top edge of
THAT provider's half of the picture (Codex left, Claude right); below 5 % it turns red. Nothing is drawn when nothing is low, so
every page is byte-identical to what it was. It is static (the page changes only when a reading does), it never needs the
animation engines (they restore their boxes from the stored page, which already carries it) and it is applied once, at the end
of page rendering, by `render_board_pages` and `render_archive`.

Rules, all tested in `tests/test_board_low_quota.py`:

- the figure is the one the screens show: the remaining percentage rounded to a whole number, so "15%" is never amber;
- an UNKNOWN reading (no week, a different login, a failed reader, a blocked Codex) never draws it, and neither does a stale
  one (`status` other than ok); a reading that is merely aged (`reading_aged`, 3 to 8 minutes old, the number still shown) does;
- Claude's half answers to the lower of its week and its five-hour session (the session is what stops work first); an unknown
  or expired session counts for nothing;
- the line stays 8 px in from the outer corners (the Token Run tube has rounded ones) and leaves a gap in the middle, and
  VERSUS, whose top rows hold the score text, carries it on the top edge of each life bar instead;
- nothing else on the page changes: the line replaces pixels that were scenery or margin, never a reading.
"""
from PIL import ImageDraw

from token_tv.board_art import _row
from token_tv.personal_faces import remaining_reading, session_remaining

AMBER_BELOW, RED_BELOW = 15, 5                  # remaining percent, as the screens show it
COLOURS = {'amber': (255, 176, 32), 'red': (255, 64, 64)}
HEIGHT = 2                                      # a 1 px line shimmers on this panel; two rows are calm
# where each provider's line runs on a page: (first row, first column, last column), the last column included
SPAN = {'codex': (8, 151), 'claude': (168, 311)}
TOP = 0
# VERSUS fills the top rows with the score text: its line lies on the upper edge of each life bar instead
BARS = {'arcade': (16, {'codex': (8, 145), 'claude': (174, 311)})}


def level(remaining):
    """None, 'amber' or 'red' for a remaining percentage (None is unknown and never draws anything)."""
    if remaining is None:
        return None
    shown = round(remaining)
    return 'red' if shown < RED_BELOW else 'amber' if shown < AMBER_BELOW else None


def _counts(row):
    """A reading may be used when it is fresh or merely aged; a stale one (an old number kept for display) may not."""
    return row.get('status') == 'ok' or bool(row.get('reading_aged'))


def levels(snapshot):
    """{'codex': level, 'claude': level} from the snapshot the pages are drawn from."""
    result = {}
    for provider in ('codex', 'claude'):
        row = _row(snapshot, provider)
        figures = []
        if _counts(row):
            remaining = remaining_reading(row)[0]
            figures.append(remaining)
            if provider == 'claude':
                figures.append(session_remaining(row))
        known = [value for value in figures if value is not None]
        result[provider] = level(min(known)) if known else None
    return result


def line(name, provider):
    """(row, first column, last column) of the line on page `name`."""
    bar = BARS.get(name)
    if bar:
        return bar[0], *bar[1][provider]
    return TOP, *SPAN[provider]


def paint(image, name, provider, state):
    """Draw a provider's line, two rows with the ends rounded off by one pixel, on an RGB or RGBA image."""
    row, left, right = line(name, provider)
    colour = COLOURS[state] + ((255,) if image.mode == 'RGBA' else ())
    draw = ImageDraw.Draw(image)
    draw.rectangle((left, row, right, row), fill=colour)
    draw.rectangle((left + 1, row + 1, right - 1, row + 1), fill=colour)


def apply_one(image, name, snapshot):
    """Light the lines the snapshot calls for on one page; returns the image, unchanged when nothing is low."""
    for provider, state in levels(snapshot).items():
        if state:
            paint(image, name, provider, state)
    return image


def apply_low_quota(images, names, snapshot):
    """The end of page rendering: every page in `images` (named by `names`) gets its provider's line when a quota is low."""
    state = levels(snapshot)
    if any(state.values()):
        for image, name in zip(images, names):
            for provider, level_ in state.items():
                if level_:
                    paint(image, name, provider, level_)
    return images
