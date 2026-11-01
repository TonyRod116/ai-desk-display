"""Original 16-bit island scenery for the resident side-scrolling level.

All drawing is local. The 512-pixel world is periodic, including the terrain,
so the camera can travel forever without a visible end or network frames.
"""
from functools import lru_cache
import random

from PIL import Image, ImageDraw

W, H = 512, 96


def heights():
    """Gentle contiguous slopes on which the rider can stay grounded."""
    points = ((0, 77), (42, 77), (75, 65), (104, 65), (136, 77),
              (249, 77), (285, 66), (326, 66), (359, 77), (512, 77))
    out = []
    for x in range(W):
        for (x0,y0),(x1,y1) in zip(points,points[1:]):
            if x0 <= x < x1:
                out.append(round(y0 + (y1-y0)*(x-x0)/(x1-x0)))
                break
    return bytes(out)


def _wrapped(draw_fn, x, *args):
    for shift in (-W, 0, W):
        draw_fn(x+shift, *args)


def _cloud(d, x, y, w):
    # Long flat, scalloped cloud banks with a dithered blue underside.
    d.rounded_rectangle((x,y+3,x+w,y+13), radius=5, fill='#b6e3ee')
    d.rounded_rectangle((x+3,y,x+w-2,y+10), radius=5, fill='#f3ffff')
    d.rectangle((x+5,y+4,x+w-5,y+8), fill='#f3ffff')
    for i in range(3,w-2,2):
        d.point((x+i,y+10+(i//2)%2), fill='#9ed3e3')


def _hill(d, x, top, width, bottom, pale=False):
    edge = '#225f8a' if not pale else '#77aab6'
    base = '#81bbd4' if not pale else '#c5e8e3'
    cap = '#e1f7f1' if not pale else '#f0ffff'
    r = width//2
    d.rounded_rectangle((x,top,x+width,bottom+r), radius=r, fill=edge)
    d.rounded_rectangle((x+1,top+1,x+width-4,bottom+r), radius=r-2, fill=base)
    # The right rim is a distinctive checkerboard, visible on a small LCD.
    for yy in range(top+r-2,bottom):
        for xx in range(x+width-8,x+width-2):
            if (xx+yy)%2 == 0:
                d.point((xx,yy),fill='#4584aa' if not pale else '#9acdcc')
    for dx,dy in ((width//4,25),(width*2//3,41),(width//3,60)):
        cy=top+dy
        if cy+8 < bottom:
            d.rounded_rectangle((x+dx,cy,x+dx+6,cy+10), radius=3, fill=cap)
            d.line((x+dx+2,cy+1,x+dx+4,cy+1),fill='#ffffff')


def _bush(d, x, y, scale=1):
    p=lambda n: n*scale
    d.polygon([(x,y),(x+p(2),y-p(5)),(x+p(4),y-p(5)),(x+p(6),y-p(10)),
               (x+p(9),y-p(7)),(x+p(12),y-p(12)),(x+p(15),y-p(8)),
               (x+p(18),y-p(10)),(x+p(22),y-p(5)),(x+p(24),y-p(4)),
               (x+p(26),y),(x+p(25),y+p(1)),(x,y+p(1))], fill='#094a2a')
    d.polygon([(x+p(2),y-p(1)),(x+p(4),y-p(5)),(x+p(6),y-p(5)),
               (x+p(7),y-p(8)),(x+p(10),y-p(5)),(x+p(12),y-p(10)),
               (x+p(15),y-p(6)),(x+p(18),y-p(8)),(x+p(22),y-p(3)),
               (x+p(24),y-p(3)),(x+p(24),y-p(1))],fill='#08c735')
    for dx,dy in ((6,-4),(14,-7),(20,-3)):
        d.rectangle((x+p(dx),y+p(dy),x+p(dx+1),y+p(dy+1)),fill='#a7ff98')


def _block(d,x,y):
    # Turn blocks: yellow-orange, bevelled and riveted, with no fake score.
    d.rectangle((x,y,x+13,y+13), fill='#67411d')
    d.rectangle((x+1,y+1,x+12,y+11), fill='#f6a522')
    d.line((x+1,y+1,x+12,y+1),fill='#fff181')
    d.line((x+1,y+2,x+1,y+10),fill='#ffd94c')
    d.line((x+2,y+11,x+11,y+11),fill='#af611e')
    for xx,yy in ((2,3),(11,3),(2,10),(11,10)):
        d.point((x+xx,y+yy),fill='#9b5b20')
    d.rectangle((x+5,y+4,x+8,y+8),fill='#fff06a')
    d.line((x+6,y+5,x+7,y+7),fill='#e78924')


def _coin(d,x,y):
    d.ellipse((x,y,x+5,y+10),fill='#8d4b16')
    d.ellipse((x+1,y,x+4,y+9),fill='#ffdd42')
    d.line((x+2,y+1,x+2,y+7),fill='#fff7ab')
    d.line((x+4,y+2,x+4,y+7),fill='#d79020')


def _koopa(d,x,feet):
    """A small shelled rival that the rider can jump over."""
    y=feet-15
    ink='#323323'
    d.ellipse((x+4,y+4,x+13,y+13),fill=ink)
    d.ellipse((x+5,y+5,x+12,y+12),fill='#3266c0')
    d.ellipse((x+7,y+6,x+11,y+10),fill='#8ec8ff')
    d.line((x+6,y+11,x+11,y+12),fill='#f5e8b6')
    d.polygon(((x+4,y+6),(x+2,y+5),(x+1,y+7),(x,y+8),(x+1,y+11),
               (x+3,y+12),(x+4,y+14),(x+8,y+14),(x+8,y+11)),fill='#df6b1d',outline=ink)
    d.rectangle((x+1,y+6,x+4,y+9),fill='#ffad36')
    d.rectangle((x+2,y+4,x+4,y+7),fill='#fff5d5')
    d.point((x+2,y+5),fill='#19221c')
    d.rectangle((x+2,y+13,x+5,y+14),fill='#ff9d2c')
    d.rectangle((x+6,y+13,x+9,y+14),fill='#ff9d2c')
    d.line((x+1,y+15,x+5,y+15),fill=ink)
    d.line((x+7,y+15,x+11,y+15),fill=ink)


@lru_cache(maxsize=2)
def scenery(zoom=False):
    im=Image.new('RGB',(W,H),'#0754aa');d=ImageDraw.Draw(im)
    ground=heights()
    for x,y,w in ((3,25,43),(89,13,42),(170,32,38),(250,18,46),
                  (334,27,44),(423,15,43),(491,31,40)):
        _wrapped(lambda xx,yy,ww:_cloud(d,xx,yy,ww),x,y,w)
    for x,top,width,pale in ((-29,13,61,False),(45,4,77,False),(116,20,61,False),
                             (171,2,62,True),(222,15,70,False),(293,6,75,False),
                             (359,18,62,False),(412,1,67,True),(474,13,65,False)):
        _wrapped(lambda xx,tt,ww,pp:_hill(d,xx,tt,ww,79,pp),x,top,width,pale)
    # Long low cloud banks in front of the mountains are characteristic of the level.
    for x,y,w in ((8,69,70),(133,69,61),(271,69,70),(405,69,71)):
        _wrapped(lambda xx,yy,ww:_cloud(d,xx,yy,ww),x,y,w)
    # The ground and the turf are generated from the same height map used by the rider.
    for x in range(W):
        y=ground[x]
        d.line((x,y,x,H-1),fill='#c69a5c')
        d.line((x,y,x,y+2),fill='#16c52f')
        d.point((x,y),fill='#a0ff75')
        d.point((x,y+3+(x//3)%2),fill='#153c24')
        d.point((x,y+4+(x//3)%2),fill='#775323')
    rnd=random.Random(4920)
    for _ in range(1600):
        x=rnd.randrange(W);y=rnd.randrange(H)
        if y>ground[x]+5:
            c=('#f3d075','#dfb971','#a87c48')[rnd.randrange(3)]
            d.rectangle((x,y,x+(rnd.randrange(5)==0),y+1),fill=c)
    for x in (78,138,197,362,404,448,496):
        y=ground[(x+13)%W]
        _wrapped(lambda xx,yy:_bush(d,xx,yy),x,y)
    blocks=((157,36),(171,36),(185,36),(413,36),(427,36),(441,36)) if zoom else (
        (157,46),(171,46),(185,46),(349,43),(363,43),(377,43))
    for x,y in blocks:
        _block(d,x,y)
    coins=((171,30),(182,25),(193,23),(204,28),
           (427,30),(438,25),(449,23),(460,28)) if zoom else (
        (146,33),(157,27),(168,24),(179,27),(190,33),
        (333,31),(344,25),(355,22),(366,25),(377,31))
    for x,y in coins:
        _coin(d,x,y)
    # Obstacles sit where the periodic jump animation reaches its apex.
    for x in (105, 361):
        feet=ground[(x+6)%W]
        if zoom:
            # Keep rivals in proportion to the enlarged mounted characters.
            rival=Image.new('RGBA',(14,16))
            _koopa(ImageDraw.Draw(rival),0,15)
            rival=rival.resize((10,12),Image.Resampling.NEAREST)
            im.paste(rival,(x,feet-11),rival)
        else:
            _koopa(d,x,feet)
    # Tiny flowers and grass are periodic objects, never tied to quota values.
    for x in (29,57,142,215,237,394,428,465):
        y=ground[x]
        d.line((x,y-6,x,y-1),fill='#14592c')
        d.point((x-1,y-5),fill='#fff1a1');d.point((x+1,y-5),fill='#fff1a1')
        d.point((x,y-6),fill='#fff1a1');d.point((x,y-5),fill='#ff8a6c')
    return im
