"""Page 6 of the touch board: "VERSUS", the usage as a 90s fighting-game screen (320x240).

Codex (left, yellow) against Claude (right, stone), the way a Neo Geo / Street Fighter II screen draws it:

- the two life bars at the top are the quota left of each week, anchored at the centre and draining
  towards the screen edges, with the big percentage under them;
- the three short reserve bars are the saved resets (lives), with ? when unknown and OLD when stale;
- Claude's five-hour session is the "power meter" under its life bar: two lines of five parts, quota left
  on top and time left below, in the colour of Claude's bar, with no marks or numbers. An unknown session
  draws nothing at all, so unknown never reads as empty;
- the reset of each week is at the bottom, and the two fighters stand on a night-city stage.

Everything is drawn on a 160x120 canvas with no anti-aliasing and scaled 2x (so each pixel is a hard 2x2
block), and the text is written afterwards at the panel's own resolution in Press Start 2P without
smoothing. Flat colour bands only: no 1-pixel line patterns, which made the panel shimmer on the Game Boy
pages. Nothing here is copied from the Pixel Retro face: the fighters, the stage and the HUD are new.
"""
import math

from PIL import Image, ImageColor, ImageDraw, ImageFilter, ImageOps

from token_tv.board_art import CLAUDE, CODEX, _row
from token_tv import board_reset_icons as icons
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

LW, LH, K = 160, 120, 2          # the logical canvas and the size of one logical pixel
SCENE_TOP, SCENE_HEIGHT, STEP_MS = 66, 30, 160
FAR_PERIOD, NEAR_PERIOD = 48, 72
FAR_STEP, NEAR_STEP = FAR_PERIOD // 4, NEAR_PERIOD // 4
INK = '#06050f'                  # outline / shadow / text edge
CREAM, PLUM, PLUM_D = '#f6e9b8', '#2a1233', '#150a22'
STONE = {'hi': '#f1ece0', 'mid': '#cfc6b4', 'lo': '#8a8274', 'dk': '#4a4338'}
GOLD = {'hi': '#fff1a0', 'mid': '#ffd23f', 'lo': '#c98f00', 'dk': '#6b4a00'}
# Shared by other pages; VS itself uses reserve bars instead.
HEART = ('.##.##.', '#######', '#######', '.#####.', '..###..', '...#...')
HEALTH_GREEN = {'hi': '#bdffc0', 'mid': '#45d978', 'lo': '#168548'}
HEALTH_AMBER = {'hi': '#ffe9a1', 'mid': '#ffb73d', 'lo': '#b56821'}
HEALTH_RED = {'hi': '#ffb4ac', 'mid': '#f64b59', 'lo': '#9c243f'}


def _px(draw, x0, y0, x1, y1, fill):
    draw.rectangle((x0, y0, x1, y1), fill=fill)


def _disc(draw, cx, cy, r, fill):
    for dy in range(-r, r + 1):
        w = round(math.sqrt(max(0, r * r - dy * dy)))
        draw.rectangle((cx - w, cy + dy, cx + w, cy + dy), fill=fill)


