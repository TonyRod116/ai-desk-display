"""A 16-bit quest scene with original art and the board's real usage readings.

Optional locally supplied artwork stays on the owner's computer; the bundled
adventurer, landscape and gauges are original drawings.
"""
from functools import lru_cache
import math
from pathlib import Path
import random

from PIL import Image, ImageDraw

from token_tv import board_anim
from token_tv.board_arcade_stage import paint_first_frame
from token_tv.board_art import _row
from token_tv.credits import exhausted_credits, format_balance
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

ART = Path.home() / '.local/share/ai-desk-display/zelda-local/link-walk.png'
LANDSCAPE = ART.with_name('landscape.png')
ACTION = ART.with_name('action.png')
GUARD = ART.with_name('guard.png')
SIZE = (320, 240)
HEART = ('.###.###.', '#########', '#########', '.#######.',
         '..#####..', '...###...', '....#....')


def _walk_version():
    try:
        stat = ART.stat()
        version = (stat.st_mtime_ns, stat.st_size)
        return version if ART.is_file() and _cached_walk(ART, *version) else None
    except OSError:
        return None


def _local_version():
    try:
        stats = tuple(path.stat() for path in (LANDSCAPE, ACTION, GUARD))
        versions = tuple((stat.st_mtime_ns, stat.st_size) for stat in stats)
        if (_cached_landscape(LANDSCAPE, *versions[0]) is None or
                not _cached_strip(ACTION, *versions[1], 29, 30) or
                not _cached_strip(GUARD, *versions[2], 24, 24)):
            return None
        return tuple(value for version in versions for value in version)
    except (OSError, ValueError):
        return None


def art_version():
    """Invalidate previews when the optional local artwork changes."""
    local = _local_version()
    if local:
        return ('scene', *local)
    walk = _walk_version()
    return ('walk', *walk) if walk else None


@lru_cache(maxsize=3)
def _cached_landscape(path, modified, size):
    try:
        with Image.open(path) as image:
            return image.convert('RGB') if image.size == SIZE else None
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=6)
def _cached_strip(path, modified, size, width, height):
    try:
        with Image.open(path) as source:
            if source.size != (width * 8, height):
                return ()
            sheet = source.convert('RGBA')
            return tuple(sheet.crop((i * width, 0, (i + 1) * width, height)) for i in range(8))
    except (OSError, ValueError):
        return ()


def _local_art():
    version = _local_version()
    if not version:
        return None
    return (_cached_landscape(LANDSCAPE, *version[:2]),
            _cached_strip(ACTION, *version[2:4], 29, 30),
            _cached_strip(GUARD, *version[4:6], 24, 24))


@lru_cache(maxsize=3)
def _cached_walk(path, modified, size):
    try:
        with Image.open(path) as source:
            if source.size != (192, 26):
                return ()
            sheet = source.convert('RGBA')
            return tuple(sheet.crop((i * 24, 0, i * 24 + 24, 26)) for i in range(8))
    except (OSError, ValueError):
        return ()


def _walk():
    version = _walk_version()
    return _cached_walk(ART, *version) if version else _bundled_walk()


