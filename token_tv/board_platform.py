"""An animated 16-bit platform level for page seven of the touch display.

The level and its characters are original pixel drawings made for this 320x240
screen.  The board moves the sprites itself; account refreshes never drive the
animation.  The unmodified deep-space renderer remains in board_space.py.
"""
import functools
import math

from PIL import Image, ImageDraw, ImageFilter

from token_tv.board_anim import encode
from token_tv.board_arcade_stage import paint_first_frame
from token_tv.board_art import _row
from token_tv import board_reset_icons as reset_icons
from token_tv.personal_faces import banked_hearts, remaining_reading, session_pace
from token_tv.themes import face

SIZE = (320, 240)
SCALE = 2
INK = '#122a39'


def _cloud(d, x, y, scale=1):
    """Chunky cloud with the pale checkerboard underside of a 16-bit sky."""
    p = lambda n: round(n * scale)
    d.rectangle((x+p(4), y+p(6), x+p(29), y+p(13)), fill='#daf6fd')
    d.rectangle((x+p(8), y+p(3), x+p(24), y+p(13)), fill='#f9ffff')
    d.rectangle((x+p(12), y+p(1), x+p(20), y+p(13)), fill='#f9ffff')
    d.rectangle((x+p(2), y+p(8), x+p(31), y+p(11)), fill='#f9ffff')
    for xx in range(x+p(5), x+p(29), max(2,p(2))):
        d.point((xx,y+p(13)), fill='#a9dfe8')
    d.line((x+p(5),y+p(14),x+p(28),y+p(14)), fill='#a7d1e4')


