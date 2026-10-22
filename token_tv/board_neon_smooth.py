"""Smooth native-resolution Neon City; the retro renderer remains available."""
from functools import lru_cache
import math
from pathlib import Path
from PIL import Image, ImageDraw
from token_tv.themes import face
from token_tv.board_art import _row
from token_tv.personal_faces import remaining_reading, session_pace
from token_tv.board_forge import _city_motion, _resets, BANDS
from token_tv import board_anim

@lru_cache(maxsize=1)
def backdrop():
    # The user's chosen city, at native resolution and its original crop/colors.
    # Smoothing the UI must never substitute a different skyline for this artwork.
    im=Image.new('RGB',(320,240),'#080f1b')
    with Image.open(Path(__file__).with_name('assets')/'neon-city.png') as source:
        if source.size!=(174,216):
            raise ValueError('Neon City requires the original prepared skyline crop')
        im.paste(source.convert('RGB'),(0,24))
    d=ImageDraw.Draw(im)
    d.text((10,4),'NEON CITY',font=face('orbitron.ttf',14),fill='#c2f6fa')
    d.line((10,22,166,22),fill='#355671')
    return im


def module(im,y,row,provider):
    d=ImageDraw.Draw(im);color='#ffda79' if provider=='codex' else '#e9dfcf'
    d.rounded_rectangle((181,y,313,y+105),radius=9,fill='#102031',outline='#294357')
    d.text((189,y+6),provider.upper(),font=face('oxanium.woff2',12),fill=color)
    # Preserve the exact saved-reset semantics; small bolts belong to this city's visual language.
    _resets(d,281,y+9,row,BANDS[provider])
    val,_,old,reset=remaining_reading(row)
    d.text((247,y+23),'--' if val is None else f'{round(val)}%',font=face('oxanium.woff2',35),fill=color,anchor='mt')
    d.rounded_rectangle((189,y+62,305,y+71),radius=3,fill='#263b4d')
    if val is not None and val>0:
        right=189+max(1,round(116*val/100));d.rounded_rectangle((189,y+62,right,y+71),radius=min(3,(right-189)//2),fill=color)
    pace=session_pace(row) if provider=='claude' else None
    if pace:
        for j,units in enumerate((math.ceil(pace[0]/5)/4,round(pace[1]*4)/4)):
            for k in range(5):
                x=207+k*16;yy=y+75+j*4;d.rectangle((x,yy,x+11,yy+2),fill='#263b4d')
                amount=min(1,max(0,units-k))
                if amount:d.rectangle((x,yy,x+max(1,round(12*amount))-1,yy+2),fill=color)
    d.text((189,y+88),'OLD' if old else 'RESET',font=face('oxanium.woff2',10),fill='#9db3c6')
    d.text((305,y+87),reset.replace(' ',''),font=face('oxanium.woff2',14),fill=color,anchor='rt')

@lru_cache(maxsize=1)
def smooth_motion():
    sprites=[]
    for original in _city_motion()[:2]:
        w,h=original['frames'][0].size
        frames=[]
        for phase in range(4):
            frame=Image.new('RGBA',(w*4,h*4))
            if phase!=3:
                d=ImageDraw.Draw(frame)
                d.ellipse((5,5,w*4-3,h*4-4),fill='#23384e')
                d.ellipse((w,4,w*3,h*2),fill='#81cfe7' if phase else '#46677e')
                d.line((8,h*4-5,w*4-8,h*4-5),fill='#e188bc',width=3)
                d.ellipse((w*4-8,h*2-2,w*4-2,h*2+2),fill='#e3fcff')
                d.line((0,h*2+2,7,h*2+2),fill='#7f87c7',width=2)
            frames.append(frame.resize((w,h),Image.Resampling.LANCZOS))
        sprites.append({**original,'frames':frames})
    return tuple(sprites)


def render_neon_smooth(snapshot,animated=False):
    im=backdrop().copy()
    module(im,10,_row(snapshot,'codex'),'codex');module(im,123,_row(snapshot,'claude'),'claude')
    sprites=smooth_motion()  # Same bounded, disjoint air lanes; no old sign overlays.
    if animated:return im,board_anim.encode(sprites)
    return im
