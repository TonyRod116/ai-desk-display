"""Original 320x240 arcade stage and two individually drawn mascots.

The stage uses native resolution. Four non-overlapping pixel-art sprites animate
locally; no per-frame network traffic or firmware change is needed.
"""
from PIL import Image, ImageColor, ImageDraw

from token_tv import board_arcade_fighters as fighters

INK = '#121427'


def poly(draw, points, fill, outline=INK):
    draw.polygon(points, fill=fill, outline=outline)


def _far_roofs(d):
    """A varied lantern-lit town far below the open rooftop."""
    blocks = (
        (0, 158, 24, 14, '#477d91', '#ffd794'),
        (21, 153, 22, 19, '#bb696c', '#ffe0a3'),
        (40, 159, 28, 13, '#485f9a', '#ffdb94'),
        (68, 154, 24, 18, '#a07b55', '#ffe3a9'),
        (91, 161, 25, 11, '#8d5d8d', '#ffd596'),
        (113, 155, 32, 17, '#38918d', '#ffe3a4'),
        (144, 160, 22, 12, '#b06b70', '#ffe0a1'),
        (163, 153, 26, 19, '#538d86', '#ffe5a9'),
        (188, 159, 25, 13, '#ad7960', '#ffd594'),
        (211, 154, 30, 18, '#477f9d', '#ffe3a6'),
        (239, 160, 20, 12, '#956a9a', '#ffd89b'),
        (257, 154, 27, 18, '#438e8b', '#ffe2a7'),
        (282, 158, 38, 14, '#b56e72', '#ffdc9c'),
    )
    for n, (x, y, w, h, wall, light) in enumerate(blocks):
        d.rectangle((x+2, y+4, x+w-2, y+h), fill=wall)
        poly(d, [(x-2,y+4),(x+2,y+2),(x+5,y),(x+w-6,y),
                 (x+w-2,y+2),(x+w+2,y+4),(x+w,y+6),(x,y+6)],
             '#1e3d55', outline='#d6c8ae')
        d.line((x+4,y+2,x+w-5,y+2), fill='#b7d3cd')
        for j, wx in enumerate(range(x+5, x+w-4, 7)):
            d.rectangle((wx,y+8,wx+3,min(y+h-2,y+12)),fill='#262d48')
            if (n+j)%3 != 1:
                d.line((wx+1,y+9,wx+2,y+9),fill=light)
        if n%3 == 0:
            d.line((x+w//2,y-4,x+w//2,y),fill='#8399aa')
            d.point((x+w//2,y-5),fill='#e4c1a4')


def _distant_landmarks(d):
    """Two asymmetrical, hand-detailed landmarks above the little town."""
    # Left: a green copper-roofed watchtower, with open balconies.
    d.rectangle((99,148,123,170),fill='#293e51',outline='#17283e')
    d.rectangle((102,151,120,167),fill='#e6bc7d',outline='#263c4c')
    for x in (104,110,116):
        d.rectangle((x,153,x+3,160),fill='#20374d')
        d.line((x+1,154,x+1,158),fill='#ffe8ab')
        d.point((x+2,155),fill='#fff2c3')
    d.line((101,163,122,163),fill='#ffdfa2')
    for x in (104,110,116):d.line((x,164,x,167),fill='#f4d4a0')
    poly(d,[(95,148),(100,145),(104,140),(118,140),(122,145),
            (127,148),(125,150),(97,150)],'#1e5261','#172c40')
    d.line([(98,147),(104,142),(118,142),(124,147)],fill='#b4d7c9')
    for x in range(105,118,3):d.line((x,143,x+1,145),fill='#73b8ae')
    d.rectangle((105,134,116,141),fill='#aa8273',outline='#293e50')
    d.rectangle((108,136,113,139),fill='#ffda94',outline='#293e50')
    poly(d,[(101,134),(106,130),(115,130),(120,134),(118,136),(103,136)],
         '#20566b','#b6d4c8')
    d.line((111,127,111,130),fill='#e2c6a0')
    d.point((111,126),fill='#ffe3ac')
    # Right: a round masonry tower with warm slit windows and a bell roof.
    d.rectangle((192,151,214,170),fill='#42616a',outline='#23364b')
    d.rectangle((195,153,211,167),fill='#9bc8c3')
    for y in (155,159,163):
        d.line((195,y,211,y),fill='#6c9a99')
    d.rectangle((201,154,206,164),fill='#213d50',outline='#d8e8c8')
    d.line((203,155,203,162),fill='#fff0b4')
    d.line((205,156,205,161),fill='#ffd18e')
    poly(d,[(188,151),(192,147),(196,145),(197,140),(200,137),(205,136),
            (209,138),(211,144),(215,147),(218,151),(215,153),(190,153)],
         '#253e5a','#1c2b42')
    d.line([(192,149),(197,146),(199,141),(201,139),(205,138),(208,140),
            (210,146),(214,149)],fill='#bad6ce')
    d.line((197,150,210,150),fill='#efd0a4')
    d.line((203,133,203,137),fill='#e2bf91')
    d.point((203,132),fill='#ffe4a4')
    for x in (193,198,208,213):d.point((x,152),fill='#d9b698')
    # A mix of trees, chimneys, terraces and tiny lights, rather than cloned
    # roofs. They remain behind both fighters and the open fighting area.
    for x,y in ((89,160),(93,157),(129,161),(134,159),(154,160),
                (172,159),(180,160),(220,157),(225,159),(233,160)):
        d.line((x,y,x,y+8),fill='#344653')
        d.ellipse((x-3,y-3,x+3,y+2),fill='#3f655e',outline='#324e52')
        d.point((x-1,y-2),fill='#91a78b')
        d.point((x+2,y),fill='#6f9778')
    for x,y in ((126,165),(139,164),(150,166),(169,165),(180,166),(221,164)):
        d.point((x,y),fill='#ffe1a1')
        d.point((x+1,y),fill='#c98e73')


def _hillside_district(d):
    """Two different little hillside buildings, behind the open arena."""
    # A small temple tucked into the left slope. Its lit windows and stepped
    # copper roof remain readable as a few crisp pixels on the physical panel.
    d.rectangle((125,146,144,161),fill='#75535c',outline='#273b51')
    d.rectangle((128,149,141,159),fill='#f0cb8d')
    for x in (130,135,140):
        d.rectangle((x,151,x+2,156),fill='#263d50')
        d.point((x+1,152),fill='#fff2bc')
    poly(d,[(122,146),(126,143),(130,140),(140,140),(144,143),
            (148,146),(145,148),(124,148)],'#225366','#c8d7c0')
    d.line([(126,145),(130,142),(140,142),(144,145)],fill='#d4e0c9')
    d.line((134,136,134,140),fill='#d8bd9b')
    d.point((134,135),fill='#fff0b4')

    # The right building is a cooler, lower terrace, not a mirrored copy.
    d.rectangle((176,147,193,162),fill='#4c6c77',outline='#293d51')
    d.rectangle((179,150,190,160),fill='#aed4cc')
    d.rectangle((181,152,185,158),fill='#274256')
    d.line((182,153,184,153),fill='#fff0b7')
    d.line((187,152,189,157),fill='#69918f')
    poly(d,[(173,147),(177,144),(179,141),(189,141),(192,145),
            (196,147),(193,149),(175,149)],'#31435c','#d0d2c1')
    d.line([(177,146),(180,143),(189,143),(192,146)],fill='#d5dfce')
    d.line((190,139,190,142),fill='#d8b99d')
    d.point((190,138),fill='#ffdda1')

    # Rooftops, scattered foliage and warm little lights lead the eye from
    # the distant buildings to the existing town without filling the centre
    # of the fighting floor.
    for x,y in ((119,157),(123,154),(148,156),(151,158),(170,158),
                (174,155),(195,157),(198,159)):
        d.line((x,y,x,y+6),fill='#3b4b56')
        d.ellipse((x-2,y-3,x+2,y+1),fill='#57756c',outline='#3b5a59')
        d.point((x-1,y-2),fill='#a9b59a')
    for x,y in ((123,162),(128,164),(145,162),(151,164),(169,163),(174,162),(191,164)):
        d.point((x,y),fill='#f7d6a1')


def _hillside_trees(d):
    """Different silhouettes frame the mountain without blocking the arena."""
    # An irregular evergreen on the left: separate clusters and broken light
    # edges, instead of a single flat triangular tree.
    d.line([(115,159),(114,143),(111,128),(110,110)],fill='#394d50',width=2)
    for x,y in ((111,107),(107,116),(115,119),(104,126),(116,130),
                (101,135),(111,137),(120,140),(105,145),(117,149)):
        poly(d,[(x-6,y+3),(x-3,y),(x,y+1),(x+3,y-2),(x+7,y+3),
                (x+4,y+5),(x-5,y+5)],'#345d5d','#304b53')
        d.line((x-3,y+2,x+2,y+2),fill='#7b9b85')
        d.point((x+3,y+1),fill='#a2ad94')
    # The opposite side is a flowering tree with peach/pink blossoms and
    # visible forked branches; its soft colours separate it from the roofs.
    d.line([(215,158),(218,145),(219,131),(216,117),(212,106)],fill='#624b56',width=3)
    d.line([(218,136),(226,127),(230,116),(234,110)],fill='#624b56',width=2)
    d.line([(217,124),(209,119),(204,111)],fill='#69525c',width=2)
    d.line([(217,117),(222,111),(223,102)],fill='#69525c',width=2)
    poly(d,[(199,112),(202,106),(207,105),(210,101),(215,102),
            (219,98),(224,101),(226,104),(231,104),(235,108),
            (235,112),(240,116),(238,122),(233,123),(230,128),
            (224,129),(219,126),(214,129),(209,126),(204,126),
            (201,122),(197,118)],'#a9697c','#6c5668')
    # Interlocking asymmetrical masses create a canopy rather than a row of
    # identical circles. Tiny blossoms pick out the light-facing edges.
    for points, colour in (
        ([(201,112),(204,107),(210,106),(213,109),(210,114),(205,116)],'#d78d99'),
        ([(211,105),(215,102),(219,103),(221,107),(217,111),(212,110)],'#e39ca3'),
        ([(220,105),(224,103),(229,106),(230,110),(225,112),(221,110)],'#d68c99'),
        ([(230,110),(234,109),(237,113),(236,117),(231,118),(228,115)],'#e7a0a5'),
        ([(203,117),(207,114),(212,116),(215,120),(212,123),(206,122)],'#d7919e'),
        ([(214,114),(219,111),(225,113),(226,118),(222,121),(217,120)],'#e3a0a6'),
        ([(224,119),(229,116),(234,119),(234,123),(230,126),(225,125)],'#cc8393'),
        ([(211,123),(215,121),(220,123),(222,126),(218,127),(214,126)],'#c47c8d'),
    ):
        poly(d,points,colour,colour)
    # A few fine branches show through gaps in the blossoms.
    d.line([(216,127),(216,122),(213,119),(209,117)],fill='#906377')
    d.line([(217,123),(220,119),(225,117)],fill='#906377')
    d.line([(221,113),(224,110),(225,107)],fill='#ac7083')
    for x,y in ((204,109),(209,107),(215,104),(222,105),(226,108),(233,111),
                (205,118),(211,116),(217,114),(223,115),(231,120),(216,124)):
        d.point((x,y),fill='#ffe0cb')
        d.point((x+1,y+1),fill='#f4b7b4')


def _distant_village(d):
    """Small individual homes, terraces and lights climb the mountain slopes."""
    # The upper settlement is deliberately asymmetrical: separate houses,
    # stairways and gardens instead of one repeated row of identical roofs.
    homes = (
        (83,139,11,'#d9aa82','#374c65'),
        (97,132,13,'#e1ba90','#24536b'),
        (119,137,12,'#d7a783','#40536d'),
        (184,135,11,'#c2d2bc','#315b68'),
        (200,131,14,'#e0b797','#3f536c'),
        (225,139,12,'#b8d2c4','#27586a'),
    )
    for i, (x, y, w, wall, roof) in enumerate(homes):
        d.rectangle((x,y+4,x+w,y+12),fill=wall,outline='#3b4a5b')
        poly(d,[(x-2,y+4),(x+2,y+1),(x+4,y),(x+w-3,y),
                (x+w,y+3),(x+w+2,y+4),(x+w,y+6),(x,y+6)],roof,'#c3d0bc')
        d.line((x+2,y+3,x+w-2,y+3),fill='#a9c3ba')
        for j, wx in enumerate(range(x+2,x+w-1,5)):
            d.rectangle((wx,y+7,wx+2,y+10),fill='#293c50')
            if (i+j)%3 != 0:
                d.point((wx+1,y+8),fill='#ffe7a9')
        if i in (1,4):
            d.line((x+w-2,y-3,x+w-2,y+1),fill='#8ca4a0')
            d.point((x+w-2,y-4),fill='#f5cf9f')
    # Terraces, steps, gardens and warm lanterns describe a real settlement
    # without adding an obstacle to the fighting floor.
    for points in (
        [(76,151),(89,148),(98,149),(106,145)],
        [(105,154),(116,151),(125,152),(133,148)],
        [(181,151),(189,148),(200,149),(208,146)],
        [(207,154),(216,151),(227,152),(239,149)],
    ):
        d.line(points,fill='#bfad9e')
        for x,y in points[1:-1]:
            d.line((x,y,x+2,y+2),fill='#647c81')
    for x,y in ((79,151),(91,146),(104,148),(118,149),(128,145),
                (186,148),(197,145),(210,149),(221,148),(233,151)):
        d.line((x,y,x,y+3),fill='#496361')
        d.point((x-1,y-1),fill='#a9bca2')
        d.point((x+1,y-1),fill='#698f7d')
    for x,y in ((94,151),(115,153),(130,150),(188,151),(205,152),(225,153)):
        d.point((x,y),fill='#ffe6ac')
        d.point((x+1,y),fill='#d89d80')


def _roof(d, x, y, w, *, upper=False, jade=False):
    """Rows of individually shaded tiles, carved eaves and gold fasteners."""
    rise = 12 if upper else 14
    tile = '#16887b' if jade else '#4555a4'
    roof_edge = '#b8f1cf' if jade else '#c6c9ff'
    tile_rows = ('#8cdbb5','#176052','#b3efcb') if jade else ('#a5aff4','#313c80','#d0caff')
    poly(d, [(x-8,y+rise+4),(x+2,y+rise),(x+12,y+2),
             (x+w-13,y+2),(x+w-2,y+rise),(x+w+8,y+rise+4),
             (x+w+5,y+rise+8),(x+w-1,y+rise+8),
             (x+2,y+rise+8),(x-5,y+rise+8)], '#182d49', '#0b1a30')
    poly(d, [(x-3,y+rise+3),(x+4,y+rise),(x+13,y+4),
             (x+w-14,y+4),(x+w-4,y+rise),(x+w+3,y+rise+3),
             (x+w-1,y+rise+5),(x+1,y+rise+5)], tile, roof_edge)
    for row in range(3):
        yy = y+6+row*3
        inset = max(2, 12-row*4)
        d.line((x+inset,yy,x+w-inset-1,yy),fill=tile_rows[row])
        for j, xx in enumerate(range(x+inset+2+(row%2)*2,x+w-inset-2,6)):
            d.line((xx,yy-1,xx+2,yy+1),fill='#c1dcd2' if j%3 else '#f2dfb4')
            d.point((xx+1,yy+1),fill='#213a50')
    d.line((x-4,y+rise+5,x+w+4,y+rise+5),fill='#d7b596')
    d.line((x-6,y+rise+8,x+w+6,y+rise+8),fill='#15263c',width=2)
    for xx in range(x, x+w, 8):
        d.rectangle((xx,y+rise+7,xx+3,y+rise+9),fill='#728b8e',outline='#182b3d')
        d.point((xx+1,y+rise+8),fill='#e6c9a3')
    # Curved finials make the outline recognizable even at actual board size.
    for xx, direction in ((x-5,-1),(x+w+5,1)):
        d.line([(xx-direction*3,y+rise+7),(xx,y+rise+5),
                (xx+direction*2,y+rise+1),(xx+direction,y+rise-2)],fill='#b8c2ac',width=2)
        d.point((xx+direction,y+rise-3),fill='#f7d198')


def _arena_festival(d):
    """Hand-drawn banners, lanterns and roof ornaments frame the arena."""
    # Each pennant has its own cut, colours and painted emblem. They sit
    # behind the fighters and outside the labels, like scenery in an arcade.
    d.line((83,91,83,132),fill='#263448',width=2)
    d.line((84,92,84,130),fill='#f2c590')
    d.ellipse((81,88,85,92),fill='#ffe1a4',outline='#76554e')
    poly(d,[(85,95),(98,97),(101,101),(98,105),(100,111),
            (97,116),(85,113)],'#a33650','#4a3045')
    d.line([(86,97),(96,99),(98,101)],fill='#f7b78b')
    d.line([(86,111),(96,114)],fill='#d9736b')
    d.polygon([(91,101),(94,102),(96,105),(93,108),(90,106)],fill='#ffd28a')
    d.point((93,104),fill='#fff3bd')
    d.line((87,114,87,119),fill='#e7bd88')

    d.line((235,89,235,132),fill='#26394c',width=2)
    d.line((236,90,236,130),fill='#e8c495')
    d.ellipse((233,86,237,90),fill='#ffe1a4',outline='#76554e')
    poly(d,[(234,94),(221,96),(219,100),(221,104),(218,109),
            (221,115),(234,112)],'#287381','#244456')
    d.line([(233,96),(223,98),(221,100)],fill='#b5e5ce')
    d.line([(233,110),(223,113)],fill='#76c1b7')
    d.ellipse((225,101,230,107),fill='#e4c88d',outline='#264e58')
    d.point((228,102),fill='#fff3bb')
    d.line((232,113,232,118),fill='#e7bd88')

    # Far lanterns hang on a delicate cord. Their different shapes and warm
    # glows add life in the depth layer without a foreground prop in the way.
    d.line([(118,157),(130,159),(145,160),(160,161),(175,160),
            (190,158),(202,156)],fill='#504f5c')
    for i,(x,y) in enumerate(((126,158),(142,159),(158,160),
                               (175,159),(191,157))):
        d.line((x,y,x,y+2),fill='#d2b290')
        d.rectangle((x-1,y+2,x+1,y+4),fill='#7f4350')
        d.point((x,y+3),fill='#ffdc9e' if i%2 else '#ffb783')
        d.point((x,y+5),fill='#e6ba90')

    # Oversized carved finials, painted tile ends and hanging cords make the
    # near buildings look like different, built structures at actual size.
    for x,side in ((0,1),(319,-1)):
        d.line([(x,117),(x+side*4,115),(x+side*7,116),
                (x+side*9,120),(x+side*7,122)],fill='#f0ca96',width=2)
        d.point((x+side*5,117),fill='#fff0bd')
        d.line((x+side*9,121,x+side*9,126),fill='#8d736e')
        d.point((x+side*9,127),fill='#ffd999')
    for x,y in ((24,124),(33,124),(44,124),(266,121),(278,121),(290,121)):
        d.rectangle((x,y,x+4,y+2),fill='#39556a',outline='#e1c5a5')
        d.point((x+2,y+1),fill='#fff0c4')


def _upper_clouds(d):
    """Layered, hand-pixelled evening clouds across the upper backdrop."""
    # Uneven silhouettes and separately lit edges make these read as clouds,
    # rather than a row of repeated strips. The clear spaces leave room for
    # the stars, meteor and the scoreboard above the scene.
    clouds = (
        ([(0,82),(5,80),(12,80),(16,77),(23,77),(27,80),(33,80),
          (36,84),(44,83),(49,86),(57,86),(62,89),(69,89),(73,93),
          (70,96),(57,96),(52,98),(38,97),(30,99),(19,97),(8,98),(0,96)],
         '#655772','#a77d88','#e4b4a6'),
        ([(48,78),(55,77),(59,75),(66,75),(70,77),(78,77),(82,80),
          (91,80),(95,82),(106,82),(111,85),(122,85),(126,88),(120,91),
          (106,90),(97,92),(86,91),(77,93),(67,91),(57,92),(49,89),(42,87)],
         '#5f6078','#988a98','#d9b8ae'),
        ([(113,76),(121,75),(125,73),(132,73),(137,76),(145,76),
          (149,78),(157,78),(161,81),(172,81),(175,84),(170,87),
          (158,87),(151,89),(140,88),(132,90),(121,88),(113,89),(107,86)],
         '#59657f','#9296a4','#d5beb9'),
        ([(183,81),(190,79),(197,79),(201,76),(209,76),(214,78),(222,78),
          (226,81),(235,81),(239,84),(249,84),(253,87),(249,90),
          (238,90),(232,92),(221,91),(214,93),(204,91),(194,92),(185,89)],
         '#5e627b','#a28a98','#e5b6ad'),
        ([(247,76),(254,75),(258,73),(266,73),(271,76),(280,76),
          (284,79),(294,78),(299,81),(310,81),(319,84),(319,96),
          (307,95),(299,97),(288,95),(280,97),(271,94),(261,95),
          (253,92),(244,92),(240,89),(242,85)],
         '#625772','#a57e8d','#edb8a9'),
    )
    for points, shade, mid, light in clouds:
        poly(d, points, shade, shade)
        # A broken highlight follows the actual profile; shorter inner lines
        # give each bank volume at the display's real resolution.
        for a, b in zip(points[:len(points)//2], points[1:len(points)//2+1]):
            if b[0] > a[0]:
                d.line((a[0],a[1],b[0],b[1]),fill=mid)
        x0=min(p[0] for p in points); x1=max(p[0] for p in points)
        y0=min(p[1] for p in points)
        d.line((x0+7,y0+6,min(x0+18,x1-4),y0+6),fill=light)
        d.line((x0+15,y0+9,min(x0+32,x1-3),y0+9),fill=mid)
        d.line((x0+24,y0+12,min(x0+38,x1-3),y0+12),fill=light)
    # Contrasting little cloud fragments connect the banks to the horizon.
    for x,y,w in ((4,102,30),(49,99,22),(92,98,25),(198,100,27),
                   (242,100,21),(282,102,31)):
        d.line((x,y,x+w,y),fill='#7d879a')
        d.line((x+5,y-2,x+w-6,y-2),fill='#c4a9aa')
        d.line((x+10,y-3,x+w-11,y-3),fill='#e5c4b7')
        d.line((x+4,y+2,x+w-8,y+2),fill='#596e85')


def _festival_sky(d):
    """A festival cord hangs between the two visible banner poles."""
    cord = [(83,90),(105,91),(126,93),(145,95),(160,96),
            (176,95),(196,93),(215,90),(235,88)]
    d.line(cord,fill='#28364e',width=2)
    d.line(cord,fill='#ffe1ad')
    # Alternating paper lanterns and little pennants: the irregular placement
    # gives the town a lived-in festival rather than a symmetrical overlay.
    for x,y,body,edge,shine in (
        (105,91,'#d34258','#663546','#ffe1ac'),
        (134,94,'#ed9b46','#754653','#fff0c1'),
        (180,95,'#22a596','#304857','#d4f1d9'),
        (207,91,'#db6954','#75404c','#ffe4b1'),
    ):
        d.line((x,y,x,y+2),fill='#dbbd9b')
        d.rectangle((x-3,y+2,x+3,y+7),fill=body,outline=edge)
        d.line((x-1,y+3,x+1,y+3),fill=shine)
        d.line((x,y+4,x,y+6),fill=shine)
        d.point((x,y+8),fill='#e8c497')
    for x,y,colour in ((116,92,'#f4a677'),(151,96,'#86e7c1'),
                       (169,96,'#f5ba85'),(196,93,'#a8c7ff')):
        d.polygon(((x,y),(x+5,y+1),(x+2,y+6)),fill=colour)
        d.point((x+2,y+2),fill='#fff0cd')


def draw_stage(im):
    d = ImageDraw.Draw(im)
    # Dark star-friendly sky and bands of dusk. The open centre gives the
    # firmware's meteor and cloud sprite a clear, undisturbed route.
    d.rectangle((0,72,319,175),fill='#33405e')
    d.rectangle((0,109,319,127),fill='#405b77')
    d.rectangle((0,128,319,146),fill='#58778a')
    d.rectangle((0,147,319,175),fill='#8c8991')
    _upper_clouds(d)
    # A low evening sun sits behind the mountain and keeps the upper half
    # of the arena interesting without hiding the meteor or either HUD.
    d.ellipse((132,91,187,146),fill='#718397')
    d.ellipse((137,96,182,141),fill='#b8aaa6')
    d.ellipse((140,99,179,138),fill='#e5c5a8')
    d.ellipse((143,102,176,135),fill='#f7dfbd')
    d.line((139,110,181,110),fill='#edd4ba')
    d.line((137,119,183,119),fill='#cfb9ad')
    d.line((142,124,178,124),fill='#e2c2ae')
    for x,y,w in ((8,104,30),(58,112,24),(181,105,28),(244,111,37),
                   (9,139,25),(262,138,36)):
        d.line((x,y,x+w,y),fill='#8ea4b2')
        d.line((x+6,y-2,x+w-6,y-2),fill='#637f94')
        d.line((x+9,y+1,x+w-9,y+1),fill='#aec1bd')
    # Layered, hand-painted dusk clouds echo the streaked skies of classic
    # arcade backgrounds. Their broken outlines stay clear of the moving stars.
    for x,y,w in ((86,113,38),(148,111,39),(206,115,29)):
        d.line((x,y,x+w,y),fill='#7493a1')
        d.line((x+5,y-1,x+w-8,y-1),fill='#8ea8ae')
        d.line((x+12,y-2,x+w-15,y-2),fill='#b5b8b1')
        d.line((x+3,y+1,x+18,y+1),fill='#53758b')
        d.line((x+w-14,y+2,x+w-3,y+2),fill='#597a8e')
    # Broken bands high in the sky add painted depth while keeping the
    # central meteor corridor and the player labels clear.
    for x,y,w in ((83,94,37),(95,102,39),(197,96,36),(186,104,29)):
        d.line((x+3,y,x+w,y),fill='#556c83')
        d.line((x,y+1,x+w-8,y+1),fill='#78909a')
        d.line((x+7,y+2,x+w-4,y+2),fill='#a3adb0')
        d.line((x+12,y+3,x+w-12,y+3),fill='#667f8d')
    # The cord must be in front of the sun and meet the two pole finials.
    _festival_sky(d)
    # Layered mountains; the cool silhouettes create distance behind the town.
    poly(d, [(0,158),(16,149),(33,151),(52,139),(69,151),(86,144),
             (101,152),(119,147),(136,155),(153,147),(169,151),(184,145),
             (204,153),(222,143),(238,150),(259,137),(277,149),(299,143),
             (319,150),(319,175),(0,175)], '#60788b', '#748b98')
    # A distant snow-capped mountain, hand-shaded like a painted arcade
    # backdrop. Its uneven ridges and warm snow catch the last evening light.
    poly(d, [(63,165),(90,157),(108,149),(126,139),(141,132),
             (154,121),(158,124),(162,122),(169,127),(181,136),
             (199,145),(222,155),(248,165)], '#70849a', '#93a4aa')
    poly(d, [(106,153),(127,141),(143,132),(153,124),(158,127),
             (162,125),(168,130),(177,136),(186,142),(174,139),
             (168,135),(163,136),(159,132),(154,134),(150,132),
             (144,137),(139,138),(132,143)], '#a1abb0', '#a1abb0')
    poly(d, [(144,133),(154,122),(158,125),(162,123),(169,128),
             (175,135),(170,133),(167,134),(162,130),(159,132),
             (155,128),(152,131),(150,130),(146,134)], '#dfd1c0', '#dfd1c0')
    d.line([(149,130),(154,124),(158,127),(162,125),(167,129)],fill='#f4dfc9')
    d.line([(162,133),(168,137),(171,142),(180,146)],fill='#8293a1')
    d.line([(137,141),(131,145),(123,148)],fill='#c2b9b4')
    d.line([(184,145),(193,150),(199,151)],fill='#8e9ba5')
    # Irregular strata and shaded gullies stop the mountain reading as one
    # flat triangle at panel size. The snowy summit stays the visual anchor.
    d.line([(153,136),(148,141),(142,143),(137,148),(128,152)],fill='#c7b9b0')
    d.line([(158,135),(160,141),(166,145),(168,150),(177,155)],fill='#617a91')
    d.line([(151,140),(153,143),(150,146),(145,149)],fill='#9ca4a8')
    d.line([(164,139),(171,144),(175,148),(183,151)],fill='#b7b2b0')
    d.line([(123,155),(132,151),(139,151)],fill='#8899a4')
    d.line([(179,151),(186,154),(193,155)],fill='#8e9da6')
    for x,y in ((116,151),(121,149),(129,146),(177,142),(185,148),(207,153)):
        d.point((x,y),fill='#c5b6b0')
    poly(d, [(0,164),(16,157),(36,161),(55,152),(74,162),(96,155),
             (119,163),(143,157),(165,164),(190,155),(210,161),(232,154),
             (253,161),(279,151),(297,160),(319,155),(319,175),(0,175)],
         '#3f536e', '#74899b')
    for x,y in ((52,140),(86,145),(183,146),(259,138),(278,152)):
        d.line((x,y,x+4,y+3),fill='#b7b5ae')
        d.line((x+5,y+3,x+9,y+6),fill='#8398a2')
    _hillside_trees(d)
    _distant_village(d)
    _far_roofs(d)
    _hillside_district(d)
    _distant_landmarks(d)

    # LEFT: indigo-and-cedar pavilion, roofed balcony and warm lanterns.
    d.rectangle((0,127,82,168),fill='#583444',outline='#1b283d')
    d.rectangle((0,132,78,164),fill='#e7a15f')
    d.rectangle((0,136,76,140),fill='#ffdc91')
    d.line((0,141,76,141),fill='#783f44')
    for x in range(3,77,17):
        d.rectangle((x,143,x+12,162),fill='#684250',outline='#332c43')
        d.rectangle((x+2,145,x+10,160),fill='#203b52')
        d.line((x+6,145,x+6,160),fill='#ffd093')
        for y in (149,154,159):
            d.line((x+2,y,x+10,y),fill='#dba477')
        d.point((x+3,146),fill='#ffe8ac')
    for x in (0,19,38,57,77):
        d.rectangle((x,132,x+2,167),fill='#bd3e54')
        d.line((x,132,x,167),fill='#ffca91')
        d.point((x+1,139),fill='#f1c292')
    d.rectangle((0,164,80,168),fill='#402d3d')
    d.line((0,164,80,164),fill='#edbf97')
    _roof(d, -3, 105, 87)
    # Smaller upper tier with a round copper ridge ornament.
    d.rectangle((0,109,45,120),fill='#693b49')
    d.rectangle((3,111,42,116),fill='#f1c791',outline='#382f40')
    for x in range(5,42,6):
        d.line((x,112,x,115),fill='#614448')
    _roof(d, -8, 96, 61, upper=True)
    d.ellipse((27,96,33,102),fill='#dbad74',outline='#432f3c')
    d.point((29,97),fill='#ffdfaa')
    d.line((30,93,30,96),fill='#dfbf8d')

    # RIGHT: a different taller plaster-and-brick tower with a broad blue roof,
    # balcony screen, carved brackets, and a plum tree curling around its edge.
    d.rectangle((252,119,319,168),fill='#244657',outline='#182a3c')
    d.rectangle((258,125,319,163),fill='#65c5ae')
    for y in (130,139,148,157):
        d.line((258,y,319,y),fill='#418080')
        offset = 0 if y%2 else 8
        for x in range(260+offset,319,16):
            d.line((x,y,x,y+5),fill='#4b8988')
    d.rectangle((262,130,314,158),fill='#284858',outline='#e4d6ac')
    for x in (265,280,295):
        d.rectangle((x,133,x+11,155),fill='#1a354d',outline='#9bc5b9')
        d.line((x+5,134,x+5,154),fill='#f8d8a0')
        for y in (139,146,152):d.line((x+1,y,x+10,y),fill='#a6c2b2')
        d.line((x+2,135,x+4,135),fill='#ffe4ac')
    for x in (254,315):
        d.rectangle((x,125,x+3,168),fill='#344658')
        d.line((x+1,126,x+1,166),fill='#d9ddba')
        for y in (131,143,155):d.point((x+2,y),fill='#ffe0af')
    d.rectangle((250,161,319,168),fill='#433442')
    d.line((250,162,319,162),fill='#e5b08f')
    _roof(d, 250, 101, 78, jade=True)
    d.rectangle((275,102,318,112),fill='#385968',outline='#1e2c3e')
    d.rectangle((278,104,317,109),fill='#c8ded0')
    for x in range(280,317,6):
        d.line((x,105,x,108),fill='#487379')
    _roof(d, 270, 91, 61, upper=True, jade=True)
    # Architectural brackets and little carved ornamental swirls.
    for x in (4,14,69,256,267,307,317):
        d.line([(x,126),(x,130),(x+3,130),(x+3,133)],fill='#f3c99d')
        d.point((x+1,131),fill='#513843')
    # A branch with small blossoms; avoid repetitive flat roof silhouettes.
    d.line([(319,143),(309,137),(299,134),(290,128),(282,126)],fill='#493543',width=3)
    d.line([(303,136),(301,129),(296,124)],fill='#4b3445',width=2)
    d.line([(313,139),(311,132),(307,128)],fill='#4b3445')
    for x,y in ((281,125),(286,127),(294,123),(299,128),(305,127),(311,131),(316,137)):
        d.point((x-1,y),fill='#d67d85'); d.point((x+1,y),fill='#f1b3ae')
        d.point((x,y-1),fill='#ffd2bd'); d.point((x,y+1),fill='#bd6275')
        d.point((x,y),fill='#f8c38e')

    # The near pavilion has a brass hanging sign, carved beams and layered
    # paper screens; these details give the two sides different personalities.
    d.rectangle((0,149,10,165),fill='#422f3e',outline='#d3a279')
    d.line((2,150,8,150),fill='#ffdcaa')
    d.line((3,153,7,153),fill='#ce9b76')
    d.rectangle((309,145,319,160),fill='#593b42',outline='#e3b18b')
    d.rectangle((312,147,317,158),fill='#294456')
    d.line((315,148,315,157),fill='#f0c19a')
    d.line((312,151,317,151),fill='#d89f83')
    d.line((312,155,317,155),fill='#d89f83')
    for x,y in ((254,134),(255,140),(316,134),(317,141)):
        d.point((x,y),fill='#ffe0ad')

    # A heavy ceramic ridge ornament and carved blue tiles add the oversized
    # architectural foreground that gives 90s arcade stages their depth.
    d.ellipse((-14,139,24,177),fill='#1e334b',outline='#9fb8b5',width=2)
    d.ellipse((-10,143,20,173),fill='#52717e',outline='#cfcbc0')
    d.ellipse((-6,147,16,169),fill='#263e56',outline='#a7b6ad')
    d.ellipse((-2,151,12,165),fill='#709096',outline='#294255')
    poly(d,[(0,155),(3,152),(7,153),(6,156),(10,157),(8,161),
            (4,162),(3,159),(0,159)],'#d1cfb8','#354f5d')
    for x,y in ((1,144),(10,147),(17,155),(15,165),(7,171)):
        d.ellipse((x-1,y-1,x+1,y+1),fill='#e5d9be',outline='#627f84')
    for y in (146,153,160,167):
        d.line((0,y,1,y+3),fill='#b2c1b6')
    # Hangings, roof joinery and pottery give the two sides their own stories.
    # The little tassels and painted insignia are physical pixels.
    d.line((15,126,15,136),fill='#eed2a9')
    d.rectangle((10,131,19,144),fill='#7f303e',outline='#302a3b')
    d.line((11,132,18,132),fill='#f0c087')
    d.rectangle((13,135,16,139),fill='#d4a963')
    d.line((14,143,14,146),fill='#eac08b')
    d.line((17,143,17,145),fill='#eac08b')
    d.line((301,124,301,134),fill='#eed2a9')
    d.rectangle((296,129,305,142),fill='#2e5969',outline='#1d2e41')
    d.line((297,130,304,130),fill='#d8d3ad')
    d.polygon([(300,133),(302,133),(303,136),(301,139),(299,136)],fill='#f3ca8a')
    d.line((299,141,299,144),fill='#d6b487')
    d.line((303,141,303,143),fill='#d6b487')
    for x,y in ((86,163),(91,165),(229,164),(235,165)):
        d.rectangle((x,y,x+4,y+5),fill='#ae735f',outline='#453c49')
        d.line((x+1,y+1,x+3,y+1),fill='#f0bf92')
        d.point((x+1,y+3),fill='#d99b77')
    _arena_festival(d)
    # Parapet: repeating carved balusters on a dark recessed wall.
    d.rectangle((0,168,319,175),fill='#29384b')
    d.line((0,168,319,168),fill='#f4cca4')
    d.line((0,170,319,170),fill='#957c78')
    for x in range(3,320,10):
        d.rectangle((x,171,x+4,174),fill='#60717a',outline='#293847')
        d.point((x+1,171),fill='#ddbc9e')
        d.point((x+3,173),fill='#96a4a1')
    # Alternating posts and diagonal inlays add carved depth to the railing.
    for x in range(1,320,40):
        d.rectangle((x,169,x+3,175),fill='#344355',outline='#c29d85')
        d.point((x+1,170),fill='#ffe2ad')
    for x in range(12,320,20):
        d.line((x,171,x+4,174),fill='#a58b7e')
        d.line((x+4,171,x,174),fill='#c9a994')
        d.point((x+2,172),fill='#f4d1a7')
    # Wide planks converge towards the stage, rather than resembling brick
    # rows. Each has a different warm tone, knots, scratches and grain.
    d.rectangle((0,176,319,205),fill='#c88e5b')
    # Stronger light/dark and hue differences than closely related browns:
    # the physical panel can collapse subtle shades into the same colour.
    boards=('#f2c879','#b85e52','#e49a52','#85506a','#f5d791','#c87456')
    for i in range(-11,12):
        top=160+i*18
        top_next=160+(i+1)*18
        bottom=160+i*27
        bottom_next=160+(i+1)*27
        d.polygon([(top,177),(top_next,177),(bottom_next,205),(bottom,205)],
                  fill=boards[(i+11)%len(boards)])
        d.line((top,177,bottom,205),fill='#6c4244')
        d.line((top+1,177,bottom+1,205),fill='#f6cf94')
        for j,y in enumerate((181,187,194,200)):
            progress=(y-177)/28
            left=round(top+(bottom-top)*progress)
            width=round(18+9*progress)
            gx=left+4+((i*7+j*5)%max(5,width-8))
            d.line([(gx,y),(gx+1,y+2),(gx,y+4)],
                   fill=('#d39c70','#8e5c43','#e1ae7c','#9f6a4c')[(i+j)%4])
            if (i+j)%3 == 0:
                d.line((gx+2,y+1,gx+4,y+1),fill='#e9bd8c')
    for x,y in ((14,189),(55,199),(105,187),(143,199),(191,188),(241,198),(291,187)):
        d.line((x,y,x+4,y),fill='#7e4b36')
        d.point((x+1,y-1),fill='#edbe8c')
        d.point((x+4,y+1),fill='#d8a073')
    # Paired brass nailheads and a few dark checks add scale and wear without
    # putting a prop or obstacle in the centre of the fighting area.
    for x,y in ((23,183),(78,185),(126,182),(176,185),(224,182),(276,185),
                (38,202),(102,202),(166,202),(230,202),(294,202)):
        d.point((x,y),fill='#6c463a')
        d.point((x+1,y),fill='#f1c69a')
    for x,y in ((38,193),(93,190),(152,195),(210,191),(273,195)):
        d.line((x,y,x+3,y+2),fill='#8f5d43')
        d.point((x+1,y-1),fill='#e7b88a')
    # Worn inlaid corner plates, ropes and small individual scratches add
    # foreground depth. The clear fighting space remains free of obstacles.
    for x, y, side in ((4,190,1),(315,190,-1)):
        d.line([(x,y),(x+side*5,y-1),(x+side*10,y+2),
                (x+side*11,y+7),(x+side*5,y+9),(x,y+8)],fill='#704c45')
        d.line([(x,y+1),(x+side*5,y),(x+side*9,y+3)],fill='#ffe2a6')
        d.point((x+side*5,y+3),fill='#c8d2ba')
        d.point((x+side*6,y+5),fill='#fff1c4')
    for x,y in ((31,191),(62,185),(116,199),(140,188),(184,200),(214,186),(257,192),(301,200)):
        d.line((x,y,x+3,y+1),fill='#edc899')
        d.point((x+4,y+2),fill='#825747')
    d.line((0,176,319,176),fill='#ffe0ac')
    d.line((0,205,319,205),fill='#82563c')
    d.rectangle((0,206,319,211),fill='#283850')
    d.line((0,206,319,206),fill='#f3c998')
    d.line((0,208,319,208),fill='#7294a1')
    d.line((0,211,319,211),fill='#111827')
    paint_lantern(im)


# ---- the lantern, the cloud strip and the fighters ---------------------------------------------------------------
LANTERN = (2, 142)
CLOUD = (128, 112, 60, 12)           # x, y, width, height in screen pixels: the gap above the middle box, below the meteor


def _lantern_frames():
    frames = []
    for colour in ('#f2b26d', '#ffd59a', '#db8b5a'):
        im = Image.new('RGBA', (5, 8), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        d.line((2, 0, 2, 1), fill='#d2b394')
        d.rectangle((1, 2, 3, 6), fill='#912f37', outline='#341d2d')
        d.line((2, 3, 2, 5), fill=colour)
        d.point((2, 7), fill='#e6b479')
        frames.append(im)
    return frames


def paint_lantern(image):
    """The lantern's first light is part of the page (only boards that keep four poses move it)."""
    pose = _lantern_frames()[0]
    pose = pose.resize((pose.width * 2, pose.height * 2), Image.Resampling.NEAREST)
    image.paste(pose, LANTERN, pose)


def _cloud_frames():
    """A repeating strip of cloud that drifts one way: 16 sprite pixels repeat, four frames of 4 pixels close the loop."""
    width, height = CLOUD[2] // 2, CLOUD[3] // 2
    clouds = []
    for phase in range(4):
        im = Image.new('RGBA', (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        for origin in range(-32, width + 32, 16):
            x = origin - phase * 4
            d.line((x + 1, 1, x + 6, 1), fill='#9fb6bd')
            d.line((x + 3, 2, x + 12, 2), fill='#c2c4bd')
            d.line((x + 7, 3, x + 14, 3), fill='#839faa')
        for px in range(width):
            edge = min(px, width - 1 - px)
            for py in range(height):
                if not im.getpixel((px, py))[3]:
                    continue
                if edge == 0:
                    im.putpixel((px, py), (0, 0, 0, 0))
                elif edge < 3:
                    im.putpixel((px, py), ImageColor.getrgb('#5c7b8c') + (255,))
                elif edge < 6:
                    im.putpixel((px, py), ImageColor.getrgb('#6b8996') + (255,))
                elif edge < 9:
                    im.putpixel((px, py), ImageColor.getrgb('#839faa') + (255,))
        clouds.append(im)
    return clouds


def draw_fighters(image, codex_down, claude_down, font):
    """A knocked-out fighter lies on the floor inside its own box, under a KO badge. Standing fighters are resident
    sprites (see animated_details), so nothing of them is drawn into the page."""
    for provider, box, down in (('codex', fighters.CODEX_BOX, codex_down), ('claude', fighters.CLAUDE_BOX, claude_down)):
        if not down:
            continue
        pose = fighters.fallen(provider)
        pose = pose.resize((pose.width * fighters.K, pose.height * fighters.K), Image.Resampling.NEAREST)
        centre = (box[0] + box[2]) * fighters.K // 2
        top = box[3] * fighters.K - pose.height
        image.paste(pose, (centre - pose.width // 2, top), pose)
        d = ImageDraw.Draw(image)
        d.fontmode = '1'
        width = round(font.getlength('KO')) + 8                      # a badge in proportion to the bigger fighters
        badge_x, badge_y = centre - width // 2, top - 19
        d.rectangle((badge_x, badge_y, badge_x + width - 1, badge_y + 13), fill='#121427', outline='#f64b59')
        d.text((badge_x + 4, badge_y + 3), 'KO', font=font, fill='#ffb4ac')


def animated_details(codex_down, claude_down, step_ms=fighters.STEP_MS, max_frames=4):
    """The resident sprites of the stage: both fighters (a duel when eight frames are available and both stand), the
    middle box of that duel, and the drifting cloud. A four-pose board keeps the lantern as a sprite instead."""
    sprites = fighters.actor_sprites(codex_down, claude_down, max_frames)
    if max_frames < 8:
        sprites.append({'x': LANTERN[0], 'y': LANTERN[1], 'frames': _lantern_frames(),
                        'script': [(0, 0, 0), (1, 0, 0), (0, 0, 0), (2, 0, 0)], 'step_ms': 2 * fighters.STEP_MS})
    sprites.append({'x': CLOUD[0], 'y': CLOUD[1], 'frames': _cloud_frames(),
                    'script': [(i, 0, 0) for i in (0, 0, 1, 1, 2, 2, 3, 3)], 'step_ms': 2 * fighters.STEP_MS})
    return sprites


def paint_first_frame(image, sprites):
    """Fallback for boards without animation matches the first native frame."""
    for sprite in sprites:
        frame, dx, dy = sprite['script'][0]
        pose = sprite['frames'][frame].resize((sprite['frames'][frame].width * 2,
                                               sprite['frames'][frame].height * 2),
                                              Image.Resampling.NEAREST)
        image.paste(pose, (sprite['x'] + dx, sprite['y'] + dy), pose)
