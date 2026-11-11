"""Offline preparation of the tablet's live scenes: look at each real picture (read only), propose a `live` block, check and apply the presets.

    .venv/bin/python -B scripts/prepare_tablet_live.py                       # propose: print what the pictures suggest (nothing is written)
    .venv/bin/python -B scripts/prepare_tablet_live.py --check               # validate scripts/tablet_live_presets.json against token_tv/tablet_live.py
    .venv/bin/python -B scripts/prepare_tablet_live.py --overlay DIR         # pictures with the preset regions drawn on them, into DIR (private art: keep DIR out of Git)
    .venv/bin/python -B scripts/prepare_tablet_live.py --apply --directory D # write the presets into D/scenes.json through tablet_media.update_manifest
    .venv/bin/python -B scripts/prepare_tablet_live.py --clear --directory D # take every `live` block out again

The presets live in `scripts/tablet_live_presets.json`: numbers only (positions as fractions of the picture, strengths, paths), never a pixel
of art. `--apply` refuses to touch the real private folder unless `--yes` is given, refuses a preset the validator would change or drop,
keeps everything else of a scene's manifest entry as it is and writes atomically (the same locked writer the scene builders use).
The pictures are opened read only; nothing is ever written next to them. Run at low priority: `nice -n 15 ionice -c 3 ...`.

The proposal is a starting point, found from the picture alone: the sea line (the row where horizontal structure is strongest in the lower
two thirds), the open sky above the skyline (per column, down to the first strong edge), the small bright lights (windows, lamps, stars:
how many and how big, which sets the lights' cell size) and a mist band at the horizon. The final presets are looked at by eye with
`--overlay` and in the page, then edited by hand.
"""
import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media  # noqa: E402
from token_tv import tablet_live  # noqa: E402

PRESETS = Path(__file__).with_name('tablet_live_presets.json')
MAX_MANIFEST_BYTES = 60 * 1024         # the server reads at most 64 KiB; leave room


def load_presets(path=PRESETS):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    scenes = data.get('scenes') if isinstance(data, dict) else None
    if not isinstance(scenes, dict):
        raise ValueError(f'{path.name}: a "scenes" object is needed')
    return scenes


def check_presets(scenes):
    """(clean blocks by scene, list of problems). A block the validator would change or drop is a problem: the file holds exactly what will be served."""
    clean, problems = {}, []
    for name, raw in sorted(scenes.items()):
        block, found = tablet_live.check_live(raw, name)
        problems.extend(f'{name}: {p}' for p in found)
        if block is None:
            problems.append(f'{name}: nothing usable is left')
            continue
        clean[name] = block
    return clean, problems


def manifest_scenes(directory):
    path = Path(directory) / tablet_media.MANIFEST
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
        return data['scenes'] if data.get('version') == 2 else {}
    except (OSError, ValueError, KeyError, AttributeError):
        return {}


def picture_path(directory, name, entry):
    """The picture of a scene to look at: its image, or the still of a film. Read only."""
    media = entry.get('media') or {}
    file = media.get('file') if media.get('kind') == 'image' else entry.get('still')
    path = Path(directory) / str(file or '')
    return path if file and path.is_file() else None


# ---- the proposal -----------------------------------------------------------------------------------------------------------

def small_luma(image, width=192):
    """(width, height, rows of luma 0..1) of the picture shrunk with a box filter."""
    height = max(8, round(image.height * width / image.width))
    small = image.convert('L').resize((width, height), Image.Resampling.BOX)
    pixels = small.load()
    return width, height, [[pixels[x, y] / 255 for x in range(width)] for y in range(height)]


def find_horizon(width, height, luma):
    """The row of the lower two thirds where horizontal structure beats vertical structure by most: a sea line, a reflection's edge."""
    scores = []
    for y in range(int(height * 0.30), int(height * 0.95)):
        vertical = sum(abs(luma[y + 1][x] - luma[y - 1][x]) for x in range(width))
        horizontal = sum(abs(luma[y][min(x + 1, width - 1)] - luma[y][max(x - 1, 0)]) for x in range(width))
        scores.append((vertical / (horizontal + 0.5 * width * 0.01), y))
    smooth = [(sum(s for s, _ in scores[max(0, i - 1):i + 2]) / len(scores[max(0, i - 1):i + 2]), scores[i][1]) for i in range(len(scores))]
    best = sorted(smooth, reverse=True)[:3]
    return [(round(y / height, 3), round(score, 2)) for score, y in best]