def _hill(d, x, top, width, ground, fill, rim, light, spots):
    """A tall, rounded, dotted landform, outlined and shaded on its right edge."""
    radius = width // 2
    d.rounded_rectangle((x, top, x+width, ground+radius), radius=radius, fill=rim)
    d.rounded_rectangle((x+1, top+1, x+width-3, ground+radius), radius=radius-1, fill=fill)
    d.rectangle((x+1, top+radius, x+width-3, ground), fill=fill)
    d.line((x+width-2,top+radius,x+width-2,ground),fill=rim)
    for yy in range(top+radius-3,ground,2):
        d.point((x+width-5+(yy//2)%2,yy),fill=rim)
    for sx, sy in spots:
        d.rounded_rectangle((x+sx,top+sy,x+sx+4,top+sy+8),radius=2,fill=light)
        d.line((x+sx+1,top+sy+1,x+sx+2,top+sy+1),fill='#e7f9ef')


def _bush(d, x, y, width=25):
    dark, mid, light = '#0b7440', '#15be56', '#65eb61'
    d.polygon([(x,y+8),(x+2,y+4),(x+5,y+5),(x+8,y+1),(x+11,y+4),
               (x+15,y),(x+19,y+4),(x+22,y+2),(x+width,y+7),(x+width,y+10),(x,y+10)],
              fill=dark,outline=INK)
    d.polygon([(x+2,y+7),(x+6,y+5),(x+8,y+3),(x+11,y+6),(x+15,y+2),
               (x+18,y+6),(x+22,y+4),(x+width-2,y+8),(x+width-2,y+9),(x+2,y+9)],fill=mid)
    d.line((x+5,y+7,x+7,y+6),fill=light)
    d.line((x+15,y+5,x+16,y+4),fill='#d2ff92')


def _pipe(d, x, y, h=28):
    """Green pipe with a shaded rim, highlights and little fasteners."""
    d.rectangle((x+2,y+5,x+19,y+h),fill=INK)
    d.rectangle((x+4,y+5,x+17,y+h),fill='#079b42')
    d.rectangle((x+5,y+5,x+7,y+h-1),fill='#82fa70')
    d.rectangle((x+8,y+5,x+12,y+h-1),fill='#31d75c')
    d.rectangle((x+16,y+5,x+17,y+h-1),fill='#087534')
    d.rectangle((x,y,x+21,y+8),fill=INK)
    d.rectangle((x+1,y+1,x+20,y+6),fill='#22c950')
    d.rectangle((x+2,y+1,x+19,y+2),fill='#9af88d')
    d.rectangle((x+2,y+4,x+19,y+6),fill='#16a946')
    d.rectangle((x+2,y+7,x+19,y+7),fill='#065d2c')
    d.point((x+3,y+3),fill='#ecffb4')
    d.point((x+18,y+3),fill='#087a30')


def _flower(d, x, y, petal):
    d.line((x,y+2,x,y+6),fill='#075d36')
    d.point((x-1,y+5),fill='#3fc94c')
    for dx,dy in ((0,-1),(-1,0),(1,0),(0,1)):
        d.point((x+dx,y+dy),fill=petal)
    d.point((x,y),fill='#ffdd35')


def _block(d, x, y, special=False):
    dark = '#573723'
    d.rectangle((x,y,x+13,y+13),fill=dark)
    d.rectangle((x+1,y+1,x+12,y+11),fill='#e8a039' if not special else '#ffcc42')
    d.line((x+1,y+1,x+12,y+1),fill='#ffe08a')
    d.line((x+1,y+2,x+1,y+10),fill='#ffe08a')
    d.line((x+2,y+11,x+12,y+11),fill='#b56928')
    for xx,yy in ((2,2),(11,2),(2,10),(11,10)):
        d.point((x+xx,y+yy),fill='#9b541f')
    if special:
        d.text((x+4,y+1),'?',font=face('press-start-2p.ttf',8),fill='#fff5b1',stroke_width=1,stroke_fill='#8e4a19')
    else:
        d.line((x+2,y+6,x+11,y+6),fill='#a86225')
        d.line((x+7,y+2,x+7,y+5),fill='#bc742d')
        d.line((x+4,y+7,x+4,y+10),fill='#bc742d')
        d.line((x+10,y+7,x+10,y+10),fill='#bc742d')


@functools.lru_cache(maxsize=1)
def _scenery():
    """Build the quiet, reusable 160x120 game world with crisp 2x pixels."""
    im = Image.new('RGB',(160,120),'#177ac7')
    d = ImageDraw.Draw(im)
    d.rectangle((0,0,159,40),fill='#146aba')
    d.rectangle((0,41,159,70),fill='#1b82ce')
    d.rectangle((0,71,159,100),fill='#4ca9db')
    # Clouds sit behind three overlapping hills, as in a side-scrolling level.
    _cloud(d, 2,45,1.0)
    _cloud(d, 45,40,.85)
    _cloud(d, 121,48,.95)
    _cloud(d, 105,69,.70)
    _hill(d,-27,47,63,100,'#8bd3e6','#497eaf','#d4f7ef',((35,22),(51,40),(26,45)))
    _hill(d,26,35,58,100,'#6fb8da','#356f9e','#c4f1eb',((13,22),(34,39),(20,51),(42,59)))
    _hill(d,72,42,55,100,'#85c9df','#497eaf','#d8f4eb',((11,24),(34,22),(22,46)))
    _hill(d,118,32,58,100,'#a7e0dc','#5d9bb7','#e8fff0',((12,20),(27,42),(9,57)))
    # Thin checkerboard shade gives the hills depth even on the low-contrast LCD.
    for x,y in ((34,83),(34,88),(81,67),(81,72),(123,76),(124,81),(153,56),(154,61)):
        for yy in range(y,y+5):
            d.point((x+(yy&1),yy),fill='#527fac')
    # A shorter green hill in front separates the player from the blue
    # mountains. Its speckles and edge stay visible on the physical LCD.
    _hill(d,-12,76,47,100,'#43bf70','#187852','#aaf492',((15,10),(30,15)))
    for y in range(87,99,3):
        for x in range(2+(y%2),30,6):
            d.point((x,y),fill='#77df83')
    _cloud(d, 5,78,.65)
    _cloud(d, 80,77,.70)
    # Distant hills and cloud faces, hidden partly behind the foreground props.
    for x,y in ((9,76),(96,75)):
        d.point((x,y),fill='#699db3');d.point((x+3,y),fill='#699db3')
    _bush(d,2,89,27)
    _bush(d,89,89,25)
    _bush(d,130,89,25)
    _pipe(d,133,73,28)
    # Bricks and the question block are behind, not an overlay on the values.
    _block(d,57,62)
    _block(d,71,62,True)
    _block(d,85,62)
    # Grass edge with a scalloped, dark underside. Dithered earth is intentionally
    # warm and much lighter than its outline so the real panel keeps its depth.
    d.rectangle((0,100,159,119),fill='#c99158')
    d.rectangle((0,100,159,102),fill='#103f31')
    d.rectangle((0,99,159,100),fill='#12b44b')
    d.line((0,99,159,99),fill='#8af46a')
    for x in range(0,160,8):
        d.line((x,102,x+2,103),fill='#263f2d')
        d.line((x+3,103,x+5,102),fill='#263f2d')
    for y in range(106,120,5):
        for x in range(2+(y%3)*2,160,9):
            d.rectangle((x,y,x+1,y+1),fill='#f5cb78')
            if x+4<160:d.point((x+4,y+3),fill='#a66f49')
    for x,y,col in ((16,93,'#ffecf0'),(53,93,'#ffe55b'),(107,93,'#fff9dc'),(126,94,'#ff9db4')):
        _flower(d,x,y,col)
    # The sign and scenery add little details while staying behind the player.
    d.rectangle((74,88,76,98),fill='#83552b')
    d.rectangle((69,84,81,91),fill='#543a26')
    d.rectangle((70,85,80,89),fill='#efc879')
    d.polygon([(72,87),(77,87),(77,86),(80,88),(77,90),(77,89),(72,89)],fill='#a96327')
    for x,y in ((42,96),(44,97),(62,97),(77,96),(123,97),(155,96)):
        d.point((x,y),fill='#baff83')
    return im.resize(SIZE,Image.Resampling.NEAREST)


def _runner_pose(step, reverse=False):
    """Original red-capped runner, with whole-body running and jumping poses."""
    im=Image.new('RGBA',(20,25))
    d=ImageDraw.Draw(im)
    dark='#492f29'; red='#ef3431'; hi='#ff7860'; skin='#ffca87'
    blue='#2455ae'; light='#4b96f5'; shoe='#7d381e'; glove='#fff7db'
    # The torso and head are redrawn as one coherent pose, with a tiny bounce.
    bounce = 1 if step == 1 else 0
    def box(a,b,c,e,col):d.rectangle((a,b+bounce,c,e+bounce),fill=col)
    box(4,3,14,4,dark);box(5,2,12,2,red)
    box(3,4,16,5,dark);box(4,3,13,4,red);box(4,5,16,5,red)
    box(8,3,10,3,hi);box(8,3,9,3,'#fff4d5')
    box(4,6,12,10,dark);box(5,6,13,9,skin)
    box(13,7,15,9,skin);box(14,8,16,9,skin)
    box(6,6,7,8,'#753c25');box(12,6,12,7,'#202326')
    box(9,9,13,10,dark);box(7,10,11,10,dark);box(12,10,13,10,skin)
    box(4,11,13,16,dark);box(5,11,12,15,red)
    box(4,12,5,15,red);box(12,12,14,15,red)
    # Blue dungarees and two yellow buttons remain visible in every pose.
    box(6,12,7,17,light);box(11,12,12,17,light)
    box(5,16,13,19,dark);box(6,15,12,18,blue)
    box(7,15,7,15,'#ffd667');box(11,15,11,15,'#ffd667')
    if step==3: # a raised glove and tucked legs at the top of a jump
        box(12,12,14,14,red);box(14,11,16,12,red);box(16,10,17,11,red)
        box(17,7,19,9,glove);box(18,7,19,7,'#ffffff')
        box(2,13,5,15,red);box(1,14,3,16,glove)
        d.rectangle((4,19,9,21),fill=blue);d.rectangle((3,21,8,23),fill=shoe)
        d.rectangle((11,18,15,20),fill=blue);d.rectangle((13,20,17,22),fill=shoe)
    elif step in (0,2):
        if step==0:
            box(1,12,4,14,red);box(0,14,3,16,glove);box(13,13,15,15,red);box(15,14,17,16,glove)
            d.rectangle((4,19,8,21),fill=blue);d.rectangle((2,22,8,24),fill=shoe)
            d.rectangle((11,19,14,21),fill=blue);d.rectangle((12,21,17,23),fill=shoe)
        else:
            box(2,13,4,16,red);box(1,15,3,17,glove);box(13,11,16,13,red);box(16,12,18,14,glove)
            d.rectangle((5,19,8,21),fill=blue);d.rectangle((2,21,7,23),fill=shoe)
            d.rectangle((10,19,14,22),fill=blue);d.rectangle((10,22,16,24),fill=shoe)
    else:
        box(2,12,4,15,red);box(1,14,3,16,glove);box(13,12,15,15,red);box(15,14,17,16,glove)
        d.rectangle((5,20,9,22),fill=blue);d.rectangle((4,22,9,24),fill=shoe)
        d.rectangle((10,20,14,22),fill=blue);d.rectangle((11,22,16,24),fill=shoe)
    # The player stays grounded on the same baseline between walking frames.
    return im.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if reverse else im


def _dino_pose(step, jumping=False):
    """Friendly green dinosaur with a moving head, tail and alternated orange boots."""
    im=Image.new('RGBA',(26,22)); d=ImageDraw.Draw(im)
    dark='#175039'; green='#32ce4b'; light='#a9f477'; white='#f4ffdc'; orange='#f38e37'
    head = (0,1,0,-1)[step]
    d.polygon([(4,12),(0,8),(1,12),(5,17),(11,18),(11,12)],fill=green,outline=dark)
    d.polygon([(6,12),(8,9),(13,9),(17,11),(19,14),(18,18),
               (16,20),(9,20),(6,18),(5,15)],fill=green,outline=dark)
    d.polygon([(14,13),(18,13),(19,15),(18,18),(16,19),(13,18)],fill=white)
    d.rectangle((8,9,13,10),fill='#ef5e32');d.line((9,9,12,9),fill='#ffcb72')
    d.polygon([(14,9),(15,6),(17,8),(17,11)],fill='#ef7135',outline=dark)
    d.rectangle((15,8+head,19,14+head),fill=green,outline=dark)
    d.ellipse((16,4+head,23,12+head),fill=green,outline=dark)
    d.ellipse((20,8+head,25,13+head),fill=green,outline=dark)
    d.rectangle((17,4+head,20,8+head),fill=white)
    d.rectangle((19,5+head,20,7+head),fill='#162e29')
    d.point((24,9+head),fill='#175039')
    d.line((21,12+head,24,12+head),fill='#f8ffe6')
    d.point((17,9+head),fill=light);d.point((8,12),fill=light)
    d.rectangle((17,14,20,15),fill=green);d.point((20,15),fill=white)
    if jumping:
        # Both boots lift clear of the ground together, instead of continuing
        # the running cycle while the rider is in mid-air.
        d.rectangle((7,16,11,18),fill=green);d.rectangle((5,18,11,19),fill=orange)
        d.line((5,20,11,20),fill=dark)
        d.rectangle((15,15,18,17),fill=green);d.rectangle((16,17,21,18),fill=orange)
        d.line((16,19,21,19),fill=dark)
    elif step%2:
        d.rectangle((7,16,11,19),fill=green);d.rectangle((6,18,11,20),fill=orange)
        d.line((6,21,11,21),fill=dark)
        d.rectangle((15,16,18,18),fill=green);d.rectangle((16,17,21,19),fill=orange)
        d.line((16,20,21,20),fill=dark)
    else:
        d.rectangle((8,16,11,19),fill=green);d.rectangle((7,18,12,20),fill=orange)
        d.line((7,21,12,21),fill=dark)
        d.rectangle((15,16,18,19),fill=green);d.rectangle((15,18,20,20),fill=orange)
        d.line((15,21,20,21),fill=dark)
    return im


def _rider_pose(step, jumping=False):
    """A seated rider; the dinosaur's legs and head move independently."""
    im=Image.new('RGBA',(32,36))
    im.alpha_composite(_dino_pose(step, jumping=jumping), (6,14))
    # Redraw the mounted legs bent over the saddle rather than recycling the
    # standing character's wide walking stride.
    upper=_runner_pose(3 if jumping else (0,1,2,1)[step]).crop((0,0,20,19))
    im.alpha_composite(upper,(1,0))
    d=ImageDraw.Draw(im)
    d.polygon(((8,17),(13,18),(17,20),(17,22),(12,22),(9,21),(7,19)),fill='#203773')
    d.polygon(((9,18),(13,19),(16,21),(12,21),(9,20)),fill='#3970ca')
    d.rectangle((11,21,17,23),fill='#5e311c')
    d.rectangle((12,21,16,22),fill='#ba542b')
    d.point((16,21),fill='#e58b47')
    return im


def _coins_pose(step):
    """Four coin-spin poses above the question block."""
    im=Image.new('RGBA',(20,12));d=ImageDraw.Draw(im)
    widths=(4,3,1,3)
    for cx,cy,shift in ((3,5,0),(10,2,1),(17,5,2)):
        w=widths[(step+shift)%4]
        d.rectangle((cx-w//2,cy-2,cx+w//2,cy+3),fill='#975321')
        d.rectangle((cx-w//2,cy-3,cx+w//2,cy+2),fill='#ffd84e')
        if w>=3:d.line((cx-1,cy-2,cx-1,cy+1),fill='#fff7af')
    return im


def _cloud_pose(step):
    im=Image.new('RGBA',(22,10)); d=ImageDraw.Draw(im)
    _cloud(d,0,0,.65)
    # A pair of eye pixels makes it a character in the scene, not HUD decoration.
    d.point((8,6),fill='#6b9db5');d.point((11,6),fill='#6b9db5')
    return im


def _sprites(frame_limit=8):
    # Each sprite owns a disjoint restoration rectangle; the firmware restores
    # it before each pose.  The runner's walk turns smoothly instead of teleporting.
    full = frame_limit >= 8
    poses = 4 if full else 2
    runner=[_runner_pose(i) for i in range(poses)]+[_runner_pose(i,True) for i in range(poses)]
    positions=list(range(0,49,3))+list(range(45,0,-3))
    jumps=(0,0,0,0,-3,-7,-12,-16,-18,-16,-12,-7,-3,0,0,0,
           0,0,0,0,-3,-7,-12,-16,-18,-16,-12,-7,-3,0,0,0)
    script=[]
    for i,x in enumerate(positions):
        moving_left=i>=17
        pose=(3 if jumps[i]<=-7 else i%3) if full else i%2
        script.append((pose+(poses if moving_left else 0),x,jumps[i]))
    dino_poses = 4 if full else 2
    dino_frames=[_dino_pose(i) for i in range(dino_poses)]
    dino_frames += [im.transpose(Image.Transpose.FLIP_LEFT_RIGHT) for im in dino_frames]
    return [
        {'x':30,'y':150,'frames':runner,'script':script,'step_ms':200},
        {'x':204,'y':156,'frames':dino_frames,
         'script':[(i%dino_poses+(dino_poses if i>=9 else 0),dx,0)
                   for i,dx in enumerate((0,1,2,3,4,5,6,7,8,7,6,5,4,3,2,1))],'step_ms':200},
        {'x':140,'y':93,'frames':[_coins_pose(i) for i in range(4)],
         'script':[(i%4,0,0) for i in range(8)],'step_ms':200},
        {'x':92,'y':50,'frames':[_cloud_pose(i) for i in range(1)],
         'script':[(0,dx,0) for dx in (0,1,2,3,4,5,6,7,8,7,6,5,4,3,2,1)],'step_ms':400},
    ]


def _text(draw, xy, text, font, colour='#ffffff'):
    """The white-on-dark offset mimics a SNES HUD and reads over the sky."""
    x,y=xy
    draw.text((x+1,y+1),text,font=font,fill='#163143')
    draw.text((x,y),text,font=font,fill=colour)


def _reserve_coins(draw,x,y,count,old):
    for i in range(3):
        left=x+i*10
        lit=count is not None and count>i
        draw.rectangle((left+1,y,left+5,y+8),fill='#173c4b')
        draw.rectangle((left,y+1,left+6,y+7),fill='#173c4b')
        draw.rectangle((left+1,y+1,left+5,y+7),fill='#ffcc3b' if lit else '#3e7390')
        if lit:
            draw.line((left+2,y+2,left+2,y+5),fill='#fff3a1')
            draw.line((left+4,y+2,left+4,y+6),fill='#d48927')
        else:
            draw.rectangle((left+2,y+2,left+4,y+6),fill='#26668c')
    if reset_icons.marked(count,old):
        draw.rectangle((x+30,y+4,x+31,y+5),fill='#adcfe0')
    if count is not None and count>3:
        _text(draw,(x+34,y+1),'+',face('press-start-2p.ttf',6),'#fff2bd')


def _pace(draw,x,y,pace):
    if pace is None:
        return
    quota,hours=pace
    for row,value in enumerate((math.ceil(quota/5)/4,round(hours*4)/4)):
        for i in range(5):
            left=x+i*11
            draw.rectangle((left,y+row*5,left+8,y+row*5+2),fill='#225271')
            width=round(9*max(0,min(1,value-i)))
            if width:
                draw.rectangle((left,y+row*5,left+width-1,y+row*5+2),
                               fill='#fff3ae' if row==0 else '#8ee9ff')


def _hud(image,snapshot):
    draw=ImageDraw.Draw(image);draw.fontmode='1'
    title=face('press-start-2p.ttf',8)
    amount=face('press-start-2p.ttf',15)
    small=face('press-start-2p.ttf',7)
    status=face('press-start-2p.ttf',6)
    # The blue item-reserve box is a characteristic part of the 16-bit HUD.
    # It is decorative: the adjacent numbers always come from the providers.
    draw.rounded_rectangle((137,2,163,30),radius=5,fill='#123653')
    draw.rounded_rectangle((139,3,161,27),radius=4,fill='#8bd1f4')
    draw.rounded_rectangle((142,6,158,25),radius=2,fill='#145597')
    draw.line((142,6,157,6),fill='#d7faff')
    draw.line((158,8,158,23),fill='#307fb2')
    for provider,x in (('codex',8),('claude',171)):
        row=_row(snapshot,provider)
        value,_,stale,reset=remaining_reading(row)
        count,old=banked_hearts(row)
        _text(draw,(x,3),provider.upper(),title,'#ffe086' if provider=='codex' else '#fff4db')
        if stale:
            _text(draw,(x+55,4),'OLD',status,'#ffd28f')
        value_text='--' if value is None else '<1%' if 0<value<1 else f'{round(value)}%'
        _text(draw,(x,16),value_text,amount,'#ffffff' if not stale else '#b6d7e2')
        _text(draw,(x,35),'RST '+reset.upper(),small,'#fff1bd')
        _reserve_coins(draw,x+84,4,count,old)
        if provider=='claude':
            _pace(draw,x+72,19,session_pace(row) if row.get('status')=='ok' else None)


def render_platform(snapshot,animated=False,anim_frames=8,scroll=False):
    """A weekly-usage game HUD over a locally animated platform level."""
    if animated and scroll:
        from token_tv import board_scroll
        version=scroll if type(scroll) is int and scroll in (2, 3, 4) else 1
        if version in (3, 4):
            try:
                board_scroll.encode(3)
            except (OSError, ValueError, Image.DecompressionBombError):
                # The original artwork is private and optional. A missing or
                # damaged local asset must never stop the rest of the display.
                version=2
        if version == 4:
            # Render the scoreboard as an outlined transparent overlay, so it
            # stays readable while the original landscape scrolls behind it.
            from token_tv.board_credits import apply_credit_badges
            hud=Image.new('RGBA',(320,48))
            _hud(hud,snapshot)
            apply_credit_badges([hud],['cockpit'],snapshot)
            outline=Image.new('RGBA',hud.size,'#102536')
            outline.putalpha(hud.getchannel('A').filter(ImageFilter.MaxFilter(3)))
            outline.alpha_composite(hud)
            from token_tv.board_low_quota import apply_one
            apply_one(outline,'cockpit',snapshot)         # the page is redrawn whole on every tick: the line belongs to the overlay
            payload=board_scroll.encode_fullscreen(outline)
            return board_scroll.first_image(version,payload),payload
        image=board_scroll.first_image(version)
        _hud(image,snapshot)
        return image,board_scroll.encode(version)
    image=_scenery().copy()
    _hud(image,snapshot)
    sprites=_sprites(anim_frames)
    if animated:
        return image,encode(sprites=sprites)
    paint_first_frame(image,sprites)
    return image
