"""Offline README GIFs: real firmware simulation, synthetic readings, no hardware.

Requires g++ for ANIM/WAVE. The legacy STAR effect is reproduced below with the
firmware's six-phase cross. Game Boy is a labelled mock quota-update sequence.
"""
import argparse
import copy
from pathlib import Path
import random
import struct
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'firmware/board/tools'))
from PIL import Image
import anim_harness
from token_tv.board_pages import PAGE_NAMES, render_board_pages
from token_tv.sample import snapshot

NOW = 2000000000


def fixture():
    data = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', 32, 4*86400)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', 64, 6*86400), ('5H', 41, 7200)]),
    ])
    for key, count in (('codex', 2), ('claude', 1)):
        data['accounts'][key]['banked_resets'] = {
            'available': count, 'confirmed_at': NOW, 'source': 'manual'}
    return data


def rgb(word):
    return ((word >> 11)*255//31, ((word >> 5)&63)*255//63, (word&31)*255//31)


def picture(raw):
    image = Image.new('RGB', (320, 240))
    image.putdata([rgb(w) for w in struct.unpack('<76800H', raw)])
    return image


def star_frames(page, count=80):
    """Same phase/arms and six random advances per50ms as firmware paintStar."""
    background = list(struct.unpack('<76800H', page[8:153608]))
    words = background.copy()
    n = struct.unpack_from('<H', page, 153612)[0]
    stars = [struct.unpack_from('<HHH', page, 153614+i*6) for i in range(n)]
    phases = [0]*n
    rng = random.Random(7)
    arms = ((-2,0),(-1,0),(1,0),(2,0),(0,-2),(0,-1),(0,1),(0,2))

    def light(c, eighths):
        r,g,b = (c>>11)&31, (c>>5)&63, c&31
        return ((r+(31-r)*eighths//8)<<11) | ((g+(63-g)*eighths//8)<<5) | (b+(31-b)*eighths//8)

    frames = []
    for _ in range(count):
        for _ in range(2):  # GIF sampling100ms, native star tick50ms
            for _ in range(6):
                i = rng.randrange(n)
                phases[i] = phase = (phases[i]+1)%6
                x,y,base = stars[i]
                look = (0,1,2,3,3,0)[phase]
                centre = (0xffff if look==1 else light(base,5) if look==2 else
                          (((base>>11)//3)<<11)|((((base>>5)&63)//3)<<5)|((base&31)//3) if look==3 else base)
                words[y*320+x] = centre
                if 1 <= phase <= 3:
                    for a,(dx,dy) in enumerate(arms):
                        at = (y+dy)*320+x+dx
                        c = background[at]
                        inner = a in (1,2,5,6)
                        words[at] = light(c,6 if inner else 3) if look==1 else light(c,2) if look==2 and inner else c
        frames.append(picture(struct.pack('<76800H',*words)))
    return frames


def save_gif(frames, destination, duration):
    # One shared palette avoids frame-to-frame colour shimmer.
    sheet = Image.new('RGB', (320*4, 240))
    for i in range(4):
        sheet.paste(frames[min(len(frames)-1,i*len(frames)//4)], (i*320,0))
    palette = sheet.quantize(colors=256, method=Image.Quantize.MEDIANCUT)
    indexed = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
    indexed[0].save(destination, save_all=True, append_images=indexed[1:],
                    duration=duration, loop=0, optimize=False, disposal=1)
    with Image.open(destination) as check:
        if check.n_frames < 2:
            raise ValueError(f'{destination.name} did not animate')
    print(f'{destination.name}: {len(frames)} sampled frames, {destination.stat().st_size//1024} KiB')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='preview')
    args = parser.parse_args()
    out = Path(args.out); out.mkdir(parents=True,exist_ok=True)
    with patch('time.time',return_value=NOW):
        pages = render_board_pages(fixture(), stars=True, anim=True, waves=True)
    with tempfile.TemporaryDirectory(prefix='desk-display-gifs-') as tmp:
        root = Path(tmp)
        engine = anim_harness.build(root)
        if engine is None:
            raise SystemExit('Install g++ to capture the real firmware animation engine.')
        for name,page in zip(PAGE_NAMES,pages):
            kind = page[153608:153612]
            duration = 100
            if kind in (b'ANIM',b'WAVE'):
                folder = root/name; folder.mkdir()
                path = folder/'page.bin';path.write_bytes(page)
                total = 6400 if kind==b'WAVE' else 8000
                result = subprocess.run([str(engine),str(path),str(folder),str(total),'100'],capture_output=True,text=True)
                if result.returncode or result.stderr:
                    raise RuntimeError(result.stderr or result.stdout)
                frames = [picture((folder/f'screen_{i}.bin').read_bytes()) for i in range(total//100)]
            elif kind==b'STAR':
                frames = star_frames(page)
            else:
                # Static LCD: show real renderer updates, not made-up movement.
                from token_tv.board_gameboy import render_gameboy_board
                frames = []
                for used in (32,45,62,80,95,80,62,45):
                    data = copy.deepcopy(fixture())
                    data['accounts']['codex']['windows'][0]['used_percent'] = used
                    with patch('time.time',return_value=NOW):
                        frames.append(render_gameboy_board(data,screen=(320,240),grid=('vertical',.22)))
                duration = 1000
            save_gif(frames,out/f'{name}.gif',duration)


if __name__ == '__main__':
    main()
