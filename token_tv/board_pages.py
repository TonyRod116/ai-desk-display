"""Eight pages for the touch ESP32 board (320x240), mixing LCD, pixel art and luminous instruments.

The board holds the pages and changes between them when touched, so it never
asks this PC for anything. Quotas are the same readings as the clock faces;
unknown stays `--` and Claude's session is drawn only from a fresh reading.
Page 2 is PARADISE, page 3 Neon City (the Code Forge slot), page 4 TIDAL RUSH,
page 5 TOKEN RUN (an Out Run-style road with two usage dials), and page 6 a fighting game.
See board_paradise.py, board_forge.py, board_surf.py, board_dials.py and board_arcade.py.

Pages travel as exact RGB565 pixels, not JPEG: a 2.8-inch panel makes
compression artefacts obvious and the board then needs no decoder at all.
Frame = b'TVF1' + width (u16 LE) + height (u16 LE) + width*height RGB565 (LE).
A page smaller than the screen would be centred on black; the pages are drawn full size.
"""
import struct

PAGE_SIZE = (320, 240)
FACES = ('game-boy', 'game-boy-pocket', 'retro', 'amber-terminal', 'orbit')  # the clock's album order
# The board's own order: Neon City keeps the Code Forge identifier in slot 3; TIDAL RUSH follows it.
BOARD_FACES = ('game-boy',)
PAGE_NAMES = BOARD_FACES + ('paradise', 'code-forge', 'surf', 'dials', 'arcade', 'cockpit', 'countdown')
# LCD grid of the two Game Boy faces on the board, as (axes, strength). The panel shimmered with a line every
# 2 px in both directions (the user, 2026-10-13); one direction only is calm, and the user confirmed neither of these
# flickers. Never put a period-2 grid back on both axes.
LCD_GRID = {'game-boy': ('vertical', .22), 'game-boy-pocket': ('horizontal', .22)}
MAGIC = b'TVF1'
_FRAMES = {}