def _landmarks(d):
    # The distant facades continue behind the moving layer, down to the tracks.
    # Gaps between moving silhouettes reveal architecture rather than a flat band.
    for x0,x1,top,body,light in (
            (0,13,60,'#39475e','#d9ae7e'),(18,34,60,'#4b426c','#dcacaa'),
            (40,55,60,'#484268','#efc790'),(55,62,64,'#57456d','#a28fad'),
            (96,106,60,'#394b69','#70aeb6'),(107,112,60,'#233449','#cb99b2'),
            (119,126,60,'#5c456d','#edbf98'),(133,140,60,'#5c456d','#a28fad'),
            (146,159,60,'#63475d','#caa57b')):
        d.rectangle((x0,top,x1,88),fill=body)
        for y in range(66,88,4):
            for x in range(x0+2,x1,4):d.line((x,y,x,y+1),fill=light)
    # Seven individually composed silhouettes, not scaled copies of a tower.
    # Port warehouse: sawtooth roof, steel braces and a water tank.
    d.polygon([(0,59),(0,51),(4,48),(4,51),(8,48),(8,51),(13,48),(13,65),(0,65)], fill='#39475e')
    d.line([(0,51),(4,48),(4,51),(8,48),(8,51),(13,48)],fill='#95a0ae')
    for x in (2,6,10):
        d.rectangle((x,54,x+1,57),fill='#d9ae7e')
        d.line((x,59,x+2,62),fill='#64708a')
    # Art-deco spire: tiered crown, copper beacon and staggered lit offices.
    d.polygon([(18,64),(18,49),(21,49),(21,45),(24,45),(24,41),(28,41),(28,45),(31,45),(31,49),(34,49),(34,64)],fill='#4b426c')
    d.line((26,37,26,41),fill='#a3b3c4');d.point((26,37),fill='#ffc78e')
    d.line([(18,49),(21,49),(21,45),(24,45),(24,41),(28,41)],fill='#9e88b2')
    for y in range(47,63,3):
        for x in range(23,30,3):
            d.line((x,y,x,y+1),fill='#dcacaa' if (x+y)%4 else '#796089')
    # Observatory: dome, rim, central slit and low annex.
    d.rectangle((40,52,55,64),fill='#484268')
    d.pieslice((40,42,54,56),180,360,fill='#72849a')
    d.line((47,43,47,48),fill='#cad9d2')
    d.line((39,50,55,50),fill='#d2b7bb')
    for x in (42,47,52):d.rectangle((x,54,x+1,57),fill='#efc790')
    d.rectangle((55,58,62,65),fill='#57456d')
    # Sloping glass offices, split faces and roof garden.
    d.polygon([(96,64),(96,51),(107,43),(112,47),(112,65)],fill='#394b69')
    d.polygon([(107,43),(112,47),(112,65),(107,64)],fill='#233449')
    d.line((96,51,107,43),fill='#94b6c0')
    for y in (52,56,60):
        d.line((98,y,105,y-3),fill='#70aeb6')
        d.point((110,y),fill='#cb99b2')
    # Twin towers with a suspended illuminated skybridge.
    for x,top in ((119,40),(133,46)):
        d.rectangle((x,top,x+7,65),fill='#5c456d')
        d.rectangle((x+2,top-2,x+5,top-1),fill='#9b6784')
        d.line((x,top,x,64),fill='#bd8f9e')
        for y in range(top+3,63,3):
            d.point((x+2,y),fill='#edbf98');d.point((x+5,y),fill='#a28fad')
    d.rectangle((126,52,133,55),fill='#7a6289')
    d.line((127,53,132,53),fill='#ffc798')
    # Radio mast, satellite dish and low red-brick utility block.
    d.rectangle((146,55,159,65),fill='#63475d')
    d.line((148,54,153,42),fill='#af94a2');d.line((158,54,153,42),fill='#af94a2')
    d.line((150,49,156,49),fill='#af94a2');d.point((153,41),fill='#ffb98b')
    d.arc((145,49,151,54),0,180,fill='#d5bbb4')
    for x in (149,154):d.rectangle((x,58,x+2,59),fill='#caa57b')


