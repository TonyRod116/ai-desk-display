"""Page 6 of the touch board: "VERSUS", the usage as a 90s fighting-game screen (320x240).

Codex (left, yellow) against Claude (right, stone), the way a Neo Geo / Street Fighter II screen draws it:

- the two long life bars at the top are the quota left of each week, anchored at the centre and draining
  towards the screen edges, with true percentages in the player-score positions;
- the permanent KO plaque is a game-style divider, not a claim that a fighter has been knocked out;
- the three short reserve bars are saved resets, marked discreetly if unknown or stale;
- Claude's five-hour session is the "power meter" under its life bar: two lines of five parts, quota left
  on top and time left below, in the colour of Claude's bar, with no marks or numbers. An unknown session
  draws nothing at all, so unknown never reads as empty;
- the reset of each week is at the bottom, and the two fighters stand on a rooftop dojo.

The HUD and whole-body animation use bold 2x arcade pixels, while the bundled
stage keeps its finer native-resolution details. A separate optional scenery
set can be supplied locally without adding it to the repository.
"""
import math

from PIL import Image, ImageColor, ImageDraw

from token_tv.board_art import CLAUDE, CODEX, _row
from token_tv import board_reset_icons as icons
from token_tv import board_arcade_stage as stage
from token_tv import board_arcade_local as local_stage
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

LW, LH, K = 160, 120, 2          # the logical canvas and the size of one logical pixel
SCENE_TOP, STEP_MS = 55, 300
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


# ---- the HUD ---------------------------------------------------------------------------------------------

def _health_bands(remaining):
    if remaining is None:
        return STONE
    return HEALTH_RED if remaining <= 20 else HEALTH_AMBER if remaining <= 50 else HEALTH_GREEN


def _life_bar(draw, x0, x1, remaining, bands, from_right):
    """Long arcade health bar, anchored at the central KO plaque."""
    # A dark shadow, silver lower edge and bright upper edge form a small
    # arcade-style bezel without moving the data-bearing part of the bar.
    _px(draw, x0-1, 8, x1+1, 17, '#31233f')
    _px(draw, x0, 9, x1, 16, '#f8f5e6')
    _px(draw, x0+1, 16, x1-1, 16, '#a4adbd')
    _px(draw, x0+2, 8, x1-2, 8, '#ffffff')
    _px(draw, x0 + 1, 10, x1 - 1, 15, '#4d2034' if remaining is not None else '#30364b')
    inner = x1 - x0 - 1                                                         # inner width in px
    if remaining is not None and remaining > 0:
        width = max(1, round(inner * remaining / 100))
        left = x1 - width if from_right else x0 + 1
        right = left + width - 1
        _px(draw, left, 10, right, 15, bands['mid'])
        _px(draw, left, 10, right, 10, bands['hi'])
        _px(draw, left, 15, right, 15, bands['lo'])


def _portrait(canvas, x, provider):
    """A small original icon portrait in the game HUD, separate from the fighter."""
    d = ImageDraw.Draw(canvas)
    _px(d,x,19,x+15,35,'#b1b8be')
    _px(d,x+1,19,x+14,19,'#ffffff')
    _px(d,x,20,x,34,'#ffffff')
    _px(d,x+1,20,x+14,34,'#414c80' if provider == 'codex' else '#694658')
    # Portraits come from the actual original mascot drawings, so the
    # scoreboard and arena cannot quietly drift to different characters.
    region = (15,16,69,76) if provider == 'codex' else (31,20,82,71)
    head = stage.fighter(provider).crop(region).resize((14,12), Image.Resampling.NEAREST)
    canvas.alpha_composite(head,(x+1,21))


def _power_meter(draw, x0, pace):
    """Five native-pixel segments each for session quota and time, beneath the life bar."""
    if pace is None:
        return
    quota, hours = pace
    for line, value in enumerate((math.ceil(quota / 5) / 4, round(hours * 4) / 4)):
        y = 35 + line * 4
        for part in range(5):
            left = x0 + part * 9
            _px(draw, left, y, left + 6, y + 2, '#4a3a70')                      # unlit
            fill = max(0, min(1, value - part))
            if fill > 0:
                _px(draw, left, y, left + max(1, round(7 * fill)) - 1, y + 2, STONE['mid'])


def _reserves(draw, x, y, count, colour, marked=False, mark_before=False):
    """Three fixed reserve bars and a discreet dot for unknown or old data.

    On Claude's right-hand side the dot comes before the bars so their
    alignment never changes. The optional excess-reserve '+' has its own space.
    """
    if marked:
        dot = x - 3 if mark_before else x + 27
        _px(draw, dot, y + 3, dot, y + 3, '#6a5a8a')
    for i in range(3):
        left=x+i*9
        _px(draw,left,y+1,left+6,y+5,'#6a5a8a')
        _px(draw,left+1,y+2,left+5,y+4,colour if count is not None and count>i else PLUM_D)


def _outlined_text(out, xy, text, font, fill, anchor, edge=INK, step=2):
    x, y = xy
    for dx, dy in ((-step, 0), (step, 0), (0, -step), (0, step), (step, step)):
        out.text((x + dx, y + dy), text, font=font, fill=edge, anchor=anchor)
    out.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _sky(image):
    """Sparse stars on empty sky only; native meteor stays in the clear HUD gap.

    The meteor engine advances down/right and stops at y1+36, so its entire
    restoration box (not just its head) must stay above the moving city.
    No clock/random input: resident movement must never cause extra uploads.
    """
    from token_tv.board_anim import rgb565
    sky = {ImageColor.getrgb(c) for c in ('#101529','#33405e','#405b77','#58778a','#8c8991')}
    # Reserve complete text regions, including empty spaces inside glyphs and
    # the optional WIN/DANGER labels. All other visible sky can carry stars.
    protected=((0,0,320,36),(4,36,112,70),(194,36,316,80),
               (140,34,180,46),(6,80,80,96),(240,80,316,96),
               (26,112,108,196),(216,112,298,196))
    points = [[],[],[]]
    for y in range(50,SCENE_TOP*K,4):
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
    meteor={'x0':135,'y0':55,'x1':135,'y1':55,'period_ms':14000,
            'head':rgb565((255,255,255)),'tail':rgb565((204,237,255)), 'length':12,'speed':2}
    return stars,meteor


