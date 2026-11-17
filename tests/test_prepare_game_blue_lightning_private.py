"""Lynx sprite tests contain synthetic bytes and invented colours only."""
import hashlib
import json
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from PIL import Image

from scripts import prepare_game_blue_lightning_private as blue


def packet(bits):
    bits += '0' * (-len(bits) % 8)
    return int(bits, 2).to_bytes(len(bits) // 8, 'big')


def row(*pixels):
    # A literal run of two-bit pixels followed by a line terminator.
    data = packet('1' + f'{len(pixels) - 1:04b}' + ''.join(f'{p:02b}' for p in pixels) + '00000')
    return bytes([len(data) + 1]) + data


class LynxTests(unittest.TestCase):
    def test_literal_and_packed_runs_and_bounds(self):
        self.assertEqual(blue.decode_line(packet('10001' + '01' + '10' + '00000'), 2), [1, 2])
        self.assertEqual(blue.decode_line(packet('00010' + '11' + '00000'), 2), [3, 3, 3])
        with self.assertRaisesRegex(ValueError, 'Truncated'):
            blue.decode_line(bytes([0xff]), 4)

    def test_four_quadrants_preserve_reference_and_transparency(self):
        stream = row(1, 2) + b'\x01' + row(3, 0) + b'\x01' + row(2, 1) + b'\x01' + row(3, 1) + b'\x00'
        image, anchor = blue.decode_sprite(stream, 0, 2)
        self.assertEqual(anchor, (2, 1))
        self.assertEqual(image.size, (4, 2))
        self.assertEqual([image.getpixel((x, y)) for y in range(2) for x in range(4)], [1, 2, 3, 0, 1, 3, 1, 2])

    def test_rejects_truncated_sprite_and_unexpected_extra_quadrants(self):
        with self.assertRaises(ValueError):
            blue.decode_sprite(b'\x03\x80', 0, 2)
        with self.assertRaises(ValueError):
            blue.decode_sprite(row(1) + b'\x01' * 5 + b'\x00', 0, 2)

    def test_reference_must_match_each_index_consistently(self):
        indices = Image.new('L', (42, 1))
        for x in range(42):
            indices.putpixel((x, 0), x // 7 + 1)
        reference = Image.new('RGB', (160, 102))
        for x in range(42):
            i = x // 7 + 1
            reference.putpixel((60 + x, 80), (i * 20, i * 10, 0))
        palette = blue.reference_palette(indices, (20, 0), reference)
        self.assertEqual(palette[3], (60, 30, 0))
        reference.putpixel((60, 80), (1, 2, 3))
        with self.assertRaisesRegex(ValueError, 'does not match'):
            blue.reference_palette(indices, (20, 0), reference)

    def test_archive_validates_content_and_does_not_follow_paths(self):
        content = b'synthetic cartridge'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'cartridge.zip'
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('game.lnx', content)
            with mock.patch.object(blue, 'ROM_SIZE', len(content)), mock.patch.object(blue, 'ROM_SHA1', hashlib.sha1(content).hexdigest()):
                self.assertEqual(blue.read_cartridge(path), content)
                with zipfile.ZipFile(path, 'w') as z:
                    z.writestr('../game.lnx', content)
                with self.assertRaises(ValueError):
                    blue.read_cartridge(path)
                with zipfile.ZipFile(path, 'w') as z:
                    link = zipfile.ZipInfo('game.lnx')
                    link.create_system = 3
                    link.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(link, content)
                with self.assertRaises(ValueError):
                    blue.read_cartridge(path)

    def test_refuses_output_outside_private_directory(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            root.mkdir()
            with mock.patch.object(blue, 'PRIVATE_ROOT', root):
                with self.assertRaisesRegex(ValueError, 'private'):
                    blue.write(Path(temp) / 'none', Path(temp) / 'none', Path(temp) / 'outside')

    def test_dangling_output_symlinks_are_never_replaced(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            root.mkdir()
            for index, name in enumerate(('scene-blue-lightning.png', 'scene-blue-lightning.json', 'thumb-blue-lightning.webp')):
                with self.subTest(name=name):
                    output = root / str(index)
                    output.mkdir()
                    link = output / name
                    link.symlink_to(root / 'fictional-missing-target')
                    with mock.patch.object(blue, 'PRIVATE_ROOT', root), mock.patch.object(blue, 'read_cartridge') as read:
                        with self.assertRaises(FileExistsError):
                            blue.write(root / 'fictional.zip', root / 'fictional.png', output)
                        read.assert_not_called()
                    self.assertTrue(link.is_symlink())

    def test_original_pose_families_decode_synthetic_sprites_with_their_anchors(self):
        addresses = {
            'level': (0xea16, 0xf285, 0xf3cd, 0xf596, 0xf7d7),
            'up': (0xfaa4, 0x10c3e, 0x10e21, 0x1109a, 0x11386),
            'down': (0x116ab, 0x1186a, 0x11a40, 0x11c16, 0x11e61),
        }
        named = [(f'player-{family}-{i}', address)
                 for family, offsets in addresses.items() for i, address in enumerate(offsets)]
        named += [('player-up-transition', 0x1219f), ('player-down-transition', 0x122b6)]
        cartridge = bytearray(0x12400)
        palette = {i: (i * 23, i * 11, i * 7) for i in range(1, 8)}
        expected = {}
        for i, (name, address) in enumerate(named):
            # Four invented quadrants, each one row, with a distinct width.
            width, colour = i % 4 + 1, i % 7 + 1
            data = packet('1' + f'{width - 1:04b}' + f'{colour:03b}' * width + '00000')
            line = bytes([len(data) + 1]) + data
            stream = b'\x01'.join([line] * 4) + b'\x00'
            cartridge[address:address + len(stream)] = stream
            expected[name] = (width, colour)
        frames = {}
        grid = blue.add_authentic_player_poses(frames, bytes(cartridge), palette, scale=1)
        self.assertEqual(len(frames), 17)
        self.assertEqual(grid['bank_angles'], [0, 22.5, 45, 67.5, 90])
        self.assertIs(grid['right_flip'], True)
        for family in addresses:
            self.assertEqual(grid[family], [f'player-{family}-{i}' for i in range(5)])
        self.assertEqual(grid['up_transition'], 'player-up-transition')
        self.assertEqual(grid['down_transition'], 'player-down-transition')
        for name, (image, anchor) in frames.items():
            width, colour = expected[name]
            self.assertEqual(anchor, (width, 1), name)
            self.assertEqual(image.size, (width * 2, 2), name)
            self.assertEqual(image.getpixel((0, 0)), (*palette[colour], 255), name)

    def test_appending_tall_poses_keeps_legacy_pixels_rectangles_and_anchors(self):
        old = {
            'player-0': (Image.new('RGBA', (8, 3), (12, 34, 56, 255)), (3, 1)),
            'enemy-0': (Image.new('RGBA', (5, 6), (78, 90, 12, 255)), (2, 4)),
        }
        added = {'player-up-4': (Image.new('RGBA', (3, 20), (34, 56, 78, 255)), (1, 10))}
        old_positions, old_image = blue.packer.pack(old, width=512)
        positions, image = blue.pack_preserving_legacy(old, added)
        for name in old:
            self.assertEqual(positions[name], old_positions[name])
        self.assertEqual(image.crop((0, 0, *old_image.size)).tobytes(), old_image.tobytes())
        self.assertGreater(positions['player-up-4'][1], old_image.height)
        x, y = positions['player-up-4']
        self.assertEqual(image.crop((x, y, x + 3, y + 20)).tobytes(), added['player-up-4'][0].tobytes())
        self.assertEqual(image.getpixel((0, old_image.height))[3], 0)
        self.assertEqual(old['player-0'][1], (3, 1))

    def test_enemy_poses_share_one_scale_and_preserve_observed_mirrors(self):
        offsets = (0xbd6d, 0xbe0d, 0xbee6, 0xc021, 0xc1ae, 0xc228,
                   0xc2f9, 0xc3f9, 0xc52b, 0xc639, 0xc6e2, 0xc7ea)
        cartridge = bytearray(0xc900)
        metadata = {'version': 1, 'scene': 'blue-lightning', 'poses': []}
        for i, address in enumerate(offsets):
            # Alternating invented tall and wide bitmaps expose per-pose scaling errors.
            width, rows = (2, 8) if i % 2 else (8, 2)
            packed = packet('1' + f'{width - 1:04b}' + '001' * width + '00000')
            line = bytes([len(packed) + 1]) + packed
            stream = b'\x01'.join([line * rows] * 4) + b'\x00'
            cartridge[address:address + len(stream)] = stream
            metadata['poses'].append({'rom_offset': address, 'palette': {'1': [23, 45, 67]},
                                      'flips': [[True, False]]})
        frames = {}
        grid = blue.add_authentic_enemy_poses(frames, bytes(cartridge), metadata)
        self.assertEqual(len(frames), 108)
        self.assertEqual(grid['sequence'], [4, 5, 6, 7, 8, 7, 6, 5, 4])
        self.assertEqual(grid['reference_width'], 72)
        for i, pose in enumerate(grid['poses']):
            self.assertEqual(pose['flips'], [[True, False]])
            for name, nominal in zip(pose['frames'], grid['widths']):
                image, anchor = frames[name]
                self.assertEqual(name, f'enemy-pose-{i}-{nominal}')
                scale = nominal / 72
                width, rows = (2, 8) if i % 2 else (8, 2)
                self.assertEqual(image.size, (max(1, round(width * 2 * scale)), max(1, round(rows * 2 * scale))))
                self.assertEqual(anchor, (round(width * scale), round(rows * scale)))

    def test_enemy_metadata_rejects_unobserved_values_and_nonprivate_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'private'
            root.mkdir()
            outside = Path(temp) / 'not-art.json'
            outside.write_text('{}')
            with mock.patch.object(blue, 'PRIVATE_ROOT', root):
                with self.assertRaisesRegex(ValueError, 'private'):
                    blue.read_private_pose_metadata(outside)
        with self.assertRaises(ValueError):
            blue.add_authentic_enemy_poses({}, b'', {'version': 1, 'scene': 'blue-lightning', 'poses': []})
        for palette, mirrors in (({'1': [256, 0, 0]}, [[True, False]]),
                                 ({'1': [1, 2, 3]}, [[1, False]])):
            metadata = {'version': 1, 'scene': 'blue-lightning', 'poses': [
                {'rom_offset': address, 'palette': palette, 'flips': mirrors}
                for address in blue.AUTHENTIC_ENEMY_POSES]}
            with self.assertRaisesRegex(ValueError, 'palette or observed mirrors'):
                blue.add_authentic_enemy_poses({}, b'', metadata)

    def test_enemy_append_preserves_both_legacy_and_already_added_player_region(self):
        legacy = {'old': (Image.new('RGBA', (8, 3), (1, 2, 3, 255)), (4, 2))}
        player = {'player-up-0': (Image.new('RGBA', (4, 20), (4, 5, 6, 255)), (2, 10))}
        positions, player_image = blue.pack_preserving_legacy(legacy, player)
        enemies = {'enemy-pose-0-5': (Image.new('RGBA', (3, 8), (7, 8, 9, 255)), (1, 4))}
        appended, image = blue.append_frames(positions, player_image, enemies)
        self.assertEqual({k: appended[k] for k in positions}, positions)
        self.assertEqual(image.crop((0, 0, *player_image.size)).tobytes(), player_image.tobytes())
        self.assertGreater(appended['enemy-pose-0-5'][1], player_image.height)

    def test_cloud_pixels_keep_private_source_origin_but_draw_about_the_visual_center(self):
        cartridge = bytearray(0x15a00)
        stream = row(0, 0) * 2 + row(0, 1, 0, 1) * 2 + b'\x00'
        metadata = {'version': 1, 'scene': 'blue-lightning', 'poses': []}
        for address in (0x157fb, 0x1590f):
            cartridge[address:address + len(stream)] = stream
            metadata['poses'].append({'rom_offset': address, 'palette': {'1': [40, 90, 130]},
                                      'flips': [[False, False]]})
        frames = {}
        grid = blue.add_authentic_cloud_poses(frames, bytes(cartridge), metadata)
        self.assertEqual(len(frames), 14)
        self.assertEqual(grid['anchor_mode'], 'visual_center')
        for pose in grid['poses']:
            self.assertEqual(pose['source_anchor'], [-1, -2])
            self.assertEqual(pose['source_size'], [3, 2])
            for name in pose['frames']:
                image, anchor = frames[name]
                self.assertEqual(anchor, (image.width // 2, image.height // 2))
                self.assertTrue(set(image.getchannel('A').tobytes()).issubset({0, 255}))
                self.assertEqual(image.getpixel((0, 0)), (40, 90, 130, 255))

    def test_written_json_checksum_binds_the_final_fictional_png(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            reference = root / 'fictional-reference.png'
            Image.new('RGB', (160, 102), (10, 20, 30)).save(reference)
            output = root / 'prepared'
            palette = {1: (20, 40, 60)}
            with (mock.patch.object(blue, 'PRIVATE_ROOT', root),
                  mock.patch.object(blue, 'read_cartridge', return_value=b'fictional'),
                  mock.patch.object(blue, 'decode_sprite', side_effect=lambda *_args: (Image.new('L', (4, 2), 1), (2, 1))),
                  mock.patch.object(blue, 'reference_palette', return_value=palette)):
                blue.write(root / 'fictional.zip', reference, output)
            data = json.loads((output / 'scene-blue-lightning.json').read_text())
            self.assertEqual(data['atlas_sha256'], hashlib.sha256((output / 'scene-blue-lightning.png').read_bytes()).hexdigest())


if __name__ == '__main__':
    unittest.main()