def _city(d, phase):
    # Wider blocks fit distinct architecture, not the same tower every 24px.
    # Each advances by exactly a quarter block: the fourth-to-first step
    # remains a forward translation, with no jump back to the start.
    for x in range(-FAR_PERIOD*2, LW+FAR_PERIOD*2, FAR_PERIOD):
        x-=phase*FAR_STEP
        # Copper-crowned art-deco tower, with its narrow shadowed side.
        d.polygon([(x,88),(x,69),(x+2,69),(x+2,67),(x+4,66),(x+6,67),(x+6,69),(x+8,69),(x+8,88)],fill='#665c86')
        d.line((x+4,66,x+4,69),fill='#efbaac')
        d.line((x,69,x,88),fill='#b89bb4')
        d.rectangle((x+5,70,x+7,88),fill='#463d66')
        for y in range(71,88,3):
            d.line((x+2,y,x+3,y),fill='#d7b0aa')
            d.point((x+6,y+1),fill='#92a9bb')
        d.rectangle((x+12,74,x+21,88),fill='#885572')
        d.polygon([(x+12,74),(x+12,72),(x+15,72),(x+15,70),(x+18,70),(x+18,74)],fill='#b87987')
        d.line((x+13,75,x+20,75),fill='#edbd9f')
        for y in (78,82,86):
            d.line((x+13,y,x+15,y),fill='#b5b2c4')
            d.point((x+20,y),fill='#e6a48b')
        # Narrow stone clock tower: spire, clock face and tall paired windows.
        d.polygon([(x+25,88),(x+25,70),(x+27,70),(x+27,68),(x+29,66),
                   (x+31,68),(x+31,70),(x+33,70),(x+33,88)],fill='#526c83')
        d.line((x+29,66,x+29,69),fill='#efce93')
        d.rectangle((x+27,71,x+31,75),fill='#b6bcc0')
        d.line((x+29,72,x+29,73),fill='#324253');d.point((x+30,74),fill='#324253')
        for y in (78,82,86):
            for xx in (27,30):d.line((x+xx,y,x+xx,y+1),fill='#a1c4c9')
        # Broad rounded glass building: horizontal floors and a darker flank.
        d.ellipse((x+37,70,x+46,76),fill='#78959b')
        d.rectangle((x+37,73,x+46,88),fill='#395a70')
        d.rectangle((x+44,74,x+46,88),fill='#29384f')
        for y in (74,78,82,86):
            d.line((x+38,y,x+43,y),fill='#91b6bb')
        d.line((x+39,71,x+44,71),fill='#b8cbbd')
    for x in range(-NEAR_PERIOD*2, LW+NEAR_PERIOD*2, NEAR_PERIOD):
        x-=phase*NEAR_STEP
        # Cantilevered green-glass offices with inset balconies.
        d.polygon([(x,88),(x,73),(x+2,73),(x+2,70),(x+13,70),(x+13,73),(x+11,73),(x+11,88)],fill='#144354')
        d.line((x+2,70,x+13,70),fill='#58d6cf')
        d.line((x+3,71,x+12,71),fill='#b5f3dc')
        d.rectangle((x+8,74,x+10,88),fill='#0d293e')
        for y in (75,79,83,87):
            d.line((x+1,y,x+6,y),fill='#65adb6')
            d.line((x+2,y+1,x+4,y+1),fill='#f8cc88')
        # Brick loft with a sawtooth roof and lit workshop windows.
        d.polygon([(x+17,88),(x+17,78),(x+21,74),(x+21,78),
                   (x+26,74),(x+26,78),(x+30,75),(x+30,88)],fill='#734858')
        d.line([(x+17,78),(x+21,74),(x+21,78),(x+26,74),(x+26,78),(x+30,75)],fill='#c18c8e')
        for y in (80,84):
            for xx in (19,24,28):
                d.rectangle((x+xx,y,x+xx+1,y+2),fill='#edbc7c' if xx!=24 else '#a87d77')
        d.line((x+18,83,x+29,83),fill='#482d47')
        # Slim blue hotel with a projecting neon sign and rooftop antenna.
        d.rectangle((x+34,73,x+41,88),fill='#293c59')
        d.rectangle((x+36,71,x+39,72),fill='#6d859c')
        d.line((x+38,70,x+38,71),fill='#eab9b4')
        d.line((x+34,73,x+41,73),fill='#a5b4cc')
        d.rectangle((x+40,76,x+43,85),fill='#b53e75')
        for y in (77,80,83):d.line((x+41,y,x+42,y),fill='#ffceab')
        for y in (76,80,84):d.line((x+35,y,x+37,y),fill='#76d5d7')
        # Old utility block with cylindrical water tank and exposed supports.
        d.rectangle((x+47,81,x+57,88),fill='#59405b')
        d.line((x+47,81,x+57,81),fill='#b77b8d')
        for xx in (49,54):d.line((x+xx,80,x+xx,75),fill='#bd998a')
        d.rectangle((x+48,72,x+55,76),fill='#697b89')
        d.ellipse((x+48,70,x+55,73),fill='#b7b6ab')
        d.line((x+50,74,x+50,76),fill='#d1d4bf')
        for xx in (49,54):d.rectangle((x+xx,84,x+xx+1,86),fill='#efba75')
        # Terraced corner house, warm windows and an exterior fire escape.
        d.polygon([(x+61,88),(x+61,77),(x+63,77),(x+63,74),(x+68,74),
                   (x+68,78),(x+70,78),(x+70,88)],fill='#3e676c')
        d.line((x+62,77,x+69,77),fill='#91b9ae')
        d.line((x+63,74,x+68,74),fill='#d3c398')
        for y in (79,83):d.rectangle((x+63,y,x+65,y+1),fill='#ffcf92')
        d.line((x+68,79,x+68,87),fill='#142f41')
        for y in (80,83,86):d.line((x+67,y,x+70,y),fill='#91a9a4')


# ---- the stage -------------------------------------------------------------------------------------------

def _roof(d, phase=0):
    # One close-up roof fills the foreground. Passenger windows made this
    # read as a second miniature train rather than the fighters' platform.
    d.rectangle((0,87,159,106),fill='#101c30')
    for left,right in ((-12,171),):
        d.polygon(((left,94),(left+5,89),(left+12,87),(right-11,87),
                   (right-4,89),(right,94),(right,97),(left,97)),fill='#52738b')
        d.line((left+12,87,right-11,87),fill='#c5dbd6')
        d.line((left+6,89,right-5,89),fill='#85a5b2')
        d.rectangle((left+1,92,right-1,95),fill='#3b5a76')
        for x in range(left+10,right-5,12):
            d.line([(x,88),(x-2,90),(x-3,94)],fill='#28425f')
            d.line([(x+1,88),(x-1,90),(x-2,94)],fill='#7596a7')
        d.line((left,96,right,96),fill='#cadbd0')
        d.rectangle((left,97,right,99),fill='#b96f3c')
        d.line((left,97,right,97),fill='#ffd27b')
        d.rectangle((left,100,right,105),fill='#294660')
        d.line((left,101,right,101),fill='#395c75')
        d.line((left,103,right,103),fill='#1c344e')
        d.line((left,106,right,106),fill='#152b42')
    for x in (65,86):
        d.rectangle((x,88,x+15,92),fill='#183049',outline='#91aeb8')
        for xx in range(x+3,x+14,3):d.line((xx,89,xx,91),fill='#4e7186')
    # Reflections travel along the metal; structural ribs never slide.
    for x in range(-36,196,36):
        x-=phase*9
        d.line((x,95,x+6,95),fill='#8ce7dd')
        d.line((x+7,95,x+9,95),fill='#5ca5bd')


