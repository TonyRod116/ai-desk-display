"""Native board DMG-style shell; existing quota readers remain authoritative."""
from PIL import Image, ImageDraw
from token_tv.themes import Canvas, face
from token_tv.personal_faces import pixel, remaining_reading, banked_hearts, hearts, bars, session_pace, session_pace_line, lcd_grid
from token_tv.display import overview_rows

def render_gameboy_board(data, screen=(320, 240), grid=None):
    # Landscape adaptation: preserve usable LCD area rather than shrink a whole handheld.
    im=Image.new('RGB',(320,240),'#c7c5bc');d=ImageDraw.Draw(im)
    for y in range(240):
        v=round(210-y*.10);d.line((0,y,319,y),fill=(v,min(255,v+1),v-7))
    d.rounded_rectangle((2,2,317,237),radius=13,outline='#eeeae1',width=2)
    d.line((8,8,311,8),fill='#aaa99f');d.line((9,9,310,9),fill='#e9e7dc')
    d.rounded_rectangle((9,15,310,211),radius=14,fill='#777681')
    d.rounded_rectangle((10,16,309,210),radius=13,outline='#96959d')
    d.line((19,24,78,24),fill='#8c3563',width=2)
    d.line((19,28,78,28),fill='#343e6a')
    d.line((257,24,299,24),fill='#8c3563',width=2)
    d.line((257,28,299,28),fill='#343e6a')
    d.text((166,25),'DOT MATRIX WITH STEREO SOUND',font=face('oxanium.woff2',7),fill='#e0deda',anchor='mm')
    # Recessed screen surround and a red power lamp, no pretend quota status.
    d.rectangle((21,35,299,201),fill='#3b3e35')
    d.line((21,35,299,35),fill='#292e26',width=2)
    d.ellipse((13,56,18,61),fill='#532439');d.ellipse((14,56,17,59),fill='#ea5360')
    paper,ink='#a4bd52','#263c25'
    cv=Canvas(paper,(274,160))
    rows=overview_rows(data)
    rows=[r for p in ('codex','claude') for r in rows if r['provider']==p][:2]
    for i,row in enumerate(rows):
        y=5+i*79
        value,period,old,reset=remaining_reading(row)
        cv.text((7,y),row['provider'].upper(),pixel(9),ink)
        count,old_count=banked_hearts(row)
        hearts(cv,94,y+1,count,ink,paper,scale=1,old=old_count,quiet=True)
        cv.text((266,y),'OLD' if old else 'WEEK',pixel(7),ink,anchor='ra')
        cv.text((7,y+19),'--' if value is None else f'{round(value)}%',pixel(25),ink)
        cv.text((266,y+21),'RESET',pixel(7),ink,anchor='ra')
        cv.text((266,y+35),reset.replace(' ',''),pixel(12),ink,anchor='ra')
        bars(cv,7,y+53,260,value,ink,paper,old)
        session_pace_line(cv,7,y+65,260,session_pace(row),ink,'#87975b',ink,row=3)
    lcd=cv.finish().convert('RGB')
    # LCD shadow is offset by one pixel; a restrained column grid avoids shimmer.
    shadow=Image.new('RGB',lcd.size,paper);shadow.paste(lcd,(1,1));lcd=Image.blend(shadow,lcd,.88)
    lcd=lcd_grid(lcd,ink,strength=.09,axes='vertical')
    im.paste(lcd,(24,38));d=ImageDraw.Draw(im)
    d.text((18,220),'Nintendo',font=face('oxanium.woff2',10),fill='#333e6a')
    d.text((71,218),'GAME BOY',font=face('orbitron.ttf',12),fill='#333e6a')
    d.text((169,222),'TM',font=face('oxanium.woff2',5),fill='#333e6a')
    # Small moulded speaker slots and burgundy controls remain in the casing.
    for x in range(260,303,7):
        d.line((x,222,x-5,232),fill='#a19f99',width=3)
        d.line((x,222,x-5,231),fill='#787780')
    for x,y in ((220,225),(240,220)):
        d.ellipse((x-6,y-5,x+6,y+6),fill='#a5a19c')
        d.ellipse((x-5,y-5,x+5,y+4),fill='#73264b')
        d.arc((x-4,y-4,x+4,y+3),190,285,fill='#ad5475')
    return im
