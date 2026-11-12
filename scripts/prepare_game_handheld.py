"""Prepare the tablet's original handheld demo, without a cartridge or game artwork.

The scene draws its own console and substitute platformer in JavaScript. Its tiny
placeholder image only makes it discoverable by the tablet's scene catalogue.
Existing scene files are never replaced.
"""
import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media as media  # noqa: E402

NAME = 'game-boy'


def prepare_assets(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    if list(directory.glob('scene-game-boy.*')) or list(directory.glob('thumb-game-boy.*')):
        raise FileExistsError('Game Boy scene files already exist; choose another output folder')
    media.save_image(Image.new('RGB', (16, 16), '#bcd05a'), directory / 'scene-game-boy.png')
    thumb = Image.new('RGB', (240, 160), '#1a2733')
    g = ImageDraw.Draw(thumb)
    g.rounded_rectangle((75, 5, 165, 155), 10, fill='#d2d0c6', outline='#81848b', width=2)
    g.rounded_rectangle((83, 13, 157, 79), 4, fill='#46505a')
    g.rectangle((90, 20, 150, 72), fill='#a4bf53')
    g.rectangle((94, 58, 146, 62), fill='#3e7738')
    g.rectangle((99, 49, 106, 57), fill='#244c2c')
    g.rectangle((96, 92, 102, 113), fill='#343a45')
    g.rectangle((89, 99, 109, 106), fill='#343a45')
    g.ellipse((129, 98, 140, 109), fill='#883c5d')
    g.ellipse((143, 91, 154, 102), fill='#883c5d')
    media.save_image(thumb, directory / 'thumb-game-boy.webp')
    return media.scene_entry('game', 'scene-game-boy.png', 'image', 16, 16)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True, help='tablet scene directory')
    args = parser.parse_args()
    try:
        entry = prepare_assets(args.out)
        media.update_manifest(NAME, entry, args.out)
    except (FileExistsError, OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print('Original handheld demo prepared. No cartridge or external artwork is needed.')


if __name__ == '__main__':
    main()