def rgb565_frame(image, stars=None, anim=None, waves=None):
    """Exact RGB565 frame of a PIL image; the result is cached by content.

    `stars` is an optional list of (x, y, rgb565) the board may make twinkle: they travel as a trailer,
    b'STAR' + count (u16 LE) + count * (x, y, colour) u16 LE, after the pixels. `anim` is an ANIM payload
    (see token_tv/board_anim.py), sent instead of the stars. Firmware 8 accepts
    a WAVE payload (board_wave.py) instead, to animate the whole photographic sea.
    """
    image = image.convert('RGB')
    data = image.tobytes()
    stars = tuple(stars or ())
    anim = bytes(anim or b'')
    waves = bytes(waves or b'')
    if waves and (anim or stars):
        raise ValueError('A wave page cannot also contain sprites or stars')
    key = (image.size, hash(data), stars, anim, waves)
    if key not in _FRAMES:
        if len(_FRAMES) > 24:
            _FRAMES.clear()
        words = [((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)
                 for r, g, b in zip(data[0::3], data[1::3], data[2::3])]
        trailer = b''
        if waves:
            from token_tv.board_wave import decode
            decode(waves)
            if image.size != PAGE_SIZE:
                raise ValueError('Ocean animation requires a full-screen page')
            trailer = b'WAVE' + struct.pack('<I', len(waves)) + waves
        elif anim:
            trailer = b'ANIM' + struct.pack('<I', len(anim)) + anim
        elif stars:
            trailer = b'STAR' + struct.pack('<H', len(stars)) + b''.join(struct.pack('<HHH', *s) for s in stars)
        _FRAMES[key] = (MAGIC + struct.pack('<HH', *image.size) + struct.pack(f'<{len(words)}H', *words)
                        + trailer)
    return _FRAMES[key]


def frame_size(frame):
    """(width, height) if `frame` is a well-formed frame, else None."""
    if len(frame) < 8 or frame[:4] != MAGIC:
        return None
    width, height = struct.unpack('<HH', frame[4:8])
    if not 0 < width <= PAGE_SIZE[0] or not 0 < height <= PAGE_SIZE[1]:
        return None
    base = 8 + width * height * 2
    extra = len(frame) - base
    if extra == 0:
        return width, height
    if extra >= 6 and frame[base:base + 4] == b'STAR':          # optional twinkling-star trailer
        count = struct.unpack('<H', frame[base + 4:base + 6])[0]
        if extra == 6 + 6 * count and count <= 128:
            return width, height
    if extra >= 12 and frame[base:base + 4] == b'ANIM':         # optional scene-animation trailer
        length = struct.unpack('<I', frame[base + 4:base + 8])[0]
        from token_tv.board_anim import MAX_PAYLOAD
        if extra == 8 + length and 4 <= length <= MAX_PAYLOAD and (width, height) == PAGE_SIZE:
            return width, height
    if extra >= 20 and frame[base:base + 4] == b'WAVE' and (width, height) == PAGE_SIZE:
        length = struct.unpack('<I', frame[base + 4:base + 8])[0]
        if extra == 8 + length and length <= 40000:
            from token_tv.board_wave import decode
            try:
                decode(frame[base + 8:])
            except (ValueError, struct.error):
                return None
            return width, height
    return None


def render_board_pages(snapshot, stars=False, anim=False, waves=False, anim_frames=8):
    """One frame per page, in PAGE_NAMES order, keeping the clock's separate album unchanged.

    `stars` adds the twinkling-star trailer to the pages that draw the starfield; `anim` lets PARADISE,
    Neon City, TIDAL RUSH, the driving CRT, VERSUS, cockpit and city use ANIM (otherwise their first poses are drawn in).
    `waves` uses the native WAVE engine for PARADISE only; its other seven pages are unchanged.
    `anim_frames` comes from /info: eight-pose Token Run requires firmware 14; older boards get its static pose."""
    from token_tv.personal_faces import RENDERERS as PERSONAL
    from token_tv.themes import RENDERERS as THEMES
    from token_tv.board_gameboy import render_gameboy_board
    faces = {'retro': THEMES['retro'], **PERSONAL, 'game-boy': render_gameboy_board}
    # Every face is drawn at the screen's own width, so nothing is left as black margin.
    from token_tv.board_arcade import render_arcade
    from token_tv.board_dials import render_dials
    from token_tv.board_neon_bridge import render_neon_bridge as render_forge
    from token_tv.board_surf import render_surf
    from token_tv.board_paradise import render_paradise
    from token_tv.board_art import free_stars, render_cockpit, render_countdown
    # The Game Boy faces get the LCD's pixel grid on the board (the clock's 240px faces stay as they were).
    images = [faces[name](snapshot, screen=PAGE_SIZE, **({'grid': LCD_GRID[name]} if name in LCD_GRID else {}))
              for name in BOARD_FACES]
    payloads = {}
    wave_payload = None
    if waves:
        paradise, wave_payload = render_paradise(snapshot, waves=True)
    elif anim:
        paradise, payloads['paradise'] = render_paradise(snapshot, animated=True)
    else:
        paradise = render_paradise(snapshot)
    images.append(paradise)
    if anim:
        forge, payloads['code-forge'] = render_forge(snapshot, animated=True)
    else:
        forge = render_forge(snapshot)
    images.append(forge)
    if anim:
        surf, payloads['surf'] = render_surf(snapshot, animated=True)
    else:
        surf = render_surf(snapshot)
    images.append(surf)
    if anim and anim_frames >= 8:
        dials, payloads['dials'] = render_dials(snapshot, animated=True)
    else:
        dials = render_dials(snapshot)
    images.append(dials)
    if anim:
        versus, payloads['arcade'] = render_arcade(snapshot, animated=True)
    else:
        versus = render_arcade(snapshot)
    if anim:
        countdown, payloads['countdown'] = render_countdown(snapshot, animated=True)
    else:
        countdown = render_countdown(snapshot)
    from token_tv.board_space import space_backdrop, star_field, render_cockpit as space_cockpit
    if anim:
        cockpit, payloads['cockpit'] = space_cockpit(snapshot, animated=True)
    else:
        cockpit = render_cockpit(snapshot)
    images += [versus, cockpit, countdown]
    from token_tv.board_credits import apply_credit_badges
    apply_credit_badges(images, PAGE_NAMES, snapshot)
    twinkle = {'cockpit'} if stars and not anim else set()
    sky = {'cockpit': {'backdrop': space_backdrop, 'field': star_field}}      # and it has its own
    return [rgb565_frame(image, free_stars(image, **sky.get(name, {})) if name in twinkle else None, payloads.get(name),
                        wave_payload if name == 'paradise' else None)
            for name, image in zip(PAGE_NAMES, images)]