def render_arcade(snapshot, animated=False, anim_frames=4):
    """Render VERSUS; animated returns a background and resident detail sprites.

    Without animation the first pose is composited into a single image.
    """
    art = local_stage.load()
    canvas = Image.new('RGBA', (LW, LH), (0, 0, 0, 0) if art else PLUM_D)
    draw = ImageDraw.Draw(canvas)
    if not art:
        draw.rectangle((0,20,LW-1,LH-1), fill='#33405e')
    draw.rectangle((0,106,LW-1,LH-1), fill='#080917')

    codex, claude = _row(snapshot, 'codex'), _row(snapshot, 'claude')
    c_value, _, c_stale, c_reset = remaining_reading(codex)
    k_value, _, k_stale, k_reset = remaining_reading(claude)
    c_ko, k_ko = c_value == 0 and not c_stale, k_value == 0 and not k_stale
    c_count, c_old = banked_hearts(codex)
    k_count, k_old = banked_hearts(claude)

    # Long opposing health bars, with the classic centre KO plaque and
    # small player portraits. The plaque is a permanent game HUD ornament;
    # an actual knockout still requires a fresh weekly zero.
    _life_bar(draw, 4, 72, c_value, _health_bands(c_value), from_right=True)
    _life_bar(draw, 87, 155, k_value, _health_bands(k_value), from_right=False)
    _px(draw, 73, 8, 86, 17, '#f7f0dd')
    _px(draw, 74, 9, 85, 16, '#160e22')
    _portrait(canvas,4,'codex')
    _portrait(canvas,140,'claude')
    c_reserves_x, k_reserves_x = 24, 108
    _reserves(draw, c_reserves_x, 26, c_count, GOLD['mid'], icons.marked(c_count, c_old))
    k_marked = icons.marked(k_count, k_old)
    _reserves(draw, k_reserves_x, 26, k_count, STONE['hi'], k_marked, mark_before=True)

    f8, f12, f15 = (face('press-start-2p.ttf', size) for size in (8, 12, 15))
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
    overlay = canvas.resize((LW * K, LH * K), Image.Resampling.NEAREST)
    image = (Image.alpha_composite(art[0].convert('RGBA'), overlay).convert('RGB')
             if art else overlay.convert('RGB'))
    # The native-resolution stage is the clean background for both complete
    # pixel-art fighters. The board moves them without network transfers.
    if not art:
        stage.draw_stage(image)
    stage.draw_fighters(image, c_ko, k_ko, face('press-start-2p.ttf',6))
    out = ImageDraw.Draw(image)
    out.fontmode = '1'                                                          # hard glyph pixels
    _power_meter(out, 178, session_pace(claude))
    _outlined_text(out,(4,1),'1P',f8,'#ffcb76','la',edge='#563083',step=1)
    _outlined_text(out,(316,1),'2P',f8,'#ffcb76','ra',edge='#563083',step=1)
    _outlined_text(out,(160,1),'WEEK',f8,CREAM,'ma',edge='#563083',step=1)
    _outlined_text(out,(160,17),'KO',f12,'#ff5a45','ma',edge='#330b22',step=1)
    _outlined_text(out,((c_reserves_x+12)*K+1,38),'CODEX',f8,CODEX,'ma',edge='#25204d',step=1)
    _outlined_text(out,((k_reserves_x+12)*K+1,38),'CLAUDE',f8,CLAUDE,'ma',edge='#25204d',step=1)
    for xy, value, anchor in (((27,1), c_value, 'la'), ((293,1), k_value, 'ra')):
        percentage = '--' if value is None else '<1%' if 0 < value < 1 else f'{round(value)}%'
        _outlined_text(out,xy,percentage,f15,'#ffe5a0',anchor,edge='#762948',step=1)
    for xy, value, stale, opponent_down, anchor in (
            ((10,84),c_value,c_stale,k_ko,'la'), ((310,84),k_value,k_stale,c_ko,'ra')):
        label = 'WIN' if opponent_down and not stale and value is not None and value > 0 else (
                'DANGER' if value is not None and 0 < value <= 20 else '')
        if label:
            _outlined_text(out,xy,label,f8,HEALTH_GREEN['hi'] if label=='WIN' else HEALTH_RED['hi'],anchor)
    out.text((c_left, 218), c_text, font=f8, fill=GOLD['hi'], anchor='la')
    out.text((310, 218), k_text, font=f8, fill=STONE['hi'], anchor='ra')
    for x, count, old, anchor in ((104, c_count, c_old, 'la'),
                                  (207 if k_marked else 213, k_count, k_old, 'ra')):
        mark = icons.mark(count, old)
        if mark:
            out.text((x, 54), mark, font=f8, fill='#b9a8e0', anchor=anchor)
    if art:
        stars, meteor = [], None
        sprites = local_stage.animated_details(art, c_ko, k_ko, STEP_MS, anim_frames)
    else:
        stars,meteor = _sky(image)
        sprites = stage.animated_details(c_ko, k_ko, STEP_MS, anim_frames)
    if not animated:
        stage.paint_first_frame(image, sprites)
        return image
    from token_tv import board_anim
    return image, board_anim.encode(sprites,stars,meteor)