@lru_cache(maxsize=1)
def _bundled_walk():
    """Eight original traveller poses: no game graphics or personal files."""
    right = []
    for step in range(4):
        im = Image.new('RGBA', (24, 26))
        d = ImageDraw.Draw(im)
        # Amber hood and scarf, teal tunic, boots and a little satchel.
        d.ellipse((4, 23, 19, 25), fill=(29, 54, 45, 110))
        d.polygon([(6, 6), (8, 2), (15, 1), (19, 5), (19, 11),
                   (16, 15), (8, 14), (5, 11)], fill='#493b34')
        d.polygon([(7, 6), (9, 3), (15, 3), (18, 6), (17, 10),
                   (14, 11), (8, 10)], fill='#e3ad53')
        d.polygon([(9, 7), (17, 7), (18, 10), (16, 14),
                   (10, 14), (8, 11)], fill='#f4cc91')
        d.point((16, 9), fill='#382f2d')
        d.line((11, 4, 15, 4), fill='#ffe0a1')
        d.polygon([(8, 14), (16, 13), (18, 17), (18, 21),
                   (6, 21), (6, 17)], fill='#244e50')
        d.polygon([(9, 14), (15, 14), (16, 18), (15, 20),
                   (8, 20), (8, 17)], fill='#499887')
        d.line((8, 15, 16, 15), fill='#edb94e', width=2)
        d.rectangle((5, 16, 7, 20), fill='#c58d58')
        d.rectangle((17, 16, 19, 19), fill='#e1ae73')
        d.rectangle((5, 18, 8, 22), fill='#72523b')
        d.point((6, 19), fill='#e5bd75')
        front = (0, 1, 0, -1)[step]
        d.rectangle((8 - front, 21, 11 - front, 24), fill='#493a32')
        d.rectangle((14 + front, 21, 17 + front, 24), fill='#493a32')
        d.line((8 - front, 22, 11 - front, 22), fill='#b68552')
        d.line((14 + front, 22, 17 + front, 22), fill='#b68552')
        right.append(im)
    return tuple(right + [frame.transpose(Image.Transpose.FLIP_LEFT_RIGHT) for frame in right])



def _flower(d, x, y, colour):
    d.point((x,y + 2),fill='#216c43')
    for dx,dy in ((0,0),(-1,1),(1,1),(0,2)):
        d.point((x + dx,y + dy),fill=colour)
    d.point((x,y + 1),fill='#fff3a0')


