"""Render the eight board scenes offline with fictional usage; no config/accounts."""
import argparse
from pathlib import Path
import struct
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from token_tv.board_pages import PAGE_NAMES, render_board_pages
from token_tv.sample import snapshot


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='preview')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    now = 2000000000
    data = snapshot(now=now, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', 32, 4*86400)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', 64, 6*86400), ('5H', 41, 7200)]),
    ])
    for key, count in (('codex', 2), ('claude', 1)):
        data['accounts'][key]['banked_resets'] = {
            'available': count, 'confirmed_at': now, 'source': 'manual'}
    with patch('time.time', return_value=now):
        frames = render_board_pages(data)
    gallery = Image.new('RGB', (1280, 480), '#10131e')
    for index, (name, frame) in enumerate(zip(PAGE_NAMES, frames)):
        words = struct.unpack('<76800H', frame[8:153608])
        image = Image.new('RGB', (320, 240))
        image.putdata([(((v >> 11) & 31)*255//31, ((v >> 5) & 63)*255//63,
                        (v & 31)*255//31) for v in words])
        image.save(out / f'{name}.png')
        gallery.paste(image, ((index % 4)*320, (index // 4)*240))
    gallery.save(out / 'gallery.png')
    gallery.save(out / 'social-preview.png')
    print(f'Eight fictional scenes saved in {out}; no accounts or hardware accessed.')


if __name__ == '__main__':
    main()