def find_skyline(width, height, luma, columns=18):
    """Per column, where the open sky ends: the first row below the top tenth whose brightness drops clearly under the sky just above it."""
    line = []
    for i in range(columns + 1):
        x = min(width - 1, round(i / columns * (width - 1)))
        stop = None
        for y in range(max(9, int(height * 0.10)), int(height * 0.9)):
            above = sum(luma[k][x] for k in range(y - 8, y - 2)) / 6
            rows = range(y, min(height, y + 4))
            here = sum(luma[k][x] for k in rows) / len(rows)
            if above > 0.12 and here < above * 0.6:
                stop = y
                break
        line.append((round(i / columns, 3), round((stop if stop is not None else height * 0.9) / height, 3)))
    return line


def find_lights(width, height, luma):
    """How many small bright spots there are (a pixel far brighter than the pixels two steps away: windows, lamps, stars)."""
    spots = 0
    for y in range(2, height - 2):
        for x in range(2, width - 2):
            v = luma[y][x]
            if v < 0.45:
                continue
            ring = (luma[y - 2][x] + luma[y + 2][x] + luma[y][x - 2] + luma[y][x + 2]) / 4
            if v - ring > 0.18:
                spots += 1
    return spots


def propose(image, name):
    width, height, luma = small_luma(image)
    horizon = find_horizon(width, height, luma)
    skyline = find_skyline(width, height, luma)
    spots = find_lights(width, height, luma)
    top = min(0.9, max(0.2, horizon[0][0]))
    sky = [[0, 0], [1, 0]] + [[x, round(max(0.05, min(y, top - 0.02)), 3)] for x, y in reversed(skyline)]
    live = {
        'water': {'regions': [[0, round(top + 0.02, 3), 1, 1]], 'amount': 1, 'glints': 1},
        'clouds': {'regions': [[[round(x, 3), round(y, 3)] for x, y in sky]], 'amount': 1},
        'mist': {'regions': [[0, round(top - 0.06, 3), 1, round(min(1, top + 0.04), 3)]], 'amount': 0.35},
    }
    if spots >= 12:
        live['lights'] = {'amount': 1, 'cell': max(3, round(image.width / 160))}
    return {'horizon_candidates': horizon, 'skyline': skyline, 'light_spots': spots, 'picture': [image.width, image.height], 'proposal': live}


# ---- overlays ---------------------------------------------------------------------------------------------------------------

COLOURS = {'water': (0, 255, 255), 'clouds': (255, 255, 0), 'mist': (255, 160, 255), 'lights': (90, 255, 90)}


