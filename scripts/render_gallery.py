"""Render the eight board scenes offline with fictional usage; no config/accounts."""
import argparse
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from token_tv.board_pages import PAGE_NAMES, render_board_pages
from token_tv.board_preview import _sequence
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
    # Public demos use the bundled art even if the user has private art installed.
    with (patch('time.time', return_value=now),
          patch('token_tv.board_arcade_local.load', return_value=None),
          patch('token_tv.board_beach.load', return_value=None)):
        frames = render_board_pages(data, anim=True, waves=3, scroll=2)
    gallery = Image.new('RGB', (1280, 480), '#10131e')
    for index, (name, frame) in enumerate(zip(PAGE_NAMES, frames)):
        sequence, _ = _sequence(frame)
        image = next(sequence)
        image.save(out / f'{name}.png')
        gallery.paste(image, ((index % 4)*320, (index // 4)*240))
    gallery.save(out / 'gallery.png')
    gallery.save(out / 'social-preview.png')
    print(f'Eight fictional scenes saved in {out}; no accounts or hardware accessed.')


if __name__ == '__main__':
    main()