@lru_cache(maxsize=1)
def _landscape():
    """An original 16-bit village terrace, drawn for a 160 x 120 pixel world."""
    im = Image.new('RGB', (160, 120), '#5da05a')
    d = ImageDraw.Draw(im)
    rnd = random.Random(732)

    # The lower earthen ledges frame an open path, with separate lit and shadow faces.
    for points in ([(0, 92), (47, 92), (52, 95), (55, 101), (62, 103),
                    (62, 119), (0, 119)],
                   [(100, 103), (105, 100), (108, 95), (112, 92), (159, 92),
                    (159, 119), (100, 119)]):
        d.polygon(points, fill='#513f2d')
    d.polygon([(0, 94), (45, 94), (49, 96), (53, 103), (60, 105), (60, 119), (0, 119)],
              fill='#a27346')
    d.polygon([(102, 105), (108, 102), (111, 96), (114, 94), (159, 94),
               (159, 119), (102, 119)], fill='#a27346')
    for y, colour in ((98, '#ca9a5b'), (102, '#8a5f3c'), (108, '#c38c53'),
                      (113, '#795238'), (118, '#be8954')):
        d.line((0, y, 47, y), fill=colour)
        d.line((114, y, 159, y), fill=colour)
    for x, y in ((4, 104), (18, 111), (31, 100), (41, 116), (120, 102),
                 (130, 114), (145, 106), (154, 117)):
        d.line((x, y, x + 4, y), fill='#795639')
        d.point((x + 3, y - 1), fill='#dfb978')
    d.line((0, 92, 47, 92, 52, 95, 55, 101, 61, 103), fill='#295c39', width=2)
    d.line((101, 103, 106, 100, 109, 95, 113, 92, 159, 92), fill='#295c39', width=2)
    d.line((0, 91, 47, 91), fill='#a4d77c')
    d.line((113, 91, 159, 91), fill='#a4d77c')

    # The warm path leads from the doorway down between the two terraces.
    d.polygon([(73, 47), (88, 47), (90, 64), (98, 84), (101, 98), (107, 119),
               (53, 119), (60, 100), (63, 84), (71, 64)], fill='#bdab71')
    d.polygon([(74, 50), (86, 50), (87, 65), (96, 88), (98, 102), (102, 119),
               (58, 119), (63, 102), (66, 85), (73, 64)], fill='#d6c184')
    for _ in range(85):
        x, y = rnd.randrange(55, 105), rnd.randrange(55, 120)
        if im.getpixel((x, y)) == (214, 193, 132):
            d.point((x, y), fill=rnd.choice(('#bcaa70', '#ead397', '#c7b376')))

    # A little cottage has a tiled roof, eaves, stone walls and a recessed door.
    d.rectangle((51, 25, 109, 56), fill='#514431')
    d.rectangle((54, 27, 106, 55), fill='#cda96e')
    d.rectangle((56, 29, 104, 52), fill='#dfc38c')
    for y in (31, 36, 41, 46, 51):
        d.line((56, y, 104, y), fill='#bb9868')
        for x in range(57 + (3 if y % 2 else 0), 104, 11):
            d.line((x, y, x, min(52, y + 3)), fill='#c5a778')
    d.polygon([(46, 26), (48, 22), (78, 7), (82, 7), (112, 22),
               (114, 26), (110, 29), (50, 29)], fill='#403b30')
    d.polygon([(49, 23), (79, 9), (81, 9), (110, 23), (108, 26), (51, 26)], fill='#8f5148')
    d.line((51, 22, 79, 9, 81, 9, 109, 22), fill='#e0a879')
    for y in (18, 21, 24):
        left = 80 - (y - 10) * 2
        right = 80 + (y - 10) * 2
        d.line((left, y, right, y), fill='#6f3e3c')
        for x in range(left + 2 + (y % 3), right, 6):
            d.line((x, y - 1, x + 2, y - 1), fill='#c8846e')
    d.rectangle((53, 26, 107, 29), fill='#735337')
    d.line((54, 27, 106, 27), fill='#f2d393')
    d.rectangle((72, 38, 88, 56), fill='#704c32')
    d.polygon([(74, 55), (74, 41), (76, 39), (84, 39), (86, 41), (86, 55)], fill='#24372c')
    d.rectangle((76, 42, 84, 55), fill='#132920')
    d.rectangle((69, 55, 91, 57), fill='#94754c')
    d.line((70, 55, 90, 55), fill='#f2d99d')
    for x in (58, 94):
        d.rectangle((x, 35, x + 10, 43), fill='#6b543c')
        d.rectangle((x + 2, 36, x + 8, 41), fill='#34584a')
        d.line((x + 5, 36, x + 5, 41), fill='#e9d59d')
        d.line((x + 2, 39, x + 8, 39), fill='#e9d59d')
        d.line((x + 1, 44, x + 9, 44), fill='#f5dfab')
    d.rectangle((91, 11, 97, 18), fill='#967657')
    d.line((90, 10, 98, 10), fill='#ddbf89', width=2)

    # Posts and hedges give the village the depth and texture of an adventure map.
    for start in (8, 119):
        d.line((start, 38, start + 32, 38), fill='#755132', width=3)
        d.line((start, 37, start + 32, 37), fill='#e0b878')
        for x in range(start, start + 33, 8):
            d.rectangle((x, 33, x + 3, 43), fill='#6c4c31')
            d.rectangle((x + 1, 33, x + 2, 40), fill='#c7965e')
            d.line((x, 33, x + 3, 33), fill='#f0d095')

    def hedge(x, y):
        d.rectangle((x + 1, y + 2, x + 10, y + 8), fill='#205b39')
        d.polygon([(x, y + 3), (x + 2, y), (x + 5, y + 1), (x + 7, y),
                   (x + 11, y + 2), (x + 11, y + 7), (x + 8, y + 9),
                   (x + 4, y + 8), (x + 1, y + 9)], fill='#2f7542')
        for dx, dy in ((2, 2), (6, 2), (9, 3), (4, 5), (8, 6)):
            d.line((x + dx, y + dy, x + dx + 1, y + dy - 1), fill='#80bf66')
        d.point((x + 5, y + 1), fill='#c0de87')
    for x, y in ((12, 48), (24, 48), (12, 58), (24, 58), (37, 60),
                 (113, 48), (125, 48), (137, 48), (125, 58), (137, 58)):
        hedge(x, y)

    # A few grass tufts, flowers, stones and a sign are hand-placed around the path.
    for x, y in ((4, 72), (18, 78), (43, 72), (49, 83), (109, 73), (121, 84),
                 (144, 74), (154, 84), (6, 85), (35, 83)):
        d.line((x, y + 2, x + 1, y, x + 2, y + 2), fill='#367444')
        d.point((x + 3, y + 1), fill='#9dcc76')
    for x, y, colour in ((8, 63, '#ffdf89'), (46, 67, '#fff6cc'), (25, 74, '#f8b8a1'),
                         (114, 65, '#fff1b8'), (148, 67, '#ffd181'), (134, 80, '#f9ccd1')):
        _flower(d, x, y, colour)
    for x, y in ((48, 75), (105, 77), (39, 86), (117, 89), (64, 106), (91, 111)):
        d.ellipse((x, y, x + 5, y + 3), fill='#6d8266')
        d.line((x + 1, y, x + 4, y), fill='#d4ddaa')
    d.rectangle((109, 66, 110, 76), fill='#675033')
    d.rectangle((104, 64, 115, 70), fill='#634932')
    d.rectangle((105, 65, 114, 68), fill='#e1be7d')
    d.line((107, 66, 112, 66), fill='#8e673b')
    return im