def draw_overlay(image, block, width=1200):
    picture = image.convert('RGB')
    picture = picture.resize((width, round(picture.height * width / picture.width)), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(picture, 'RGBA')

    def at(x, y):
        return (x * picture.width, y * picture.height)

    for name, colour in COLOURS.items():
        for region in (block.get(name) or {}).get('regions') or []:
            points = [(region[0], region[1]), (region[2], region[1]), (region[2], region[3]), (region[0], region[3])] if isinstance(region[0], (int, float)) else region
            draw.polygon([at(*p) for p in points], fill=colour + (50,), outline=colour + (255,))
    for craft in block.get('craft') or []:
        draw.line([at(*craft['from']), at(*craft['to'])], fill=(255, 80, 80, 255), width=2)
        draw.ellipse([at(*craft['from'])[0] - 5, at(*craft['from'])[1] - 5, at(*craft['from'])[0] + 5, at(*craft['from'])[1] + 5], outline=(255, 80, 80, 255))
    for step in range(1, 10):
        draw.line([at(step / 10, 0), at(step / 10, 1)], fill=(255, 255, 255, 40))
        draw.line([at(0, step / 10), at(1, step / 10)], fill=(255, 255, 255, 40))
        draw.text((at(step / 10, 0)[0] + 2, 2), f'{step / 10:.1f}', fill=(255, 255, 0, 255))
        draw.text((2, at(0, step / 10)[1] + 2), f'{step / 10:.1f}', fill=(255, 255, 0, 255))
    return picture


# ---- apply and clear ----------------------------------------------------------------------------------------------------------

def apply_presets(directory, clean, only=None, dry=False):
    """Write each preset into the scene's manifest entry (everything else of the entry stays). Returns the scenes written."""
    scenes = manifest_scenes(directory)
    written = []
    for name, block in clean.items():
        if only and name not in only:
            continue
        entry = scenes.get(name)
        if not isinstance(entry, dict):
            print(f'  {name}: not in {directory}/scenes.json: skipped')
            continue
        if entry.get('look') != 'photo':
            print(f'  {name}: look is {entry.get("look")}, live effects are for the photo look: skipped')
            continue
        updated = {**entry, 'live': block}
        size = len(json.dumps(block, separators=(',', ':')))
        print(f'  {name}: {", ".join(k for k in block if k != "version")} ({size} bytes)')
        if not dry:
            tablet_media.update_manifest(name, updated, directory)
        written.append(name)
    final = Path(directory) / tablet_media.MANIFEST
    if not dry and final.is_file() and final.stat().st_size > MAX_MANIFEST_BYTES:
        print(f'WARNING: scenes.json is {final.stat().st_size} bytes; the server reads at most 65536', file=sys.stderr)
    return written


def clear_presets(directory, only=None):
    scenes = manifest_scenes(directory)
    cleared = []
    for name, entry in scenes.items():
        if isinstance(entry, dict) and 'live' in entry and (not only or name in only):
            tablet_media.update_manifest(name, {k: v for k, v in entry.items() if k != 'live'}, directory)
            cleared.append(name)
    return cleared


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--directory', type=Path, default=tablet_media.PRIVATE, help='the scene folder (default: the real private one; it is only read unless --apply/--clear)')
    parser.add_argument('--presets', type=Path, default=PRESETS)
    parser.add_argument('--only', nargs='*', help='only these scenes')
    parser.add_argument('--check', action='store_true', help='validate the presets and say what is wrong')
    parser.add_argument('--overlay', type=Path, metavar='DIR', help='write each scene\'s picture with its preset regions drawn on it into DIR')
    parser.add_argument('--out', type=Path, help='save the proposal (numbers only) to this file instead of only printing it')
    parser.add_argument('--apply', action='store_true', help='write the presets into the scene folder\'s scenes.json')
    parser.add_argument('--clear', action='store_true', help='remove every live block from the scene folder\'s scenes.json')
    parser.add_argument('--dry-run', action='store_true', help='with --apply: show what would be written')
    parser.add_argument('--yes', action='store_true', help='allow --apply/--clear on the real private folder')
    args = parser.parse_args(argv)
    directory = args.directory.expanduser()
    real = directory.resolve() == tablet_media.PRIVATE.resolve()

    if args.clear:
        if real and not args.yes:
            parser.error('--clear on the real private folder needs --yes')
        print('cleared:', ', '.join(clear_presets(directory, args.only)) or 'nothing')
        return 0

    presets = load_presets(args.presets)
    clean, problems = check_presets(presets)
    for problem in problems:
        print('PROBLEM', problem, file=sys.stderr)

    if args.check or args.apply or args.overlay:
        if problems:
            print(f'{len(problems)} problem(s): fix them first', file=sys.stderr)
            return 1
        print(f'{len(clean)} preset(s) are valid: {", ".join(clean)}')
    if args.overlay:
        args.overlay.mkdir(parents=True, exist_ok=True)
        scenes = manifest_scenes(directory)
        for name, block in clean.items():
            path = picture_path(directory, name, scenes.get(name) or {})
            if path is None:
                print(f'  {name}: no picture in {directory}: skipped')
                continue
            with Image.open(path) as image:
                out = args.overlay / f'overlay-{name}.png'
                draw_overlay(image, block).save(out)
                print('  wrote', out)
    if args.apply:
        if real and not args.yes:
            parser.error('--apply on the real private folder needs --yes (the orchestrator does that at deployment)')
        written = apply_presets(directory, clean, args.only, args.dry_run)
        print(('would write: ' if args.dry_run else 'written: ') + (', '.join(written) or 'nothing'))
        return 0
    if args.check or args.overlay:
        return 0

    # the default: propose, read only
    scenes = manifest_scenes(directory)
    names = args.only or [n for n, e in sorted(scenes.items()) if isinstance(e, dict) and e.get('look') == 'photo']
    proposals = {}
    for name in names:
        path = picture_path(directory, name, scenes.get(name) or {})
        if path is None:
            print(f'{name}: no picture in {directory}: skipped')
            continue
        with Image.open(path) as image:
            found = propose(image, name)
        proposals[name] = found
        print(f'{name}: picture {found["picture"][0]}x{found["picture"][1]}, sea line candidates {found["horizon_candidates"]}, {found["light_spots"]} small lights')
        print('  ' + json.dumps(found['proposal'], separators=(',', ':')))
    if args.out:
        args.out.write_text(json.dumps({'version': 1, 'scenes': {n: p['proposal'] for n, p in proposals.items()}}, indent=1), encoding='utf-8')
        print('saved', args.out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
