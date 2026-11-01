"""Compact, resident side-scrolling world for supported touch-board firmware.

The board receives one indexed, seamless landscape and four rider poses once.
It scrolls and composites them locally; the HUD and account readers are separate.
"""
import functools
import struct
from pathlib import Path

from PIL import Image

from token_tv import board_anim, board_platform_world

W, H, TOP = 512, 96, 48
STEP_MS, SPEED = 120, 2                 # logical pixels per frame, shown at 2x
FRAME_MS = STEP_MS // 2                 # firmware 18 interpolates each stored step
ACTOR_W, ACTOR_H, ACTOR_X, FRAMES = 32, 36, 40, 4
ZOOM_ACTOR_W, ZOOM_ACTOR_H = 48, 54
ZOOM_SCALE, ZOOM_ORIGIN, ZOOM_CAMERA_SPEED = 3, 20, 4
ZOOM_FRAMES = 5  # four riding poses plus a dedicated raised-glove jump pose
ZOOM_HOP = (0, 6, 12, 18, 24, 33, 24, 18, 12, 6, 0)
ORIGINAL_ACTOR_W, ORIGINAL_ACTOR_H, ORIGINAL_FRAMES = 56, 64, 8
ORIGINAL_HOP = (0, 3, 6, 9, 11, 14, 11, 9, 6, 3, 0)
# Sampled from the supplied game's mounted jump and scaled to fit below the HUD.
ORIGINAL_JUMP = (0, 16, 40, 63, 83, 96, 99, 96, 82, 61, 36, 10, 0)
ORIGINAL_ASSETS = Path.home() / '.local/share/ai-desk-display/smw-original'
HUD_WIDTH, HUD_HEIGHT, HUD_COLOURS = 320, 48, 64
HUD_INDEX_BYTES = HUD_WIDTH * HUD_HEIGHT * 6 // 8
FULLSCREEN_HUD_BYTES = HUD_COLOURS * 2 + HUD_INDEX_BYTES
ZOOM_COIN_MASK = (0b001100, 0b011110, 0b111111, 0b111111, 0b111111,
                  0b111111, 0b111111, 0b011110, 0b001100)
HEADER = struct.Struct('<BB9H')
JUMP_START = 26
JUMP = (0, 4, 8, 14, 20, 26, 32, 38, 42, 44,
        44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44, 44,
        42, 38, 32, 26, 20, 14, 8, 4, 2, 0)


def _original_images():
    """Read optional locally supplied assets; never fetch or bundle artwork."""
    def image(name, size, mode):
        with Image.open(ORIGINAL_ASSETS / name) as source:
            if source.size != size:
                raise ValueError('Invalid local artwork dimensions')
            return source.convert(mode)

    scenery = image('world.png', (W, H), 'RGB')
    poses = [image(f'rider-{i}.png', (28, 32), 'RGBA')
        for i in range(ORIGINAL_FRAMES)]
    coin = image('coin.png', (8, 16), 'RGBA')
    shell = image('shell.png', (16, 16), 'RGBA')
    used = image('used-block.png', (16, 16), 'RGBA')
    backdrops = [image(f'block-bg-{i}.png', (16, 18), 'RGB') for i in range(2)]
    ground = (ORIGINAL_ASSETS / 'heights.bin').read_bytes()
    if len(ground) != W or any(h < 48 or h >= H for h in ground):
        raise ValueError('Invalid local artwork ground')
    return scenery, poses, coin, shell, used, backdrops, ground


