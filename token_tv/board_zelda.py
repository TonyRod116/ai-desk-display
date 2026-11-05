"""A 16-bit quest scene with original art and the board's real usage readings.

An optional locally supplied character strip stays on the owner's computer;
the bundled adventurer, landscape and gauges are original drawings.
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
SIZE = (320, 240)
HEART = ('.##.##.', '#######', '#######', '.#####.', '..###..', '...#...')


def art_version():
    try:
        stat = ART.stat()
        version = (stat.st_mtime_ns, stat.st_size)
        return version if ART.is_file() and _cached_walk(ART, *version) else None
    except OSError:
        return None


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
    version = art_version()
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


def _tree(d, x, y, variant=0):
    """Small multi-layer forest canopy, with hard pixels and deep shadows."""
    dark, shade, leaf, bright = (
        ('#123c30','#176345','#319257','#79cb6c'),
        ('#143b36','#255a4c','#397c59','#9acb75'),
        ('#193d36','#2a694d','#4c9d61','#b0d887'),
    )[variant % 3]
    d.rectangle((x + 8, y + 14, x + 15, y + 25), fill='#463527')
    d.rectangle((x + 10, y + 14, x + 12, y + 23), fill='#a16e3c')
    d.polygon([(x + 1,y + 15),(x + 1,y + 7),(x + 4,y + 7),(x + 4,y + 3),
               (x + 8,y + 3),(x + 8,y + 1),(x + 17,y + 1),(x + 17,y + 3),
               (x + 21,y + 3),(x + 21,y + 7),(x + 24,y + 7),(x + 24,y + 16),
               (x + 21,y + 16),(x + 21,y + 19),(x + 17,y + 19),(x + 17,y + 21),
               (x + 7,y + 21),(x + 7,y + 19),(x + 3,y + 19),(x + 3,y + 16)], fill=dark)
    d.polygon([(x + 2,y + 14),(x + 3,y + 7),(x + 6,y + 7),(x + 6,y + 4),
               (x + 10,y + 2),(x + 17,y + 3),(x + 20,y + 5),(x + 22,y + 9),
               (x + 22,y + 15),(x + 18,y + 18),(x + 14,y + 17),(x + 11,y + 19),
               (x + 6,y + 17)], fill=shade)
    d.polygon([(x + 3,y + 12),(x + 5,y + 7),(x + 9,y + 6),(x + 10,y + 3),
               (x + 15,y + 3),(x + 17,y + 5),(x + 21,y + 7),(x + 21,y + 12),
               (x + 18,y + 14),(x + 14,y + 13),(x + 11,y + 16),(x + 7,y + 15)], fill=leaf)
    for ox, oy in ((6,8),(11,4),(16,6),(8,12),(16,11),(4,13)):
        d.line((x + ox,y + oy,x + ox + 2,y + oy - 1),fill=bright)
        d.point((x + ox + 3,y + oy + 1),fill='#216b48')
    if variant:
        d.point((x + 13,y + 8),fill='#e6bd68')


def _flower(d, x, y, colour):
    d.point((x,y + 2),fill='#216c43')
    for dx,dy in ((0,0),(-1,1),(1,1),(0,2)):
        d.point((x + dx,y + dy),fill=colour)
    d.point((x,y + 1),fill='#fff3a0')


@lru_cache(maxsize=1)
def _landscape():
    im = Image.new('RGB', (160, 120), '#75ba68')
    d = ImageDraw.Draw(im)
    rnd = random.Random(732)
    # A mottled lawn with a meandering sand path, then a river under a bridge.
    for _ in range(280):
        x, y = rnd.randrange(160), rnd.randrange(25,120)
        color = rnd.choice(('#69ad5d','#8bc879','#559f5b','#a0d68b'))
        d.point((x,y), fill=color)
        if x % 3 == 0: d.point((x + 1,y),fill=color)
    d.polygon([(59,37),(101,37),(94,65),(99,89),(114,119),(43,119),(61,87),(66,65)],fill='#ccbd80')
    for _ in range(90):
        x, y = rnd.randrange(49,110), rnd.randrange(40,120)
        if im.getpixel((x,y)) == (204,189,128):
            d.point((x,y),fill=rnd.choice(('#b4a76d','#e1d29d','#d6c98f')))
    d.polygon([(0,54),(25,53),(42,56),(60,54),(78,56),(96,53),(116,55),(138,52),(159,54),
               (159,72),(144,74),(121,72),(103,75),(82,73),(62,75),(44,73),(23,75),(0,72)],fill='#174c68')
    d.polygon([(0,57),(20,56),(42,59),(65,57),(86,58),(105,56),(128,58),(144,55),(159,57),
               (159,69),(141,71),(120,69),(103,72),(80,70),(60,72),(40,70),(21,72),(0,69)],fill='#318db2')
    for x,y in ((3,61),(17,67),(31,62),(46,68),(107,63),(119,69),(135,61),(149,67)):
        d.line((x,y,x + 7,y),fill='#8fd9cf')
        d.line((x + 3,y + 2,x + 9,y + 2),fill='#5cb9c4')
    # The shrine gives the quest a destination above the river.
    d.rectangle((60,32,100,53),fill='#394b4a')
    d.polygon([(57,36),(80,26),(103,36),(101,39),(59,39)],fill='#253e3b')
    d.polygon([(61,35),(80,28),(99,35),(99,37),(61,37)],fill='#84977b')
    d.line((64,35,80,29,96,35),fill='#d3d7a3')
    d.rectangle((63,39,97,53),fill='#9aa88c')
    d.rectangle((65,40,69,52),fill='#d6d9b2')
    d.rectangle((91,40,95,52),fill='#ced7b2')
    d.rectangle((74,41,86,53),fill='#263d35')
    d.rectangle((76,43,84,52),fill='#132c2a')
    d.polygon([(80,31),(77,35),(83,35)],fill='#f6d563')
    d.polygon([(76,36),(73,40),(79,40)],fill='#e5b640')
    d.polygon([(84,36),(81,40),(87,40)],fill='#e5b640')
    for xx in (62,70,88,96):
        d.point((xx,49),fill='#647c69')
    for y in (42,46,50):
        d.line((70,y,73,y),fill='#6d8979')
        d.line((87,y,90,y),fill='#647e6d')
        d.point((71 + (y % 3),y - 1),fill='#e3e4bb')
    # Weathered stones and small lanterns mark the entrance.
    for x in (55,100):
        d.rectangle((x,45,x + 4,53),fill='#526b5d')
        d.rectangle((x + 1,46,x + 3,51),fill='#cbd7a9')
        d.point((x + 2,48),fill='#fcdf73')
    # Stout trees overlap the rear edges; foreground trees frame the clearing.
    for x,y,v in ((-8,25,0),(12,28,1),(32,25,2),(111,25,1),(133,27,2),(149,25,0),
                  (-9,78,1),(6,92,0),(139,78,2),(149,96,1)):
        _tree(d,x,y,v)
    # Reeds and irregular stepping stones trace the river banks.
    for x in (4,13,25,37,48,112,126,139,154):
        y = 53 + (x % 3)
        d.line((x,y,x,y - 3),fill='#336b46')
        d.line((x + 1,y - 1,x + 2,y - 4),fill='#b9d88b')
    for x in (12,27,39,109,125,143,153):
        y = 73 + (x % 2)
        d.line((x,y,x + 5,y),fill='#c8dd9b')
        d.point((x + 2,y - 1),fill='#356c53')
    # Bridge boards, rail posts and their shadows are clearly separated from water.
    d.polygon([(63,53),(97,53),(100,75),(60,75)],fill='#46382e')
    d.rectangle((65,54,95,74),fill='#9a633b')
    for y in range(55,75,4):
        d.line((65,y,95,y),fill='#dbab68')
        d.line((65,y + 2,95,y + 2),fill='#75492d')
        for x in (68,92):d.point((x,y + 1),fill='#e7c78e')
    for x in (62,96):
        d.rectangle((x,51,x + 2,76),fill='#3c352a')
        d.line((x + 1,52,x + 1,75),fill='#d0a15d')
        for y in (51,61,72):d.rectangle((x - 1,y,x + 3,y + 2),fill='#e1bd75')
    # A few flowers, stepping stones and little grass tufts keep the foreground alive.
    for x,y,c in ((25,76,'#fff1bd'),(47,105,'#ff8cb1'),(35,85,'#ffea84'),(119,82,'#f9edbe'),
                  (127,102,'#ffc3d2'),(104,112,'#fff2a5'),(21,112,'#eef0df')):
        _flower(d,x,y,c)
    # Different bushes, mushrooms and a weathered sign break up the clearing.
    for x,y in ((28,94),(113,94),(43,77),(112,76),(29,114),(128,113)):
        d.ellipse((x,y,x + 9,y + 5),fill='#276d48')
        d.ellipse((x + 1,y,x + 4,y + 3),fill='#64ae60')
        d.ellipse((x + 5,y - 1,x + 8,y + 3),fill='#79c77a')
        d.point((x + 3,y + 1),fill='#c7e88b')
    for x,y in ((16,86),(135,91),(38,110)):
        d.rectangle((x + 1,y + 2,x + 2,y + 4),fill='#f5ddb0')
        d.polygon([(x,y + 2),(x + 1,y),(x + 3,y),(x + 4,y + 2)],fill='#df655d')
        d.point((x + 1,y + 1),fill='#fff2ce')
    d.rectangle((47,79,48,88),fill='#5c472f')
    d.rectangle((43,78,53,83),fill='#684b2d')
    d.rectangle((44,79,52,82),fill='#dfb674')
    d.line((46,80,50,80),fill='#8c673e')
    d.line((46,82,49,82),fill='#8c673e')
    for x,y in ((58,100),(101,96),(54,114),(105,105)):
        d.rectangle((x,y,x + 4,y + 2),fill='#9c9976');d.line((x,y,x + 3,y),fill='#eee0ae')
    return im


def _crystal(im, cx, top, remaining, color):
    d = ImageDraw.Draw(im)
    d.ellipse((cx - 10,top + 22,cx + 10,top + 26),fill='#284a35')
    d.rectangle((cx - 8,top + 19,cx + 8,top + 23),fill='#374c42')
    d.rectangle((cx - 7,top + 19,cx + 7,top + 21),fill='#a7b5a0')
    shape = [(cx,top),(cx + 7,top + 6),(cx + 6,top + 15),(cx,top + 20),
             (cx - 6,top + 15),(cx - 7,top + 6)]
    d.polygon(shape,fill='#263c42',outline='#d0d8b4')
    if remaining is None:
        d.point((cx,top + 9),fill='#a2b1ae')
        return
    mask = Image.new('L', im.size)
    md = ImageDraw.Draw(mask)
    md.polygon(shape,fill=255)
    cutoff = top + 20 - round(19 * max(0,min(100,remaining)) / 100)
    md.rectangle((cx - 8,top,cx + 8,cutoff),fill=0)
    layer = Image.new('RGB', im.size, color)
    im.paste(layer,(0,0),mask)
    d.line((cx - 4,top + 7,cx,top + 3,cx + 4,top + 7),fill='#f6f6d4')
    d.line((cx,top + 4,cx,top + 18),fill='#a9d9bd')


def _hearts(d, left, top, count, old):
    for i in range(3):
        active = count is not None and i < count
        for y,row in enumerate(HEART):
            for x,cell in enumerate(row):
                if cell != '#': continue
                edge = any(not (0 <= y + dy < 6 and 0 <= x + dx < 7)
                           or HEART[y + dy][x + dx] != '#'
                           for dx,dy in ((-1,0),(1,0),(0,-1),(0,1)))
                if active or edge:
                    d.point((left + i * 9 + x, top + y),fill=('#ff8982' if active and y == 1 else '#ed4e58') if active else '#5d6070')
    if count is None or old:
        d.point((left + 27,top + 4),fill='#a8a6a1')
    if count is not None and count > 3:
        d.text((left + 28,top - 1),'+',font=face('press-start-2p.ttf',7),fill='#f7daa0')


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


def _hud(im, snapshot):
    d = ImageDraw.Draw(im)
    d.rectangle((0,0,319,48),fill='#132b39')
    d.rectangle((0,45,319,48),fill='#49706d')
    d.line((0,45,319,45),fill='#c6d6a7')
    d.line((159,3,159,43),fill='#577870')
    for provider, x in (('codex',0),('claude',160)):
        row = _row(snapshot,provider)
        remaining, _, old, reset = remaining_reading(row)
        count, old_count = banked_hearts(row)
        _hearts(d,x + 118,5,count,old_count or old)
        d.text((x + 6,3),provider.upper(),font=face('press-start-2p.ttf',8),fill='#f3e5bb')
        credit = exhausted_credits(row)
        value = ('CR ' + format_balance(credit)) if credit is not None else ('--' if remaining is None else '<1%' if 0 < remaining < 1 else f'{round(remaining)}%')
        size = 14 if credit is None else 10
        while size > 7 and face('press-start-2p.ttf',size).getlength(value) > 85:
            size -= 1
        d.text((x + 6,14),value,font=face('press-start-2p.ttf',size),fill='#fff5c9')
        d.text((x + 6,35),'RST ' + reset.upper(),font=face('press-start-2p.ttf',7),fill='#c4dbc7')
        if provider == 'claude' and row.get('status') == 'ok':
            _pace(d,x + 94,19,session_pace(row))


def _fairy_frame(i):
    im = Image.new('RGBA',(7,7))
    d = ImageDraw.Draw(im)
    glow = ('#6ac5e1','#bdf3f5','#fff9d0','#bdf3f5')[i]
    d.point((3,0),fill=glow); d.line((3,2,3,4),fill='#ffffff')
    d.line((1,3,5,3),fill=glow)
    d.point((0,2 if i % 2 else 4),fill='#72bae1')
    d.point((6,4 if i % 2 else 2),fill='#72bae1')
    return im


def _water_frame(i):
    im = Image.new('RGBA',(16,5))
    d = ImageDraw.Draw(im)
    d.line((i,1,i + 7,1),fill='#b6ece4')
    d.line((4 - i,3,10 - i,3),fill='#74d3d2')
    return im


def _sprites(anim_frames=8):
    sprites = []
    walk = _walk()
    if walk:
        full = anim_frames >= 8
        if not full:
            walk = (walk[0], walk[1], walk[4], walk[5])
        poses = 4 if full else 2
        offsets = list(range(0,32,2)) + list(range(32,0,-2))
        sprites.append({'x':120,'y':160,'frames':walk,
                        'script':[(i % poses + (poses if i >= 16 else 0),dx,0) for i,dx in enumerate(offsets)],
                        'step_ms':200})
    positions = (0,1,2,3,4,3,2,1,0,-1,-2,-3,-4,-3,-2,-1)
    sprites.append({'x':98,'y':136,'frames':[_fairy_frame(i) for i in range(4)],
                    'script':[(i % 4,dx,0) for i,dx in enumerate(positions)],'step_ms':200})
    sprites.append({'x':22,'y':124,'frames':[_water_frame(i) for i in range(4)],
                    'script':[(i % 4,0,0) for i in range(8)],'step_ms':400})
    return sprites


def render_quest(snapshot, animated=False, anim_frames=8):
    """Render a compact, live game HUD and animate only small independent areas."""
    world = _landscape().copy()
    for provider, x, color in (('codex',38,'#eacb55'),('claude',122,'#76dcf0')):
        _crystal(world,x,79,remaining_reading(_row(snapshot,provider))[0],color)
    image = world.resize(SIZE, Image.Resampling.NEAREST)
    _hud(image,snapshot)
    sprites = _sprites(anim_frames)
    if animated:
        return image, board_anim.encode(sprites=sprites)
    paint_first_frame(image,sprites)
    return image
