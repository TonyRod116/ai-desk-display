"""Offline optical crystal renderer: convex glass, Snell refraction and Fresnel reflection.

Only Pillow and the standard library. Bake once; the display service only loads
the resulting native artwork and four small reflection masks. No external assets.
"""
import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


SIZE = (144, 128)


def dot(a, b):
    return a[0]*b[0] + a[1]*b[1] + a[2]*b[2]


def add(a, b, scale=1):
    return (a[0]+scale*b[0], a[1]+scale*b[1], a[2]+scale*b[2])


def unit(a):
    length = math.sqrt(dot(a, a))
    return tuple(x / length for x in a)


def cross(a, b):
    return (a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0])


def rotate(v):
    x, y, z = v
    a, b, c = .57, .19, -.22
    x, z = x*math.cos(a)+z*math.sin(a), -x*math.sin(a)+z*math.cos(a)
    y, z = y*math.cos(b)-z*math.sin(b), y*math.sin(b)+z*math.cos(b)
    return (x*math.cos(c)-y*math.sin(c), x*math.sin(c)+y*math.cos(c), z)


def geometry():
    rings = []
    for y, radius in ((-1.08, .035), (.03, .73), (.17, .73), (.67, .46), (.86, .28)):
        rings.append([rotate((radius*math.cos(i*math.tau/8), y,
                              radius*math.sin(i*math.tau/8))) for i in range(8)])
    faces = [rings[0], rings[-1]]
    for lower, upper in zip(rings, rings[1:]):
        for i in range(8):
            faces.append([lower[i], lower[(i+1)%8], upper[(i+1)%8], upper[i]])
    planes = []
    for face in faces:
        n = unit(cross(add(face[1],face[0],-1), add(face[2],face[0],-1)))
        distance = dot(n, face[0])
        if distance < 0:
            n, distance = tuple(-x for x in n), -distance
        planes.append((n, distance))
    return planes


PLANES = geometry()


def intersect(origin, direction):
    entry, leave, entry_n, leave_n = -1e9, 1e9, None, None
    for normal, distance in PLANES:
        denominator = dot(normal, direction)
        gap = distance-dot(normal, origin)
        if abs(denominator) < 1e-9:
            if gap < 0:
                return None
            continue
        t = gap/denominator
        if denominator < 0 and t > entry:
            entry, entry_n = t, normal
        elif denominator > 0 and t < leave:
            leave, leave_n = t, normal
        if entry > leave:
            return None
    return (entry, entry_n, leave, leave_n) if leave > 0 else None


def reflected(direction, normal):
    return add(direction, normal, -2*dot(direction, normal))


def refracted(direction, normal, eta):
    cosine = -dot(normal, direction)
    k = 1-eta*eta*(1-cosine*cosine)
    if k < 0:
        return None
    return add(tuple(eta*x for x in direction), normal, eta*cosine-math.sqrt(k))


def environment(direction, phase, origin=(0,0,0)):
    x,y,z = direction
    # Finite-distance studio lights vary across each face. An environment at
    # infinity would make every planar facet a single flat cartoon colour.
    x += origin[0]*.24
    y += origin[1]*.24
    shift = (0, .04, .08, .12)[phase]
    # Long studio softboxes reflected and refracted by actual geometric faces.
    white = 5*math.exp(-((x+.52-shift)/.10)**2-((y-.32)/.72)**2)
    rim = 2.7*math.exp(-((x-.68)/.065)**2-((y+.06)/.95)**2)
    strip = 2.4*math.exp(-((y-.57+shift*.35)/.035)**2-((x-.08)/.8)**2)
    blue = .65*math.exp(-((x-.24)/.53)**2-((y+.38)/.38)**2)
    warm = 1.4*math.exp(-((x+.27)/.13)**2-((y+.62)/.14)**2)
    fine = 1.6*math.exp(-((x+y*.31+.18-shift*.6)/.025)**2-((y-.15)/.8)**2)
    return (.018+white+rim*.35+strip+blue*.16+warm+fine,
            .037+white+rim*.82+strip*.94+blue*.68+warm*.46+fine,
            .065+white+rim+strip*.88+blue+warm*.18+fine)


def channel(origin, direction, hit, phase, component):
    entry, normal, _, _ = hit
    point = add(origin,direction,entry)
    fresnel = .04+.96*(1-abs(dot(direction,normal)))**5
    value = environment(reflected(direction,normal),phase,point)[component]*fresnel
    ior = (1.505,1.52,1.54)[component]
    direction = refracted(direction,normal,1/ior)
    origin = add(point,direction,1e-5)
    weight = 1-fresnel
    for _ in range(5):
        inside = intersect(origin,direction)
        if inside is None:
            break
        _,_,distance,normal = inside
        point = add(origin,direction,distance)
        weight *= math.exp(-distance*(.15,.055,.025)[component])
        out = refracted(direction,tuple(-x for x in normal),ior)
        if out is not None:
            f = .04+.96*(1-abs(dot(direction,normal)))**5
            value += weight*(1-f)*environment(out,phase,point)[component]
            weight *= f
        direction = reflected(direction,normal)
        origin = add(point,direction,1e-5)
        if weight < .005:
            break
    return round(255*(max(0,value)/(max(0,value)+.55))**(1/2.2))