@functools.lru_cache(maxsize=3)
def encode(version=1):
    from token_tv.board_platform import _rider_pose
    if version not in (1, 2, 3):
        raise ValueError('Unsupported scrolling world')
    dimensions = {1: (ACTOR_W, ACTOR_H, FRAMES),
                  2: (ZOOM_ACTOR_W, ZOOM_ACTOR_H, ZOOM_FRAMES),
                  3: (ORIGINAL_ACTOR_W, ORIGINAL_ACTOR_H, ORIGINAL_FRAMES)}
    actor_w, actor_h, frames = dimensions[version]
    if version == 3:
        scenery, poses, coin, shell, used, backdrops, ground = _original_images()
    else:
        scenery = board_platform_world.scenery(version == 2)
        ground = board_platform_world.heights()
        poses = [_rider_pose(frame) for frame in range(FRAMES)]
        if version == 2:
            poses.append(_rider_pose(3, jumping=True))
            poses = [im.resize((actor_w, actor_h), Image.Resampling.NEAREST) for im in poses]
    indexed = scenery.quantize(
        colors=128, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    palette = indexed.getpalette()
    palette += [0] * (768-len(palette))
    colours = [board_anim.rgb565(palette[i:i+3]) for i in range(0, 768, 3)]
    actor = [word for pose in poses for word in board_anim.sprite_words(pose)]
    body = (HEADER.pack(version, 0, W, H, TOP, STEP_MS, SPEED, actor_w, actor_h, ACTOR_X, frames)
            + struct.pack('<256H', *colours) + ground + indexed.tobytes()
            + struct.pack(f'<{len(actor)}H', *actor))
    if version == 3:
        body += struct.pack('<128H', *board_anim.sprite_words(coin))
        body += struct.pack('<256H', *board_anim.sprite_words(shell))
        body += struct.pack('<256H', *board_anim.sprite_words(used))
        for backdrop in backdrops:
            rgb=backdrop.tobytes()
            body += struct.pack('<288H', *(board_anim.rgb565(rgb[i:i+3]) for i in range(0,len(rgb),3)))
    if len(body) > board_anim.MAX_PAYLOAD:
        raise ValueError('Platform animation exceeds board memory limit')
    return body


def encode_fullscreen(hud):
    """Add a compact transparent six-bit HUD to the original-art scene."""
    if hud.size != (HUD_WIDTH, HUD_HEIGHT) or hud.mode != 'RGBA':
        raise ValueError('Invalid scrolling HUD')
    raw = hud.tobytes()
    rgba = [raw[i:i + 4] for i in range(0, len(raw), 4)]
    visible = [board_anim.rgb565(pixel[:3]) for pixel in rgba if pixel[3]]
    colours = sorted(set(visible))
    if len(colours) <= HUD_COLOURS - 1:
        lookup = {colour: i + 1 for i, colour in enumerate(colours)}
        indices = (lookup[board_anim.rgb565(pixel[:3])] if pixel[3] else 0 for pixel in rgba)
    else:
        # Only foreground pixels participate; transparent pixels must not
        # distort the palette, and index zero remains fully transparent.
        foreground = Image.new('RGB', (len(visible), 1))
        foreground.putdata([tuple(pixel[:3]) for pixel in rgba if pixel[3]])
        indexed = foreground.quantize(colors=HUD_COLOURS - 1,
                                      method=Image.Quantize.MEDIANCUT,
                                      dither=Image.Dither.NONE)
        palette = indexed.getpalette()
        colours = [board_anim.rgb565(palette[i:i + 3]) for i in range(0, (HUD_COLOURS - 1) * 3, 3)]
        chosen = iter(indexed.tobytes())
        indices = (next(chosen) + 1 if pixel[3] else 0 for pixel in rgba)
    palette = [0] + colours
    palette.extend([0] * (HUD_COLOURS - len(palette)))
    packed = bytearray()
    accumulator = bits = 0
    for index in indices:
        accumulator |= index << bits
        bits += 6
        while bits >= 8:
            packed.append(accumulator & 0xff)
            accumulator >>= 8
            bits -= 8
    if bits:
        packed.append(accumulator)
    body = bytearray(encode(3))
    body[0] = 4
    body.extend(struct.pack('<64H', *palette))
    body.extend(packed)
    if len(packed) != HUD_INDEX_BYTES or len(body) > board_anim.MAX_PAYLOAD:
        raise ValueError('Fullscreen animation exceeds board memory limit')
    return bytes(body)


def decode(payload):
    if len(payload) < HEADER.size:
        raise ValueError('Truncated scrolling header')
    vals = HEADER.unpack_from(payload)
    version = vals[0]
    dimensions = {1: (ACTOR_W, ACTOR_H, FRAMES),
                  2: (ZOOM_ACTOR_W, ZOOM_ACTOR_H, ZOOM_FRAMES),
                  3: (ORIGINAL_ACTOR_W, ORIGINAL_ACTOR_H, ORIGINAL_FRAMES),
                  4: (ORIGINAL_ACTOR_W, ORIGINAL_ACTOR_H, ORIGINAL_FRAMES)}
    if version not in dimensions:
        raise ValueError('Unsupported scrolling world')
    actor_w, actor_h, frames = dimensions[version]
    if vals != (version, 0, W, H, TOP, STEP_MS, SPEED,
                                          actor_w, actor_h, ACTOR_X, frames):
        raise ValueError('Unsupported scrolling world')
    original = version in (3, 4)
    pixels_per_frame = (actor_w//2)*(actor_h//2) if original else actor_w*actor_h
    expected = (HEADER.size + 512 + W + W*H + frames*pixels_per_frame*2
                + (2432 if original else 0) + (FULLSCREEN_HUD_BYTES if version == 4 else 0))
    if len(payload) != expected or len(payload) > board_anim.MAX_PAYLOAD:
        raise ValueError('Invalid scrolling payload length')
    pos=HEADER.size
    palette=struct.unpack_from('<256H',payload,pos);pos+=512
    heights=payload[pos:pos+W];pos+=W
    if any(h < 48 or h >= H for h in heights):
        raise ValueError('Invalid ground height')
    pixels=payload[pos:pos+W*H];pos+=W*H
    count=frames*pixels_per_frame
    actor=struct.unpack_from(f'<{count}H',payload,pos);pos+=count*2
    coin=struct.unpack_from('<128H',payload,pos) if original else ();pos+=256 if original else 0
    shell=struct.unpack_from('<256H',payload,pos) if original else ();pos+=512 if original else 0
    used=struct.unpack_from('<256H',payload,pos) if original else ();pos+=512 if original else 0
    backdrops=struct.unpack_from('<576H',payload,pos) if original else ();pos+=1152 if original else 0
    hud_palette=struct.unpack_from('<64H',payload,pos) if version == 4 else ();pos+=128 if version == 4 else 0
    hud=payload[pos:pos+HUD_INDEX_BYTES] if version == 4 else b''
    return dict(version=version, actor_w=actor_w, actor_h=actor_h, frames=frames,
                palette=palette, heights=heights, pixels=pixels, actor=actor, coin=coin,
                shell=shell, used=used, backdrops=backdrops, hud_palette=hud_palette, hud=hud)


def jump_height(spec, tick):
    if spec['version'] in (2, 3, 4):
        # A single 1.62 s ballistic arc, timed for both periodic obstacles.
        # Integer arithmetic is shared with the ESP32 compositor.
        phase=tick%192-54
        if spec['version'] in (3, 4) and 0 <= phase < len(ORIGINAL_JUMP):
            return ORIGINAL_JUMP[phase]
        if spec['version'] == 2 and 0 <= phase <= 27:
            return (312*phase*(27-phase)+364)//(27*27)
        hop=tick%192-99
        steps=ORIGINAL_HOP if spec['version'] in (3, 4) else ZOOM_HOP
        return steps[hop] if 0 <= hop < len(steps) else 0
    phase=tick%256-JUMP_START*2
    jump=0
    if 0 <= phase < len(JUMP)*2:
        index=phase//2
        jump=JUMP[index]
        if phase%2:
            jump=(jump+(JUMP[index+1] if index+1<len(JUMP) else 0))//2
    return jump


def actor_y(spec, tick):
    if spec['version'] in (2, 3, 4):
        camera=(tick*ZOOM_CAMERA_SPEED)%(W*ZOOM_SCALE)
        foot=((camera+ACTOR_X+spec['actor_w']//2)//ZOOM_SCALE)%W
        ground=TOP+ZOOM_SCALE*(spec['heights'][foot]-ZOOM_ORIGIN)
        phase=tick%192-54
        duration=12 if spec['version'] in (3, 4) else 27
        if 0 <= phase <= duration:
            # In flight, interpolate between takeoff and landing heights.
            # The arc must not follow every contour of the ground below it.
            start=tick-phase
            start_camera=(start*ZOOM_CAMERA_SPEED)%(W*ZOOM_SCALE)
            end_camera=((start+duration)*ZOOM_CAMERA_SPEED)%(W*ZOOM_SCALE)
            first=((start_camera+ACTOR_X+spec['actor_w']//2)//ZOOM_SCALE)%W
            last=((end_camera+ACTOR_X+spec['actor_w']//2)//ZOOM_SCALE)%W
            change=ZOOM_SCALE*(spec['heights'][last]-spec['heights'][first])*phase
            ground=TOP+ZOOM_SCALE*(spec['heights'][first]-ZOOM_ORIGIN)
            ground += change//duration if change >= 0 else -((-change)//duration)
        return ground-spec['actor_h']-jump_height(spec,tick)
    offset=(tick*SPEED//2)%W
    foot=(offset+(ACTOR_X+ACTOR_W//2)//2)%W
    return TOP+2*spec['heights'][foot]-ACTOR_H-jump_height(spec,tick)


def coin_age(spec, tick):
    if spec['version'] not in (2, 3, 4):
        return None
    age=tick%192-104
    return age if 0 <= age < 16 else None


def _zoom_block_effect(out, spec, tick, camera):
    """Move the struck block up three pixels and pop a coin from its top."""
    phase=tick%192
    block=157 if tick%384 < 192 else 413
    left=block*ZOOM_SCALE-camera
    block_top=TOP+ZOOM_SCALE*(36-ZOOM_ORIGIN)
    bump=phase in (104,105)
    original=spec['version'] in (3, 4)
    if original and phase >= 104:
        backdrop_offset=0 if tick%384 < 192 else 288
        for row in range(54):
            y=block_top-3+row
            for column in range(48):
                x=left+column
                if 0 <= x < 320:
                    out[y*320+x]=spec['backdrops'][backdrop_offset+(row//3)*16+column//3]
        used_top=block_top-(3 if bump else 0)
        for row in range(48):
            y=used_top+row
            for column in range(48):
                x=left+column
                color=spec['used'][(row//3)*16+column//3]
                if 0 <= x < 320 and color != board_anim.KEY:
                    out[y*320+x]=color
    age=coin_age(spec,tick)
    if age is None:
        return
    size=48 if original else 42
    if bump and not original:
        for y in range(block_top-3,block_top+size):
            sy=min(ZOOM_ORIGIN+(y-TOP)//ZOOM_SCALE+1,52 if original else 50)
            for x in range(max(0,left),min(320,left+size)):
                sx=((camera+x)//ZOOM_SCALE)%W
                out[y*320+x]=spec['palette'][spec['pixels'][sy*W+sx]]
    coin_top=block_top-5-min(age*4,48 if original else 36)
    if original:
        for row in range(48):
            y=coin_top+row
            if y < (0 if spec['version'] == 4 else TOP) or y >= block_top-(3 if bump else 0):
                continue
            for column in range(24):
                x=left+12+column
                color=spec['coin'][(row//3)*8+column//3]
                if 0 <= x < 320 and color != board_anim.KEY:
                    out[y*320+x]=color
        return
    for row in range(18):
        y=coin_top+row
        if y < TOP or y >= block_top-(3 if bump else 0):
            continue
        mask=ZOOM_COIN_MASK[row//2]
        for column in range(12):
            x=left+15+column
            bit=column//2
            if 0 <= x < 320 and mask & (1 << (5-bit)):
                colour=0xffd6 if bit == 1 else 0x9ac4 if bit in (0,5) else 0xff0b
                out[y*320+x]=colour


def _original_shell(out, spec, tick):
    """A shell enters and leaves the view; it resets only when offscreen."""
    phase=tick%192
    left=651-10*phase
    position=217 if tick%384 < 192 else 473
    top=TOP+ZOOM_SCALE*(spec['heights'][position]-ZOOM_ORIGIN)-32
    for row in range(32):
        y=top+row
        if not TOP <= y < 240:
            continue
        for column in range(32):
            x=left+column
            color=spec['shell'][(row//2)*16+column//2]
            if 0 <= x < 320 and color != board_anim.KEY:
                out[y*320+x]=color


def actor_frame(spec, tick):
    if spec['version'] in (3, 4):
        phase=tick%192
        if jump_height(spec,tick):
            flight=phase-54 if 54 < phase < 67 else phase-99
            return 4 if flight <= 2 else 5 if flight <= 4 else 6 if flight <= 8 else 7
        return (tick//2)%4
    if spec['version'] == 2 and jump_height(spec,tick):
        return 4
    return (tick//2)%FRAMES


def render_words(background, spec, tick):
    """Independent RGB565 reference for the firmware compositor."""
    out=list(background)
    zoom=spec['version'] in (2, 3, 4)
    fullscreen=spec['version'] == 4
    camera=(tick*ZOOM_CAMERA_SPEED)%(W*ZOOM_SCALE) if zoom else 0
    offset=(camera//ZOOM_SCALE if zoom else tick*SPEED//2)%W
    pal=spec['palette']; pixels=spec['pixels']
    if zoom:
        for screen_y in range(0 if fullscreen else TOP, 240):
            sy=(ZOOM_ORIGIN-TOP//ZOOM_SCALE+screen_y//ZOOM_SCALE if fullscreen
                else ZOOM_ORIGIN+(screen_y-TOP)//ZOOM_SCALE)
            row=pixels[sy*W:(sy+1)*W]
            source=row[offset:]+row[:offset]
            shift=camera%ZOOM_SCALE
            line=[pal[v] for v in source[:108] for _ in range(ZOOM_SCALE)][shift:shift+320]
            at=screen_y*320
            out[at:at+320]=line
    else:
        for sy in range(H):
            row=pixels[sy*W:(sy+1)*W]
            source=row[offset:]+row[:offset]
            line=[pal[v] for v in source[:160] for _ in range(2)]
            at=(TOP+sy*2)*320
            out[at:at+320]=line
            out[at+320:at+640]=line
    if spec['version'] in (3, 4):
        _original_shell(out,spec,tick)
    if zoom:
        _zoom_block_effect(out,spec,tick,camera)
    ay=actor_y(spec,tick)
    frame=actor_frame(spec,tick)
    actor_w,actor_h=spec['actor_w'],spec['actor_h']
    scale=2 if spec['version'] in (3, 4) else 1
    source_w,source_h=actor_w//scale,actor_h//scale
    actor=spec['actor'][frame*source_w*source_h:(frame+1)*source_w*source_h]
    for sy in range(actor_h):
        for sx in range(actor_w):
            colour=actor[(sy//scale)*source_w+sx//scale]
            if colour==board_anim.KEY:
                continue
            y=ay+sy
            if TOP <= y < 240:
                out[y*320+ACTOR_X+sx]=colour
    if fullscreen:
        for i in range(HUD_WIDTH * HUD_HEIGHT):
            bit=i*6
            byte=bit//8
            word=spec['hud'][byte]
            if byte+1 < len(spec['hud']):
                word |= spec['hud'][byte+1] << 8
            index=(word >> (bit%8)) & 63
            if index:
                out[i]=spec['hud_palette'][index]
    return out


def first_image(version=1, payload=None):
    """Exact first view, including the rider, for static/instant display."""
    spec=decode(payload if payload is not None else encode(version))
    words=render_words([board_anim.rgb565((7,84,170))]*(320*240),spec,0)
    rgb=bytes(c for p in words for c in (((p>>11)&31)<<3,((p>>5)&63)<<2,(p&31)<<3))
    return Image.frombytes('RGB',(320,240),rgb)