def _hearts(d, left, top, count, old):
    for i in range(3):
        active = count is not None and i < count
        # A dark rim keeps even an empty heart distinct from the grass.
        for y, row in enumerate(HEART):
            for x, cell in enumerate(row):
                if cell == '#':
                    d.rectangle((left + i * 11 + x - 1, top + y - 1,
                                 left + i * 11 + x + 1, top + y + 1), fill='#28432e')
        for y,row in enumerate(HEART):
            for x,cell in enumerate(row):
                if cell != '#': continue
                edge = any(not (0 <= y + dy < len(HEART) and 0 <= x + dx < len(row))
                           or HEART[y + dy][x + dx] != '#'
                           for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)))
                colour = ('#fff1d9' if edge else '#e74751') if active else ('#d4d6b4' if edge else '#506c50')
                d.point((left + i * 11 + x, top + y), fill=colour)
    if count is None or old:
        d.point((left + 33,top + 4),fill='#e5dfbd')
    if count is not None and count > 3:
        d.text((left + 34,top - 1),'+',font=face('press-start-2p.ttf',7),fill='#f7daa0')


def _pace(d, x, y, pace):
    if pace is None:
        return
    remaining, hours = pace
    # Match the other screens: update quota every 5% and time every 15 minutes.
    for row, units in enumerate((math.ceil(remaining / 5) / 4, round(hours * 4) / 4)):
        for segment in range(5):
            left = x + segment * 12
            d.rectangle((left,y + row * 5,left + 9,y + row * 5 + 2),fill='#365369')
            fill = round(10 * max(0,min(1,units - segment)))
            if fill:
                d.rectangle((left,y + row * 5,left + fill - 1,y + row * 5 + 2),
                            fill='#b9eaff' if row == 0 else '#e6d39b')


def _life_meter(d, x, remaining):
    """A game-like vertical health gauge, filled upward with the week left."""
    d.rounded_rectangle((x, 25, x + 13, 96), radius=4, fill='#18281e', outline='#151b17')
    d.rounded_rectangle((x + 1, 26, x + 12, 95), radius=3, fill='#f3f0d7')
    d.rectangle((x + 3, 30, x + 10, 91), fill='#203b2b')
    if remaining is not None:
        fill = round(62 * max(0, min(100, remaining)) / 100)
        if fill:
            top = 92 - fill
            d.rectangle((x + 3, top, x + 10, 91), fill='#55d454')
            d.line((x + 4, top, x + 4, 91), fill='#9aef76')
    else:
        # An unknown reading is visibly different from a genuinely empty bar.
        d.line((x + 4, 60, x + 9, 60), fill='#c9d5c1')