def _stage(d):
    for y,c in ((25,'#101529'),(34,'#1b1b38'),(43,'#302047'),(51,'#432351')):
        d.rectangle((0,y,159,119),fill=c)
    d.ellipse((68,29,91,52),fill='#ffe0a0')
    d.ellipse((73,33,77,37),fill='#dcb579')
    _landmarks(d)
    d.rectangle((0,102,159,119),fill='#080917')
    d.line((0,103,159,103),fill='#284b64')
    _roof(d)


def _scene(phase):
    im=Image.new('RGBA',(160,120),'#150a22')
    d=ImageDraw.Draw(im);_stage(d)
    _city(d,phase)
    _roof(d,phase)
    return im.crop((0,SCENE_TOP,160,SCENE_TOP+SCENE_HEIGHT))


# ---- the fighters ----------------------------------------------------------------------------------------

def _outline(sprite, colour=INK):
    padded = Image.new('RGBA', (sprite.width + 2, sprite.height + 2), (0, 0, 0, 0))
    padded.paste(sprite, (1, 1))
    alpha = padded.split()[3].point(lambda v: 255 if v else 0)
    ring = ImageChops_subtract(alpha.filter(ImageFilter.MaxFilter(3)), alpha)
    edge = Image.new('RGBA', padded.size, colour)
    edge.putalpha(ring)
    edge.alpha_composite(padded)
    return edge


def ImageChops_subtract(a, b):   # noqa: N802 - tiny wrapper so the import list above stays short
    from PIL import ImageChops
    return ImageChops.subtract(a, b)


def _rounded(draw, x0, y0, x1, y1, fill, hi=None, lo=None):
    """A rectangle with its four corner pixels cut, a light top row and a dark bottom row."""
    _px(draw, x0 + 1, y0, x1 - 1, y1, fill)
    _px(draw, x0, y0 + 1, x1, y1 - 1, fill)
    if hi:
        _px(draw, x0 + 1, y0, x1 - 1, y0, hi)
    if lo:
        _px(draw, x0 + 1, y1, x1 - 1, y1, lo)


def _banded(size, shapes, bands):
    """Fill discs/rects on a mask, then colour them in flat horizontal bands: bands = ((y_below, colour), ...)."""
    mask = Image.new('L', size, 0)
    d = ImageDraw.Draw(mask)
    for kind, *args in shapes:
        (_disc(d, *args, fill=255) if kind == 'disc' else _px(d, *args, 255))
    sprite = Image.new('RGBA', size, (0, 0, 0, 0))
    out, m = sprite.load(), mask.load()
    for y in range(size[1]):
        colour = bands[-1][1]
        for limit, candidate in bands:
            if y < limit:
                colour = candidate
                break
        rgb = ImageColor.getrgb(colour) + (255,)
        for x in range(size[0]):
            if m[x, y]:
                out[x, y] = rgb
    return sprite


def _dots(draw, points, fill):
    for x, y in points:
        draw.point((x, y), fill=fill)


POSES = {'idle': (0, -1), 'bob': (1, -1), 'guard': (1, -2), 'ready': (0, -2)}