def crystal(phase, scale=2):
    image = Image.new('RGBA',(SIZE[0]*scale,SIZE[1]*scale))
    pixels = image.load()
    direction = (0.,0.,-1.)
    for y in range(image.height):
        for x in range(image.width):
            origin = ((x+.5-image.width/2)/(60*scale),
                      (image.height/2-y-.5)/(60*scale),4.)
            direction = unit((origin[0], origin[1], -4.))
            origin = (0.,0.,4.)
            hit = intersect(origin,direction)
            if hit is not None:
                pixels[x,y] = tuple(channel(origin,direction,hit,phase,k) for k in range(3))+(255,)
    return image.resize(SIZE,Image.Resampling.LANCZOS)


def studio():
    image = Image.new('RGBA',(160,240))
    values = []
    for y in range(240):
        for x in range(160):
            light = math.exp(-((x-81)/60)**2-((y-106)/81)**2)
            values.append((round(3+6*light),round(8+16*light),round(17+24*light),255))
    image.putdata(values)
    glow = Image.new('RGBA',image.size)
    d = ImageDraw.Draw(glow)
    # A restrained spectral caustic lands on a dark polished pedestal.
    spectrum = ((248,104,85),(255,180,100),(225,237,156),(95,240,208),(94,163,251),(172,132,239))
    for i,colour in enumerate(spectrum):
        d.polygon(((92,139),(95,139),(146-i*9,202),(128-i*9,202)),fill=colour+(55,))
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(2)))
    d = ImageDraw.Draw(image)
    d.ellipse((17,197,148,220),fill='#03060b')
    d.rectangle((17,201,148,208),fill='#070c14')
    surface = Image.new('RGBA',(160*3,240*3))
    sd = ImageDraw.Draw(surface)
    sd.ellipse((17*3,188*3,148*3,213*3),fill='#132330')
    sd.ellipse((19*3,189*3,146*3,212*3),fill='#09131f')
    sd.arc((17*3,188*3,148*3,213*3),5,172,fill='#63838e',width=2)
    sd.arc((19*3,189*3,146*3,212*3),205,315,fill='#2d5262',width=2)
    image.alpha_composite(surface.resize(image.size,Image.Resampling.LANCZOS))
    return image


def highlights(pose, base):
    """Keep fine internal facets native, too; animate only soft light on glass.

    Replacing the whole interior with a half-resolution pose blurs the cut.
    Protect high-contrast refraction edges and add restrained highlights only.
    """
    result = pose.copy()
    for y in range(pose.height):
        for x in range(pose.width):
            target = pose.getpixel((x,y))
            if target[3] < 128:
                continue
            nearby = [base.getpixel((min(143,max(0,x*2+dx)), min(127,max(0,y*2+dy))))
                      for dy in (-1,0,1,2) for dx in (-1,0,1,2)]
            if any(max(p[k] for p in nearby)-min(p[k] for p in nearby)>52 for k in range(3)):
                result.putpixel((x,y),(0,0,0,0))
                continue
            samples = [base.getpixel((x*2+dx,y*2+dy)) for dy in (0,1) for dx in (0,1)]
            average = tuple(sum(p[k] for p in samples)/4 for k in range(3))
            gain = tuple(max(0,target[k]-average[k]) for k in range(3))
            if max(gain)<18 or sum(gain)<30:
                result.putpixel((x,y),(0,0,0,0))
            else:
                result.putpixel((x,y),tuple(round(average[k]+gain[k]*.55) for k in range(3))+(255,))
    return result


def prepare(output):
    output.mkdir(parents=True,exist_ok=True)
    phases = []
    glass = []
    for phase in range(4):
        shard = crystal(phase)
        glass.append(shard)
        image = studio()
        # A subtle floor reflection carries the crystal's actual silhouette.
        reflection = shard.transpose(Image.Transpose.FLIP_TOP_BOTTOM).resize((100,34),Image.Resampling.LANCZOS)
        alpha = reflection.getchannel('A')
        alpha.putdata([round(v*.19*(1-(i//100)/34)) for i,v in enumerate(alpha.tobytes())])
        reflection.putalpha(alpha)
        image.alpha_composite(reflection,(31,196))
        image.alpha_composite(shard,(8,42))
        phases.append(image)
        print(f'Optical pose {phase+1}/4 rendered locally',flush=True)
    phases[0].convert('RGB').save(output/'prism-optics.png',optimize=True)
    # Native edges stay untouched in every pose. Animate only the interior
    # reflections, with eroded masks so 2x sprites cannot roughen the silhouette.
    mask = glass[0].getchannel('A').filter(ImageFilter.MinFilter(7))
    atlas = Image.new('RGBA',(72,256))
    for phase in range(1,4):
        pose = phases[phase].crop((8,42,152,170)).resize((72,64),Image.Resampling.LANCZOS)
        for y in range(64):
            for x in range(72):
                if min(mask.getpixel((x*2+dx,y*2+dy)) for dy in (0,1) for dx in (0,1))<250:
                    pose.putpixel((x,y),(0,0,0,0))
        atlas.paste(highlights(pose, phases[0].crop((8,42,152,170))),(0,phase*64))
    atlas.save(output/'prism-reflections.png',optimize=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,default=Path(__file__).resolve().parents[1]/'token_tv/assets')
    prepare(parser.parse_args().out)