def _hud(im, snapshot):
    d = ImageDraw.Draw(im)
    for provider, meter, box, hearts, edge in (
            ('codex', 5, 22, 24, 'left'), ('claude', 301, 243, 260, 'right')):
        row = _row(snapshot, provider)
        remaining, _, old, reset = remaining_reading(row)
        count, old_count = banked_hearts(row)
        _life_meter(d, meter, remaining)

        # The gold-framed item box carries the number instead of an item icon.
        d.rectangle((box, 25, box + 54, 52), fill='#33291e', outline='#171a18')
        d.rectangle((box + 2, 27, box + 52, 50), fill='#dcb94d')
        d.rectangle((box + 4, 29, box + 50, 48), fill='#17251e')
        d.line((box + 5, 29, box + 49, 29), fill='#fff2a9')
        credit = exhausted_credits(row)
        value = (format_balance(credit) if credit is not None else '--' if remaining is None
                 else '<1%' if 0 < remaining < 1 else f'{round(remaining)}%')
        if credit is not None:
            d.text((box + 6, 28), 'CR', font=face('press-start-2p.ttf', 6), fill='#e8c96e')
            size = 12
            while size > 5 and face('oxanium.woff2', size).getlength(value) > 42:
                size -= 1
            d.text((box + 27, 35), value, anchor='mt', font=face('oxanium.woff2', size), fill='#fff6dd')
        else:
            size = 10
            while size > 7 and face('press-start-2p.ttf', size).getlength(value) > 43:
                size -= 1
            d.text((box + 27, 32), value, anchor='mt', font=face('press-start-2p.ttf', size), fill='#fff7e1')

        _hearts(d, hearts, 56, count, old_count or old)
        x = 22 if edge == 'left' else 298
        anchor = 'la' if edge == 'left' else 'ra'
        for y, text, size in ((6, provider.upper(), 8), (67, 'RST ' + reset.upper(), 7)):
            d.text((x, y), text, anchor=anchor, font=face('press-start-2p.ttf', size),
                   fill='#fff9e5', stroke_width=1, stroke_fill='#183126')
        if provider == 'claude' and row.get('status') == 'ok':
            _pace(d, 240, 82, session_pace(row))


def _fairy_frame(i):
    im = Image.new('RGBA',(7,7))
    d = ImageDraw.Draw(im)
    glow = ('#6ac5e1','#bdf3f5','#fff9d0','#bdf3f5')[i]
    d.point((3,0),fill=glow); d.line((3,2,3,4),fill='#ffffff')
    d.line((1,3,5,3),fill=glow)
    d.point((0,2 if i % 2 else 4),fill='#72bae1')
    d.point((6,4 if i % 2 else 2),fill='#72bae1')
    return im


def _butterfly_frame(i):
    im = Image.new('RGBA', (16, 5))
    d = ImageDraw.Draw(im)
    x = 4 + i
    d.point((x, 2), fill='#423c37')
    d.point((x - 1, 1 if i % 2 else 2), fill='#ffe9a2')
    d.point((x + 1, 1 if i % 2 else 2), fill='#ffe9a2')
    return im


def _action_frame(walk, phase):
    """One complete pose keeps the sword, bush and reward in one safe redraw box."""
    im = Image.new('RGBA', (38, 30))
    positions = (0, 2, 4, 4, 4, 4, 2, 0)
    poses = (0, 1, 2, 2, 3, 1, 4, 5)
    im.alpha_composite(walk[poses[phase]], (positions[phase], 4))
    d = ImageDraw.Draw(im)
    if phase <= 3:
        # A compact clipped bush, with the same hard-edged pixels as the land.
        d.polygon([(28, 23), (28, 19), (30, 19), (30, 17), (34, 17),
                   (34, 18), (37, 18), (37, 26), (29, 26)], fill='#1d5c35')
        d.polygon([(29, 21), (31, 18), (34, 19), (35, 18), (37, 20),
                   (36, 24), (32, 23), (30, 25)], fill='#51a84b')
        d.line((30, 20, 32, 19), fill='#a7d777')
        d.point((35, 21), fill='#c4e590')
    elif phase in (4, 5, 6):
        d.line((28, 26, 37, 26), fill='#52713c')
        d.line((30, 24, 32, 25), fill='#80b253')
        if phase == 4:
            for x, y, c in ((28, 16, '#a7d777'), (34, 13, '#5cb64f'),
                            (37, 17, '#9bd66f'), (33, 22, '#4a9b43')):
                d.rectangle((x, y, min(37, x + 1), y + 1), fill=c)
        else:
            # A small green gem rises out of the cut bush, then glints.
            y = 15 if phase == 5 else 11
            d.polygon([(33, y), (36, y + 2), (36, y + 5), (33, y + 7),
                       (30, y + 5), (30, y + 2)], fill='#216e4c', outline='#f2e9ac')
            d.polygon([(33, y + 1), (35, y + 3), (33, y + 6), (31, y + 3)], fill='#61e7a0')
            d.point((32, y + 2), fill='#f6ffe5')
            if phase == 6:
                d.point((28, y + 2), fill='#fff6bd')
                d.point((37, y - 1), fill='#fff6bd')
    else:
        # The sprout reappears before the loop repeats, avoiding a hard pop.
        d.line((30, 26, 36, 26), fill='#52713c')
        d.polygon([(31, 26), (30, 23), (32, 23), (33, 25), (34, 22),
                   (36, 23), (35, 26)], fill='#72c462')
    if phase in (3, 4):
        # Two clear sword poses: wind-up, then the bright horizontal cut.
        if phase == 3:
            d.line((22, 17, 27, 10), fill='#263d47', width=3)
            d.line((22, 17, 27, 10), fill='#c6f5f1')
        else:
            d.line((22, 18, 30, 18), fill='#263d47', width=3)
            d.line((22, 17, 30, 17), fill='#e8ffff')
            d.line((24, 19, 30, 19), fill='#7dcbe1')
        d.line((22, 16, 22, 20), fill='#e6b956')
    return im