def _codex(pose='idle'):
    """"Cloudy": Codex's cloud as a fighter. A violet-blue storm cloud whose face is a little terminal showing the
    ">_" prompt, a yellow lightning bolt for a crest, stubby legs and a glove thrown forward. Faces right.
    Poses: planted feet, breathing and small shifts of the raised guard."""
    sq, ext = POSES[pose]
    size = (42, 36)
    cloud = [('disc', 11, 15, 5), ('disc', 17, 12, 6), ('disc', 24, 14, 5), ('disc', 27, 19, 4),
             ('rect', 8, 16, 29, 25), ('disc', 10, 24, 3), ('disc', 18, 26, 3), ('disc', 26, 24, 3)]
    body = _banded(size, cloud, ((13, '#cdbfff'), (16, '#a396ff'), (20, '#7683ff'), (24, '#5560f0'), (99, '#3b3dc4')))
    d = ImageDraw.Draw(body)
    _px(d, 12, 15, 25, 22, '#0c0f2e')                                          # the terminal face
    _px(d, 12, 15, 25, 15, '#3a3f9a')
    _px(d, 12, 15, 12, 22, '#3a3f9a')
    for y, (x0, x1) in zip(range(16, 21), ((14, 15), (15, 16), (16, 17), (15, 16), (14, 15))):   # ">"
        _px(d, x0, y, x1, y, '#7be1ff')
    _px(d, 19, 20, 23, 21, '#7be1ff')                                          # "_"
    _dots(d, ((14, 16), (15, 16)), '#e6fbff')
    _dots(d, ((17, 8), (18, 8), (16, 9), (17, 9), (16, 10), (17, 10), (18, 10), (19, 10), (18, 11), (19, 11), (17, 12), (18, 12),
              (17, 13), (16, 14)), '#ffd23f')                                  # crest tucked into the cloud
    _dots(d, ((17, 8), (18, 8), (16, 9), (17, 9)), '#fff1a0')
    _px(d, 4, 20, 7, 24, '#7683ff')                                            # back arm and glove
    _px(d, 2, 22, 5, 26, '#e6e9ff')
    _px(d, 30, 17, 32 + ext, 20, '#7683ff')                                    # front arm
    guard = -3 if pose in ('guard', 'ready') else -2
    _px(d, 32 + ext, 14 + guard, 36 + ext, 21 + guard, '#ffffff')
    _px(d, 32 + ext, 19 + guard, 36 + ext, 21 + guard, '#c4cbff')
    if pose == 'guard':
        d.line((34,13,36,16),fill='#96e9ef')
    s = Image.new('RGBA', size, (0, 0, 0, 0))
    s.alpha_composite(body, (0, sq))
    d = ImageDraw.Draw(s)
    _px(d, 12, 27 + sq, 15, 31, '#3b3dc4')                                     # legs and boots (the feet stay put)
    _px(d, 22, 27 + sq, 25, 31, '#3b3dc4')
    _px(d, 10, 31, 16, 32, '#23247f')
    _px(d, 21, 31, 27, 32, '#23247f')
    return _outline(s)


