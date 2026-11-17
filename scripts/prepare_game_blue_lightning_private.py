"""Prepare a private tablet atlas from a locally supplied Atari Lynx cartridge.

The ROM is read in memory and never executed. A locally held gameplay reference
is used only to verify the sprite palette; no screenshot is copied into the
atlas. ROMs, derived pictures and references must stay outside Git and services.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import prepare_game_token_run as packer  # noqa: E402
from scripts import tablet_media as media  # noqa: E402

PRIVATE_ROOT = Path.home() / '.local/share/ai-desk-display'
ROM_SIZE = 131072
ROM_SHA1 = 'be08076586f76db368db1769380dcbb6de2a6513'

# Verified by same-state direction traces on the supported cartridge. Suzy
# mirrors these five original bank steps for rightward flight.
AUTHENTIC_PLAYER_POSES = {
    'level': (0xea16, 0xf285, 0xf3cd, 0xf596, 0xf7d7),
    'up': (0xfaa4, 0x10c3e, 0x10e21, 0x1109a, 0x11386),
    'down': (0x116ab, 0x1186a, 0x11a40, 0x11c16, 0x11e61),
}
AUTHENTIC_PLAYER_TRANSITIONS = {'up': 0x1219f, 'down': 0x122b6}
AUTHENTIC_ENEMY_POSES = (0xbd6d, 0xbe0d, 0xbee6, 0xc021, 0xc1ae, 0xc228,
                         0xc2f9, 0xc3f9, 0xc52b, 0xc639, 0xc6e2, 0xc7ea)
ENEMY_SIZES = (5, 7, 10, 14, 18, 24, 32, 42, 54)
AUTHENTIC_CLOUD_POSES = (0x157fb, 0x1590f)
CLOUD_SIZES = (16, 24, 36, 54, 80, 120, 180)


def read_cartridge(archive_path: Path) -> bytes:
    if archive_path.stat().st_size > 2 * 1024 * 1024:
        raise ValueError('Cartridge archive is too large')
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if len(members) != 1:
            raise ValueError('Expected one cartridge in the archive')
        item = members[0]
        if (item.file_size != ROM_SIZE or item.compress_size > ROM_SIZE + 4096 or
                item.flag_bits & 1 or stat.S_ISLNK(item.external_attr >> 16) or
                Path(item.filename).name != item.filename or '\\' in item.filename):
            raise ValueError('Unexpected cartridge member')
        data = archive.read(item)
    if hashlib.sha1(data).hexdigest() != ROM_SHA1:
        raise ValueError('Cartridge does not match the supported version')
    return data


def decode_line(data: bytes, bpp: int) -> list[int]:
    """Decode a single Suzy packed line, with strict bounds for bad data."""
    if bpp not in (1, 2, 3, 4):
        raise ValueError('Invalid pixel depth')
    bits = int.from_bytes(data, 'big')
    left = len(data) * 8
    pixels = []
    while left >= 5:
        left -= 5
        head = (bits >> left) & 31
        if head == 0:
            break
        literal, count = head >> 4, (head & 15) + 1
        needed = bpp * (count if literal else 1)
        if needed > left:
            raise ValueError('Truncated sprite packet')
        if literal:
            for _ in range(count):
                left -= bpp
                pixels.append((bits >> left) & ((1 << bpp) - 1))
        else:
            left -= bpp
            pixels.extend([(bits >> left) & ((1 << bpp) - 1)] * count)
        if len(pixels) > 256:
            raise ValueError('Sprite line too wide')
    return pixels


def decode_sprite(data: bytes, start: int, bpp: int = 3):
    """Return the original indexed pixels and their hardware reference point."""
    if not 0 <= start < len(data):
        raise ValueError('Sprite starts outside the cartridge')
    groups: list[list[list[int]]] = [[]]
    at = start
    for _ in range(512):
        if at >= len(data):
            raise ValueError('Sprite extends beyond the cartridge')
        length = data[at]
        if length == 0:
            break
        if length == 1:
            if len(groups) >= 4:
                raise ValueError('Too many sprite quadrants')
            groups.append([])
            at += 1
            continue
        if at + length >= len(data):
            raise ValueError('Sprite line extends beyond the cartridge')
        groups[-1].append(decode_line(data[at + 1:at + length], bpp))
        at += length
    else:
        raise ValueError('Unterminated sprite')
    points = []
    for quadrant, lines in enumerate(groups):
        for y, row in enumerate(lines):
            for x, colour in enumerate(row):
                if colour:
                    points.append((x if quadrant in (0, 1) else -1 - x,
                                   y if quadrant in (0, 3) else -1 - y, colour))
    if not points:
        raise ValueError('Sprite has no visible pixels')
    x0 = min(x for x, _, _ in points)
    x1 = max(x for x, _, _ in points)
    y0 = min(y for _, y, _ in points)
    y1 = max(y for _, y, _ in points)
    if x1 - x0 >= 256 or y1 - y0 >= 256:
        raise ValueError('Sprite exceeds safe dimensions')
    indices = Image.new('L', (x1 - x0 + 1, y1 - y0 + 1))
    pixels = indices.load()
    for x, y, colour in points:
        pixels[x - x0, y - y0] = colour
    return indices, (-x0, -y0)


def reference_palette(indices: Image.Image, anchor, reference: Image.Image):
    """Verify a 160x102 reference against the straight sprite, then sample its colours."""
    if reference.width % 160 or reference.height % 102 or reference.width // 160 != reference.height // 102:
        raise ValueError('The gameplay reference has unexpected dimensions')
    reference = reference.convert('RGB').resize((160, 102), Image.Resampling.NEAREST)
    observed = collections.defaultdict(collections.Counter)
    for y in range(indices.height):
        for x in range(indices.width):
            index = indices.getpixel((x, y))
            if not index:
                continue
            rx, ry = 80 + x - anchor[0], 80 + y - anchor[1]
            if not 0 <= rx < 160 or not 0 <= ry < 102:
                raise ValueError('Reference does not contain the complete sprite')
            observed[index][reference.getpixel((rx, ry))] += 1
    if len(observed) < 6 or any(sum(c.values()) < 5 or c.most_common(1)[0][1] / sum(c.values()) < .98 for c in observed.values()):
        raise ValueError('Reference palette does not match the cartridge sprite')
    return {i: values.most_common(1)[0][0] for i, values in observed.items()}


def colour_sprite(indices: Image.Image, palette: dict[int, tuple[int, int, int]]) -> Image.Image:
    rgba = Image.new('RGBA', indices.size)
    pix = rgba.load()
    for y in range(indices.height):
        for x in range(indices.width):
            index = indices.getpixel((x, y))
            if index:
                if index not in palette:
                    raise ValueError('The reference palette is incomplete')
                pix[x, y] = (*palette[index], 255)
    return rgba


def scale_sprite(image: Image.Image, anchor, scale: float):
    width, height = max(1, round(image.width * scale)), max(1, round(image.height * scale))
    return image.resize((width, height), Image.Resampling.NEAREST), (round(anchor[0] * scale), round(anchor[1] * scale))


def rotate_sprite(image: Image.Image, anchor, angle: float):
    """Rotate about the original hardware anchor without losing its pixels."""
    side, centre = 320, 160
    canvas = Image.new('RGBA', (side, side))
    canvas.alpha_composite(image, (centre - anchor[0], centre - anchor[1]))
    canvas = canvas.rotate(angle, resample=Image.Resampling.NEAREST, center=(centre, centre))
    box = canvas.getbbox()
    if not box:
        raise ValueError('Empty rotated sprite')
    return canvas.crop(box), (centre - box[0], centre - box[1])


def add_authentic_player_poses(frames, cartridge, palette, scale=1.18):
    """Add original pitch/bank sprites while keeping their hardware anchors."""
    names = {}
    for family, addresses in AUTHENTIC_PLAYER_POSES.items():
        names[family] = []
        for level, address in enumerate(addresses):
            name = f'player-{family}-{level}'
            pixels, anchor = decode_sprite(cartridge, address)
            frames[name] = scale_sprite(colour_sprite(pixels, palette), anchor, scale)
            names[family].append(name)
    for family, address in AUTHENTIC_PLAYER_TRANSITIONS.items():
        name = f'player-{family}-transition'
        pixels, anchor = decode_sprite(cartridge, address)
        frames[name] = scale_sprite(colour_sprite(pixels, palette), anchor, scale)
        names[family + '_transition'] = name
    return {'version': 1, 'bank_angles': [0, 22.5, 45, 67.5, 90],
            'right_flip': True, **names, 'evidence': 'local_rom_input_trace'}


def read_private_pose_metadata(path):
    """Read explicit private draw-time palettes, never ship them with the code."""
    path = Path(path)
    if path.is_symlink() or not path.resolve().is_relative_to(PRIVATE_ROOT.resolve()):
        raise ValueError('Pose palette metadata must stay in the private directory')
    if not 0 < path.stat().st_size <= 64 * 1024:
        raise ValueError('Pose palette metadata exceeds safe bounds')
    return json.loads(path.read_text(encoding='utf-8'))


def _private_pose_entries(metadata, addresses, bpp):
    if (not isinstance(metadata, dict) or metadata.get('version') != 1 or
            metadata.get('scene') != 'blue-lightning' or
            not isinstance(metadata.get('poses'), list) or len(metadata['poses']) != len(addresses)):
        raise ValueError('Invalid private pose metadata')
    entries = []
    for address, entry in zip(addresses, metadata['poses']):
        if not isinstance(entry, dict) or type(entry.get('rom_offset')) is not int or entry['rom_offset'] != address:
            raise ValueError('Pose metadata does not match the supported cartridge')
        supplied, flips = entry.get('palette'), entry.get('flips')
        if (not isinstance(supplied, dict) or not supplied or
                any(key not in tuple(str(i) for i in range(1, 1 << bpp)) for key in supplied) or
                any(not isinstance(rgb, list) or len(rgb) != 3 or
                    any(type(v) is not int or not 0 <= v <= 255 for v in rgb) for rgb in supplied.values()) or
                not isinstance(flips, list) or not 1 <= len(flips) <= 4 or
                any(not isinstance(flip, list) or len(flip) != 2 or
                    any(type(v) is not bool for v in flip) for flip in flips)):
            raise ValueError('Invalid private palette or observed mirrors')
        entries.append((address, {int(k): tuple(v) for k, v in supplied.items()}, flips))
    return entries


def add_authentic_enemy_poses(frames, cartridge, metadata):
    """Decode traced silhouettes with private palettes and a common physical scale."""
    poses = []
    for index, (address, palette, flips) in enumerate(_private_pose_entries(metadata, AUTHENTIC_ENEMY_POSES, 3)):
        pixels, anchor = decode_sprite(cartridge, address)
        image = colour_sprite(pixels, palette)
        names = []
        for size in ENEMY_SIZES:
            name = f'enemy-pose-{index}-{size}'
            # A narrow banked sprite must not grow taller as its wings rotate.
            frames[name] = scale_sprite(image, anchor, size / 72)
            names.append(name)
        poses.append({'frames': names, 'flips': flips})
    return {'version': 1, 'widths': list(ENEMY_SIZES), 'reference_width': 72, 'poses': poses,
            'sequence': [4, 5, 6, 7, 8, 7, 6, 5, 4], 'orientation': 'trace_unclassified',
            'evidence': 'local_rom_trace_and_user_identification'}


def add_authentic_cloud_poses(frames, cartridge, metadata):
    """Keep cloud pixels intact, with visual anchors for the adapted 3D scene."""
    sources = []
    for address, palette, flips in _private_pose_entries(metadata, AUTHENTIC_CLOUD_POSES, 2):
        pixels, anchor = decode_sprite(cartridge, address, 2)
        sources.append((colour_sprite(pixels, palette), anchor, flips))
    reference_width = max(image.width for image, _anchor, _flips in sources)
    poses = []
    for index, (image, anchor, flips) in enumerate(sources):
        names = []
        for size in CLOUD_SIZES:
            name = f'cloud-pose-{index}-{size}'
            scaled, _source_anchor = scale_sprite(image, anchor, size / reference_width)
            frames[name] = (scaled, (scaled.width // 2, scaled.height // 2))
            names.append(name)
        poses.append({'frames': names, 'flips': flips, 'source_size': list(image.size), 'source_anchor': list(anchor)})
    return {'version': 1, 'anchor_mode': 'visual_center', 'widths': list(CLOUD_SIZES),
            'reference_width': reference_width, 'poses': poses, 'draw_mode': 5, 'transparent_index': 0,
            'evidence': 'local_rom_trace_and_user_identification'}


def append_frames(positions, original, added):
    """Append a layer without repacking any previously prepared rectangle."""
    extra_positions, extra = packer.pack(added, width=original.width)
    offset_y = original.height + 1
    atlas = Image.new('RGBA', (original.width, offset_y + extra.height))
    atlas.paste(original, (0, 0))
    atlas.paste(extra, (0, offset_y))
    positions = dict(positions)
    positions.update({name: (x, y + offset_y) for name, (x, y) in extra_positions.items()})
    return positions, atlas


def pack_preserving_legacy(legacy, added):
    """Append new poses so old image/metadata readers retain every rectangle."""
    positions, original = packer.pack(legacy, width=512)
    return append_frames(positions, original, added)


def thumbnail(frames):
    image = Image.new('RGB', (240, 160), '#45c7ec')
    d = ImageDraw.Draw(image)
    d.rectangle((0, 75, 240, 160), fill='#db812c')
    for y in range(77, 160, 5):
        for x in range((y * 13) % 19, 240, 19):
            d.rectangle((x, y, x + 3, y + 2), fill='#ba5d13')
    plane, anchor = frames['player-0']
    image.paste(plane, (120 - anchor[0], 115 - anchor[1]), plane)
    enemy, anchor = frames['enemy-0-18']
    image.paste(enemy, (150 - anchor[0], 55 - anchor[1]), enemy)
    return image


def write(rom: Path, reference_path: Path, out: Path, enemy_metadata: Path | None = None,
          cloud_metadata: Path | None = None) -> dict:
    root, out = PRIVATE_ROOT.resolve(), out.resolve()
    if not out.is_relative_to(root) or out == root:
        raise ValueError('Output must be a private AI Desk Display subdirectory')
    out.mkdir(mode=0o700, parents=True, exist_ok=True)
    names = ('scene-blue-lightning.png', 'scene-blue-lightning.json', 'thumb-blue-lightning.webp')
    if any((out / name).exists() or (out / name).is_symlink() for name in names):
        raise FileExistsError('Choose an empty private output directory')
    cartridge = read_cartridge(rom)
    straight, straight_anchor = decode_sprite(cartridge, 0xea16)
    with Image.open(reference_path) as ref:
        palette = reference_palette(straight, straight_anchor, ref)
    frames = {}
    # Two complete cartridge poses plus nearest-neighbour in-between frames.
    # Keeping the centre of rotation fixed prevents the plane jumping when it
    # banks; the other direction mirrors this same sequence at runtime.
    pixels, anchor = decode_sprite(cartridge, 0xea16)
    straight = scale_sprite(colour_sprite(pixels, palette), anchor, 1.18)
    pixels, anchor = decode_sprite(cartridge, 0xeb27)
    banked = scale_sprite(colour_sprite(pixels, palette), anchor, 1.18)
    poses = [straight, rotate_sprite(*straight, 7), rotate_sprite(*straight, 14),
             banked, rotate_sprite(*banked, 8), rotate_sprite(*banked, 16)]
    for index, pose in enumerate(poses):
        frames[f'player-{index}'] = pose
    # An intentionally neutral tint differentiates enemy aircraft; the shapes
    # themselves remain original indexed sprites.
    grey = {i: (min(255, int(.55 * r + .35 * g + .1 * b) + 45),) * 3 for i, (r, g, b) in palette.items()}
    for model, address in enumerate((0xb532, 0xb8c9)):
        enemy, anchor = decode_sprite(cartridge, address)
        enemy = colour_sprite(enemy, grey)
        for width in (5, 7, 10, 14, 18, 24, 32, 42, 54):
            frames[f'enemy-{model}-{width}'] = scale_sprite(enemy, anchor, width / enemy.width)
    mesa, anchor = decode_sprite(cartridge, 0x15498)
    warm = {i: (min(255, int(.8 * r + .3 * g + 80)), min(255, int(.35 * r + .4 * g + 55)), min(255, int(.18 * r + .25 * b + 25)))
            for i, (r, g, b) in palette.items()}
    mesa = colour_sprite(mesa, warm)
    for width in (12, 18, 26, 38, 55, 80, 110):
        frames[f'mesa-{width}'] = scale_sprite(mesa, anchor, width / mesa.width)
    ship, anchor = decode_sprite(cartridge, 0x9fd2)
    ship = colour_sprite(ship, grey)
    for width in (10, 16, 24, 36, 52, 72):
        frames[f'ship-{width}'] = scale_sprite(ship, anchor, width / ship.width)
    added = {}
    aircraft_poses = add_authentic_player_poses(added, cartridge, palette)
    positions, atlas = pack_preserving_legacy(frames, added)
    frames.update(added)
    enemy_poses = None
    if enemy_metadata is not None:
        enemies = {}
        enemy_poses = add_authentic_enemy_poses(enemies, cartridge, read_private_pose_metadata(enemy_metadata))
        positions, atlas = append_frames(positions, atlas, enemies)
        frames.update(enemies)
    cloud_poses = None
    if cloud_metadata is not None:
        clouds = {}
        cloud_poses = add_authentic_cloud_poses(clouds, cartridge, read_private_pose_metadata(cloud_metadata))
        positions, atlas = append_frames(positions, atlas, clouds)
        frames.update(clouds)
    if atlas.width > 4096 or atlas.height > 4096:
        raise ValueError('Atlas exceeds tablet limits')
    data = packer.describe(frames, {}, positions, atlas)
    data['scene'] = 'blue-lightning'
    data['aircraft_poses'] = aircraft_poses
    if enemy_poses:
        data['enemy_poses'] = enemy_poses
    if cloud_poses:
        data['cloud_poses'] = cloud_poses
    png, js, thumb = [out / name for name in names]
    media._write_atomically(png, lambda p: atlas.save(p, format='PNG', optimize=True), media.MAX_IMAGE_BYTES)
    data['atlas_sha256'] = hashlib.sha256(png.read_bytes()).hexdigest()
    media._write_atomically(js, lambda p: p.write_text(json.dumps(data, separators=(',', ':'), sort_keys=True), encoding='utf-8'), 512 * 1024)
    media.save_thumbnail(thumbnail(frames), thumb)
    return {'frames': len(frames), 'atlas_size': list(atlas.size), 'bytes': png.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--rom', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--enemy-metadata', type=Path, help='Optional private draw-time enemy palettes and observed mirrors')
    parser.add_argument('--cloud-metadata', type=Path, help='Optional private draw-time cloud palettes and observed mirrors')
    args = parser.parse_args()
    os.umask(0o077)
    print(json.dumps(write(args.rom, args.reference, args.out, args.enemy_metadata, args.cloud_metadata)))


if __name__ == '__main__':
    main()