def _sprites(anim_frames=8, local=None):
    if local:
        # Each changing region has its own complete, independent loop.
        action_steps = ((0,) * 8 + (1, 2, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5,
                                    6, 5, 6, 7, 7) + (0,) * 7)
        guard_steps = tuple(i for i in range(8) for _ in range(2)) + \
                      tuple(i for i in reversed(range(8)) for _ in range(2))
        action, guard = local[1:]
        if anim_frames < 8:
            action = tuple(action[i] for i in (0, 2, 5, 7))
            guard = tuple(guard[i] for i in (0, 2, 4, 6))
            reduced = (0, 0, 1, 1, 1, 2, 3, 3)
            action_steps = tuple(reduced[i] for i in action_steps)
            guard_steps = tuple(i // 2 for i in guard_steps)
        return [{'x':136, 'y':64, 'frames':action,
                 'script':[(i, 0, 0) for i in action_steps], 'step_ms':80},
                {'x':136, 'y':192, 'frames':guard,
                 'script':[(i, 0, 0) for i in guard_steps], 'step_ms':80}]

    sprites = []
    walk = _walk()
    if walk:
        full = anim_frames >= 8
        frames = [_action_frame(walk, i) for i in range(8)]
        steps = (0, 0, 0, 1, 1, 2, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6,
                 6, 6, 6, 7, 7, 7, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        if not full:
            frames = [frames[i] for i in (0, 2, 4, 6)]
            reduced = (0, 0, 1, 1, 2, 2, 3, 3)
            steps = tuple(reduced[i] for i in steps)
        sprites.append({'x':120, 'y':154, 'frames':frames,
                        'script':[(i, 0, 0) for i in steps], 'step_ms':200})
    positions = (0,1,2,3,4,3,2,1,0,-1,-2,-3,-4,-3,-2,-1)
    sprites.append({'x':98,'y':136,'frames':[_fairy_frame(i) for i in range(4)],
                    'script':[(i % 4,dx,0) for i,dx in enumerate(positions)],'step_ms':200})
    sprites.append({'x':22,'y':124,'frames':[_butterfly_frame(i) for i in range(4)],
                    'script':[(i % 4,0,0) for i in range(8)],'step_ms':400})
    return sprites


def render_quest(snapshot, animated=False, anim_frames=8):
    """Render live readings over local art when available, or the bundled scene."""
    local = _local_art()
    image = local[0].copy() if local else _landscape().resize(SIZE, Image.Resampling.NEAREST)
    _hud(image, snapshot)
    sprites = _sprites(anim_frames, local)
    if animated:
        return image, board_anim.encode(sprites=sprites)
    paint_first_frame(image, sprites)
    return image