def _claude(pose='idle'):
    """"Clawd": Claude Code's orange critter as a karate fighter: two black eyes, a headband with the Claude mark,
    a glove thrown forward and four little legs. Drawn facing right, mirrored for the ring.
    Poses: planted feet, breathing and small shifts of the raised guard."""
    sq, ext = POSES[pose]
    size = (44, 36)
    orange, hi, lo, deep = '#e08a60', '#f6b692', '#b8603a', '#7a3a22'
    body = Image.new('RGBA', size, (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    _px(d, 7, 10, 28, 25, orange)                                              # body
    _px(d, 7, 10, 28, 11, hi)
    _px(d, 7, 24, 28, 25, lo)
    _px(d, 26, 12, 28, 24, '#c46f48')
    _px(d, 7, 12, 28, 14, '#ece5d3')                                           # headband and its shadow
    _px(d, 7, 14, 28, 14, '#bdb4a0')
    _px(d, 4, 10, 6, 12, '#cfc6b4')                                            # tails flying behind
    flutter = 1 if pose in ('bob', 'guard') else 0
    _px(d, 1, 8 + flutter, 4, 10 + flutter, '#cfc6b4')
    _px(d, 0, 12 - flutter, 4, 14 - flutter, '#bdb4a0')
    _px(d, 15, 11, 19, 14, '#4a4338')                                          # the Claude mark on the band
    _dots(d, ((17, 11), (17, 14), (16, 12), (18, 12), (16, 13), (18, 13), (17, 12), (17, 13)), '#f1ece0')
    _px(d, 11, 16, 13, 21, INK)                                                # eyes
    _px(d, 22, 16, 24, 21, INK)
    _dots(d, ((11, 16), (11, 17), (22, 16), (22, 17)), '#ffffff')
    _px(d, 15, 22, 20, 22, deep)                                               # determined mouth
    _px(d, 3, 17, 6, 21, orange)                                               # back arm and glove
    _px(d, 1, 19, 5, 23, '#ece5d3')
    _px(d, 29, 16, 31 + ext, 20, orange)                                       # front arm
    guard = -3 if pose in ('guard', 'ready') else -2
    _px(d, 31 + ext, 13 + guard, 36 + ext, 22 + guard, '#f1ece0')
    _px(d, 31 + ext, 20 + guard, 36 + ext, 22 + guard, '#cfc6b4')
    if pose == 'guard':
        d.line((33,12,35,15),fill='#ffe1a5')
    s = Image.new('RGBA', size, (0, 0, 0, 0))
    s.alpha_composite(body, (0, sq))
    d = ImageDraw.Draw(s)
    for x in (9, 14, 20, 25):                                                  # four stout legs
        _px(d, x, 26 + sq, x + 2, 30, lo)
        _px(d, x - 1, 30, x + 3, 31, deep)
    return _outline(s)


# ---- the HUD ---------------------------------------------------------------------------------------------

def _health_bands(remaining):
    if remaining is None:
        return STONE
    return HEALTH_RED if remaining <= 20 else HEALTH_AMBER if remaining <= 50 else HEALTH_GREEN


def _fallen(provider, size):
    """Hand-drawn grounded KO, in the same restoration box as the live fighter."""
    sprite = Image.new('RGBA', size, (0,0,0,0))
    d = ImageDraw.Draw(sprite)
    if provider == 'codex':
        for x,y,r in ((12,30,4),(18,29,5),(25,30,4)):
            _disc(d,x,y,r,'#7683ff')
        _rounded(d,10,29,29,35,'#5560f0','#a396ff','#3b3dc4')
        _px(d,13,29,26,33,'#0c0f2e')
        eye_color='#7be1ff'
        _px(d,4,33,9,36,'#c4cbff')
        _px(d,28,34,34,36,'#23247f')
        d.line([(31,29),(34,30),(32,32),(36,32)],fill='#ffd23f',width=2)
    else:
        _rounded(d,9,27,31,35,'#e08a60','#f6b692','#b8603a')
        _px(d,9,27,31,29,'#ece5d3')
        d.line([(9,28),(5,30),(3,29)],fill='#cfc6b4',width=2)
        _px(d,4,33,9,36,'#f1ece0')
        _px(d,29,34,35,36,'#7a3a22')
        eye_color=INK
    for x in (15,22):
        d.line((x,30,x+2,32),fill=eye_color)
        d.line((x+2,30,x,32),fill=eye_color)
    # A contained badge travels with the sprite, so restoration cannot erase it.
    d.rectangle((11,14,29,23),fill=INK,outline='#f64b59')
    d.text((14,16),'KO',font=face('press-start-2p.ttf',6),fill='#ffb4ac')
    return sprite

def _life_bar(draw, x0, x1, remaining, bands, from_right):
    """A 54x8 bar with a cream frame. `remaining` is 0..100 or None (unknown: an empty frame, no fill)."""
    _px(draw, x0, 5, x1, 12, HEALTH_RED['mid'] if remaining == 0 else CREAM)
    _px(draw, x0 + 1, 6, x1 - 1, 11, PLUM)
    inner = x1 - x0 - 1                                                         # inner width in px
    if remaining is not None and remaining > 0:
        width = max(1, round(inner * remaining / 100))
        left = x1 - width if from_right else x0 + 1
        right = left + width - 1
        _px(draw, left, 6, right, 11, bands['mid'])
        _px(draw, left, 6, right, 7, bands['hi'])
        _px(draw, left, 11, right, 11, bands['lo'])
    for tick in range(1, 10):                                                   # a notch every 10 %
        notch = x0 + 1 + round(inner * tick / 10)
        draw.point((notch, 6), fill=INK)
        draw.point((notch, 11), fill=INK)


def _power_meter(draw, x0, pace):
    """Two lines of five parts: quota left on top, time left below (quota in 5% steps, time in quarter hours)."""
    if pace is None:
        return
    quota, hours = pace
    for line, value in enumerate((math.ceil(quota / 5) / 4, round(hours * 4) / 4)):
        y = 22 + line * 3
        for part in range(5):
            left = x0 + part * 11
            _px(draw, left, y, left + 8, y + 1, '#4a3a70')                      # unlit
            fill = max(0, min(1, value - part))
            if fill > 0:
                _px(draw, left, y, left + max(1, round(9 * fill)) - 1, y + 1, STONE['mid'])


def _reserves(draw, x, y, count, colour, marked=False):
    """Three short reserve bars, one per saved reset. While the number is unknown or old they stay (empty when unknown, the last
    known count when old) and ONE faint dot ends the row, with no `?` and no OLD (the user, 2026-10-20)."""
    if marked:
        _px(draw, x + 27, y + 3, x + 27, y + 3, '#6a5a8a')
    for i in range(3):
        left=x+i*9
        _px(draw,left,y+1,left+6,y+5,'#6a5a8a')
        _px(draw,left+1,y+2,left+5,y+4,colour if count is not None and count>i else PLUM_D)


def _outlined_text(out, xy, text, font, fill, anchor, edge=INK, step=2):
    x, y = xy
    for dx, dy in ((-step, 0), (step, 0), (0, -step), (0, step), (step, step)):
        out.text((x + dx, y + dy), text, font=font, fill=edge, anchor=anchor)
    out.text((x, y), text, font=font, fill=fill, anchor=anchor)


# Guard stances, no translation or attack. Rivals breathe out of phase.
CODEX_SCRIPT = [(0,0,0), (1,0,0), (2,0,0), (3,0,0)]
CLAUDE_SCRIPT = [(0,0,0), (3,0,0), (2,0,0), (1,0,0)]


def _fighter_specs(c_ko, k_ko):
    sprites = []
    for provider, build, x, mirrored, script, knocked_out, opponent_down in (
            ('codex', _codex, 14, False, CODEX_SCRIPT, c_ko, k_ko),
            ('claude', _claude, 101, True, CLAUDE_SCRIPT, k_ko, c_ko)):
        poses = ([_fallen(provider, build().size)] if knocked_out else
                 [build(pose) for pose in ('idle', 'bob', 'guard', 'ready')])
        if knocked_out:
            script = [(0,0,0)] * len(script)
        elif opponent_down:
            script = [(min(frame,1),0,0) for frame,_,_ in script]
        if mirrored:
            poses = [ImageOps.mirror(pose) for pose in poses]
            if knocked_out:  # Keep KO readable, while the fallen character faces its rival.
                d = ImageDraw.Draw(poses[0])
                left=poses[0].width-30
                d.rectangle((left,14,left+18,23),fill=INK,outline='#f64b59')
                d.text((left+3,16),'KO',font=face('press-start-2p.ttf',6),fill='#ffb4ac')
        # Remove unused headroom, not scale the bodies. The 30-row band buys
        # a fourth full-scene frame within the existing board's 40 KB budget.
        poses = [pose.crop((0,8,pose.width,38)) for pose in poses]
        sprites.append({'x': x * K, 'y': SCENE_TOP * K, 'frames': poses, 'script': script, 'step_ms': STEP_MS})
    return sprites


def _sky(image, credit_badge=False):
    """Sparse stars on empty sky only; native meteor stays in the clear HUD gap.

    The meteor engine advances down/right and stops at y1+36, so its entire
    restoration box (not just its head) must stay above VS and the moving city.
    No clock/random input: resident movement must never cause extra uploads.
    """
    from token_tv.board_anim import rgb565
    sky = {ImageColor.getrgb(c) for c in ('#101529','#1b1b38','#302047','#432351')}
    # Reserve complete text regions, including empty spaces inside glyphs and
    # the optional WIN/DANGER labels. All other visible sky can carry stars.
    protected=((0,0,320,48),(202,40,316,54),(6,54,82,82),(238,54,316,82),
               (6,82,80,96),(240,82,316,96),(124,90,196,134))
    if credit_badge:
        protected += ((8, 56, 129, 85),)
    points = [[],[],[]]
    for y in range(50,116,4):
        for x in range(4,316,6):
            safe = not any(x<r and x+2>l and y<b and y+2>t for l,t,r,b in protected)
            if safe and all(image.getpixel((x+dx,y+dy)) in sky for dx in (0,1) for dy in (0,1)):
                points[min(2,x*3//320)].append((x,y))
    chosen = []
    for zone in points:
        zone.sort(key=lambda p: ((p[0]*73) ^ (p[1]*151)) % 997)
        count=0
        for x,y in zone:
            if all((x-a)**2+(y-b)**2 >= 64 for a,b in chosen):
                chosen.append((x,y));count+=1
            if count==6:break
    d=ImageDraw.Draw(image)
    stars=[]
    for i,(x,y) in enumerate(chosen):
        base = '#9baccb' if i%3 else '#d3ccba'
        d.rectangle((x,y,x+1,y+1),fill=base)
        stars.append((x,y,rgb565(ImageColor.getrgb(base)),rgb565((239,247,255)),rgb565((85,99,135))))
    meteor={'x0':76,'y0':50,'x1':76,'y1':50,'period_ms':14000,
            'head':rgb565((255,255,255)),'tail':rgb565((204,237,255)), 'length':12,'speed':2}
    if credit_badge:
        meteor['x0'] = meteor['x1'] = 140
    return stars,meteor


def render_arcade(snapshot, animated=False):
    """The VERSUS page. With `animated` the fighters are left out of the picture and returned as sprites in an
    ANIM payload instead: (image, payload). Without it they are drawn in, for boards that cannot animate."""
    canvas = Image.new('RGBA', (LW, LH), PLUM_D)
    draw = ImageDraw.Draw(canvas)
    _stage(draw)
    canvas.alpha_composite(_scene(0), (0, SCENE_TOP))

    codex, claude = _row(snapshot, 'codex'), _row(snapshot, 'claude')
    c_value, _, c_stale, c_reset = remaining_reading(codex)
    k_value, _, k_stale, k_reset = remaining_reading(claude)
    c_ko, k_ko = c_value == 0 and not c_stale, k_value == 0 and not k_stale
    c_count, c_old = banked_hearts(codex)
    k_count, k_old = banked_hearts(claude)

    # the centre box between the bars: what the bars measure
    _px(draw, 61, 4, 98, 17, CREAM)
    _px(draw, 62, 5, 97, 16, PLUM)

    _life_bar(draw, 4, 57, c_value, _health_bands(c_value), from_right=True)
    _life_bar(draw, 102, 155, k_value, _health_bands(k_value), from_right=False)
    _power_meter(draw, 102, session_pace(claude))
    _reserves(draw, 31, 15, c_count, GOLD['mid'], icons.marked(c_count, c_old))
    _reserves(draw, 102, 15, k_count, STONE['hi'], icons.marked(k_count, k_old))

    sprites = _fighter_specs(c_ko, k_ko)
    for sprite in sprites:
        x, top = sprite['x']//K, sprite['y']//K
        pose = sprite['frames'][0]
        _px(draw, x+5, 94, x+pose.width-7, 95, '#122238')
        if not animated:
            canvas.alpha_composite(pose, (x, top))

    f8, f16, fvs = face('press-start-2p.ttf', 8), face('press-start-2p.ttf', 16), face('press-start-2p.ttf', 24)
    c_text, k_text = 'RESET ' + c_reset.upper(), 'RESET ' + k_reset.upper()
    glass = ('#####', '.###.', '..#..', '..#..', '.#.#.', '.###.', '#####')       # hourglass icon for the resets
    c_left = 26                                                                    # final px where the text starts
    k_left = 310 - round(f8.getlength(k_text))
    for text_left, colour in ((c_left, GOLD['hi']), (k_left, STONE['hi'])):
        x0 = (text_left - 16) // K                                                # 16 px to its left, with a gap
        for yy, line in enumerate(glass):
            for xx, cell in enumerate(line):
                if cell == '#':
                    draw.point((x0 + xx, 107 + yy), fill=colour)
    image = canvas.resize((LW * K, LH * K), Image.Resampling.NEAREST).convert('RGB')
    before_text = image.copy()
    out = ImageDraw.Draw(image)
    out.fontmode = '1'                                                          # hard glyph pixels
    out.text((160, 10), 'WEEK', font=f8, fill=CREAM, anchor='ma')
    out.text((160, 21), 'LEFT', font=f8, fill='#b9a8e0', anchor='ma')
    out.text((10, 30), 'CODEX', font=f8, fill=CODEX, anchor='la')
    out.text((310, 30), 'CLAUDE', font=f8, fill=CLAUDE, anchor='ra')
    for xy, value, anchor in (((10, 58), c_value, 'la'), ((310, 58), k_value, 'ra')):
        percentage = '--' if value is None else '<1%' if 0 < value < 1 else f'{round(value)}%'
        _outlined_text(out, xy, percentage, f16, '#ffffff', anchor)
    _outlined_text(out, (160, 110), 'VS', fvs, CREAM, 'mm', edge='#7a1d4a', step=4)
    for xy, value, stale, opponent_down, anchor in (
            ((10,84),c_value,c_stale,k_ko,'la'), ((310,84),k_value,k_stale,c_ko,'ra')):
        label = 'WIN' if opponent_down and not stale and value is not None and value > 0 else (
                'DANGER' if value is not None and 0 < value <= 20 else '')
        if label:
            _outlined_text(out,xy,label,f8,HEALTH_GREEN['hi'] if label=='WIN' else HEALTH_RED['hi'],anchor)
    out.text((c_left, 218), c_text, font=f8, fill=GOLD['hi'], anchor='la')
    out.text((310, 218), k_text, font=f8, fill=STONE['hi'], anchor='ra')
    for x, count, old, anchor in ((118, c_count, c_old, 'la'), (200, k_count, k_old, 'ra')):
        mark = icons.mark(count, old)
        if mark:
            out.text((x, 33), mark, font=f8, fill='#b9a8e0', anchor=anchor)
    from token_tv.credits import exhausted_credits
    stars,meteor = _sky(image, credit_badge=exhausted_credits(codex) is not None)
    if not animated:
        return image
    from token_tv import board_anim
    # Compose city and fighters together. The two halves are disjoint, so the
    # firmware never restores a static rectangle over a moving building.
    from PIL import ImageChops
    text_mask = ImageChops.difference(image, before_text).convert('L')
    scenes = []
    for phase in range(4):
        scene = _scene(phase)
        d = ImageDraw.Draw(scene)
        for fighter in sprites:
            x, y = fighter['x']//K, fighter['y']//K - SCENE_TOP
            poses = fighter['frames']
            frame, dx, dy = fighter['script'][phase]
            _px(d,x+5,94-SCENE_TOP,x+poses[0].width-7,95-SCENE_TOP,'#122238')
            scene.alpha_composite(poses[frame],(x+dx//K,y+dy//K))
        scenes.append(scene)
    tiles = []
    for x in (0, 160):
        poses = [scene.crop((x//2,0,x//2+80,SCENE_HEIGHT)) for scene in scenes]
        for pose in poses:
            for py in range(pose.height):
                for px in range(pose.width):
                    if text_mask.crop((x+px*2,SCENE_TOP*2+py*2,x+px*2+2,SCENE_TOP*2+py*2+2)).getbbox():
                        pose.putpixel((px,py),(0,0,0,0))
        tiles.append({'x': x, 'y': SCENE_TOP*K, 'frames': poses,
                      'script': [(step,0,0) for step in range(4)], 'step_ms':STEP_MS})
    return image, board_anim.encode(tiles,stars,meteor)
