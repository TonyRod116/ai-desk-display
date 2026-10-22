"""Fine local architectural lighting inspired by the reference original city palette.

The underlying photograph is unchanged. Small supersampled window banks follow
facade planes, with sparse uneven occupancy and restrained optical glow. This is
native UI scenery, not a pixel-art downsample or an external generated image.
"""
import random
from PIL import Image, ImageChops, ImageDraw, ImageFilter

# x, y, width, height, vertical slope, horizontal/vertical window spacing.
# The sky and river are excluded. Different planes have different room sizes.
PANES = (
    (45, 16, 25, 34, .04, 3.1, 3.6), (78, 37, 15, 17, -.08, 2.5, 3.5),
    (48, 80, 16, 39, .08, 3.1, 4.2), (74, 82, 18, 35, -.05, 2.8, 4.4),
    (57, 139, 42, 19, -.05, 3.7, 4.0), (55, 178, 43, 23, -.16, 3.6, 4.1),
    (55, 206, 28, 12, -.21, 3.1, 3.7),
    (270, 25, 18, 53, .04, 2.8, 4.3), (270, 99, 23, 18, .07, 3.3, 4.0),
    (265, 129, 28, 22, .09, 3.3, 3.7), (261, 171, 31, 44, .12, 3.4, 4.0),
    (7, 149, 15, 48, -.05, 3.1, 5.2), (305, 180, 10, 37, .18, 3.0, 5.1),
    (122, 77, 10, 63, .08, 2.8, 5.2), (157, 113, 10, 36, -.04, 2.8, 4.6),
    (237, 100, 9, 48, .02, 2.5, 4.5), (180, 138, 12, 17, .04, 2.8, 3.8),
)
COLORS = ((90, 238, 255), (255, 110, 198), (255, 196, 97),
          (126, 162, 255), (181, 246, 243), (255, 106, 113))
NEONS = (
    ((45,43,69,43),(84,228,255)), ((76,46,93,44),(255,99,205)),
    ((51,74,90,76),(255,75,193)), ((52,124,99,122),(75,229,255)),
    ((58,157,100,154),(255,90,193)), ((54,201,94,192),(74,221,255)),
    ((270,43,287,43),(67,232,255)), ((271,77,290,76),(255,106,197)),
    ((267,121,293,124),(95,225,255)), ((263,154,291,157),(255,111,190)),
    ((260,168,291,175),(74,228,246)), ((265,211,291,216),(255,181,100)),
    ((94,82,94,112),(255,98,192)), ((289,26,289,69),(84,232,255)),
    ((294,129,294,151),(255,114,203)), ((301,190,301,216),(88,219,255)),
    ((8,143,25,143),(70,230,255)), ((302,174,315,177),(255,92,186)),
)


def enrich_city(source):
    scale = 4
    layer = Image.new('RGB', (source.width * scale, source.height * scale))
    draw = ImageDraw.Draw(layer)
    rng = random.Random(6067)
    for x,y,w,h,slope,sx,sy in PANES:
        for row in range(int(h/sy)):
            for col in range(int(w/sx)):
                if rng.random() > .82:
                    continue
                px,py = x + col*sx + .8, y + row*sy + col*sx*slope
                color = COLORS[rng.randrange(len(COLORS))]
                strength = rng.uniform(.65,1.0)
                color = tuple(round(c*strength) for c in color)
                ww,hh = rng.uniform(.65,1.35),rng.uniform(.6,.95)
                draw.rectangle((round(px*scale),round(py*scale),round((px+ww)*scale),round((py+hh)*scale)),fill=color)
    for (x0,y0,x1,y1),color in NEONS:
        # Small breaks and unequal intensities keep signs from becoming HUD bars.
        for segment in range(7):
            if segment == 4:
                continue
            t0,t1=segment/7,(segment+.72)/7
            xy=(round((x0+(x1-x0)*t0)*scale),round((y0+(y1-y0)*t0)*scale),
                round((x0+(x1-x0)*t1)*scale),round((y0+(y1-y0)*t1)*scale))
            draw.line(xy,fill=color,width=3)
    detail=layer.resize(source.size,Image.Resampling.LANCZOS)
    glow=detail.filter(ImageFilter.GaussianBlur(.75)).point(lambda v:round(v*.48))
    return ImageChops.screen(ImageChops.screen(source,detail),glow)
