"""Render the bundled quest scene offline with fictional usage and artwork."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'firmware/board/tools'))
import anim_harness
from scripts.render_animations import NOW, fixture, picture, save_gif
from token_tv.board_pages import rgb565_frame
from token_tv.board_scenes import render_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='preview')
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    # An impossible local path guarantees the public preview uses only bundled art.
    with patch('time.time', return_value=NOW), \
            patch('token_tv.board_zelda.ART', Path('/nonexistent/quest-art.png')), \
            patch('token_tv.board_zelda._local_art', return_value=None):
        image, animation = render_archive('zelda', fixture(), animated=True, anim_frames=8)
    page = rgb565_frame(image, anim=animation)
    with tempfile.TemporaryDirectory(prefix='quest-preview-') as tmp:
        folder = Path(tmp)
        engine = anim_harness.build(folder)
        if engine is None:
            raise SystemExit('Install g++ to capture the firmware animation engine.')
        source = folder / 'page.bin'
        source.write_bytes(page)
        result = subprocess.run([str(engine), str(source), str(folder), '6400', '200'],
                                capture_output=True, text=True)
        if result.returncode or result.stderr:
            raise RuntimeError(result.stderr or result.stdout)
        frames = [picture((folder / f'screen_{i}.bin').read_bytes()) for i in range(32)]
    frames[0].save(out / 'quest.png')
    save_gif(frames, out / 'quest.gif', 200)
    print('Quest preview: fictional readings and bundled original artwork only.')


if __name__ == '__main__':
    main()
