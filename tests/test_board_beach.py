"""Stabilised private beach playback and compatibility with the native board."""

import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageChops, ImageDraw

from tests.test_board_forge import NOW, sample
from token_tv import board_beach, board_wave
from token_tv.board_pages import frame_size, render_board_pages, rgb565_frame
from token_tv.board_paradise import render_paradise

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'firmware' / 'board' / 'tools'))


def fictional_art():
    photo = Image.new('RGB', (320, 240), (166, 180, 160))
    photo.putpixel((218, 100), (244, 80, 48))  # the fixed boat, above the film
    palette = tuple(board_beach._word(((i * 7) % 256, (i * 13) % 256, (i * 19) % 256))
                    for i in range(256))
    frames = bytes((x * 3 + y * 7 + phase * 5) % 256
                   for phase in range(board_beach.FRAMES)
                   for y in range(board_beach.HEIGHT) for x in range(board_beach.WIDTH))
    return photo, palette, frames


def fictional_film_with_boat():
    palette = tuple(board_beach._word((128 + i // 8, 128 + i // 8, 128 + i // 8))
                    for i in range(256))
    pixels = b''.join(bytes([value]) * (40 * 56) for value in (0, 48, 96, 48))
    return (*fictional_art(), (palette, pixels))


def fictional_smooth_art():
    photo, palette, old = fictional_art()
    stride = board_beach.WIDTH * board_beach.HEIGHT
    frames = bytearray([128] * (stride * 48))
    for phase in range(48):
        value = 128 + min(phase, 48 - phase)
        for y in (*range(8, 16), *range(32, 48)):
            for x in range(32 + (y // 8) * 4, 80 + (y // 8) * 4):
                frames[phase * stride + y * board_beach.WIDTH + x] = value
    return photo, palette, old, None, (palette, bytes(frames))


def scene(data):
    with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_art()):
        image, payload = render_paradise(data, waves=2)
    raw = rgb565_frame(image)
    return image, payload, struct.unpack('<76800H', raw[8:]), board_beach.decode(payload)


class BeachFilmTests(unittest.TestCase):
    def test_smooth_film_preserves_frames_and_old_board_fallback(self):
        from token_tv.board import BoardDisplay
        board = BoardDisplay('http://192.168.1.50', '0123456789abcdef')
        with patch.object(board, 'info', return_value={'paired': True, 'waves': 4}):
            board.ensure_paired()
        self.assertEqual(board.waves, 4)
        art = fictional_smooth_art()
        with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=art):
            image, payload = render_paradise(sample(), waves=4)
            _, old = render_paradise(sample(), waves=3)
        self.assertEqual(payload[0], 4)
        self.assertEqual(old[0], 3)
        self.assertLessEqual(len(payload), 80000)
        film = board_wave.decode(payload)
        self.assertEqual(film['frames'], art[4][1])
        self.assertEqual(film['frame_count'], 48)
        self.assertEqual(frame_size(rgb565_frame(image, waves=payload)), (320, 240))
        background = struct.unpack('<76800H', rgb565_frame(image)[8:])
        self.assertEqual(board_beach.render_words(background, film, 0),
                         board_beach.render_words(background, film, 48 * 8))

    def test_smooth_film_rejects_corrupt_offsets_and_runs(self):
        payload = bytearray(board_beach.encode(fictional_smooth_art(), version=4))
        table = 12 + 512 + 7 * 4
        bad_offset = payload[:]
        struct.pack_into('<I', bad_offset, table, len(payload) + 10)
        bad_run = payload[:]
        offset, size = struct.unpack_from('<IH', payload, table)
        bad_run[offset:offset + size] = b'\xff' * size
        for bad in (payload[:-1], bad_offset, bad_run):
            with self.subTest(kind=len(bad)):
                with self.assertRaises(ValueError):
                    board_beach.decode(bytes(bad))

    def test_faster_film_and_gently_moving_boat_are_versioned_and_loop(self):
        from token_tv.board import BoardDisplay
        board = BoardDisplay('http://192.168.1.50', '0123456789abcdef')
        with patch.object(board, 'info', return_value={'paired': True, 'waves': 3}):
            board.ensure_paired()
        self.assertEqual(board.waves, 3)
        art = fictional_film_with_boat()
        with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=art):
            image, payload = render_paradise(sample(), waves=3)
        self.assertEqual(payload[0], 3)
        self.assertLessEqual(len(payload), 80000)
        film = board_wave.decode(payload)
        background = struct.unpack('<76800H', rgb565_frame(image)[8:])
        start = board_beach.render_words(background, film, 0, boat_step=0)
        moved = board_beach.render_words(background, film, 32, boat_step=16)
        loop = board_beach.render_words(background, film, 0, boat_step=64)
        self.assertEqual(start, list(background))
        self.assertEqual(start, loop)
        self.assertNotEqual(start[100 * 320 + 218], moved[100 * 320 + 218])
        self.assertEqual(start[:73 * 320], moved[:73 * 320], 'HUD and sky remain fixed')
        self.assertEqual(start[100 * 320 + 190], moved[100 * 320 + 190], 'background stays fixed')

    def test_compact_instruments_keep_real_reset_and_session_states(self):
        with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_art()):
            full, payload = render_paradise(sample(0, hearts=3), waves=2)
            empty, payload2 = render_paradise(sample(100, hearts=0), waves=2)
            unknown, payload3 = render_paradise({'accounts': {}}, waves=2)
            session, _ = render_paradise(sample(), waves=2)
            no_session, _ = render_paradise(sample(session=False), waves=2)
        self.assertEqual(payload, payload2)
        self.assertEqual(payload, payload3)
        self.assertEqual(len({im.crop((0, 0, 320, 73)).tobytes() for im in (full, empty, unknown)}), 3)
        self.assertEqual(session.crop((0, 0, 160, 73)).tobytes(), no_session.crop((0, 0, 160, 73)).tobytes())
        self.assertNotEqual(session.crop((160, 0, 320, 73)).tobytes(), no_session.crop((160, 0, 320, 73)).tobytes())
        self.assertEqual(session.crop((0, 73, 320, 240)).tobytes(), no_session.crop((0, 73, 320, 240)).tobytes())

    def test_film_moves_and_closes_while_the_boat_and_labels_stay_fixed(self):
        image, payload, background, film = scene(sample())
        initial = board_beach.render_words(background, film, 0)
        middle = board_beach.render_words(background, film, 24)
        self.assertEqual(initial, list(background))
        self.assertEqual(initial, board_beach.render_words(background, film, 64))
        self.assertEqual(initial[:board_beach.TOP * 320], middle[:board_beach.TOP * 320])
        self.assertNotEqual(initial[200 * 320 + 150], middle[200 * 320 + 150])
        self.assertEqual(image.getpixel((218, 100)), fictional_art()[0].getpixel((218, 100)))
        self.assertEqual(board_wave.decode(payload)['version'], 2)

    def test_bad_film_is_rejected_and_missing_art_uses_the_original_beach(self):
        image, payload, _, _ = scene(sample())
        raw = rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload
        self.assertEqual(frame_size(raw), (320, 240))
        for bad in (payload[:-1], payload + b'X', bytes([3]) + payload[1:], payload[:2] + b'\x00' + payload[3:]):
            malformed = rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(bad)) + bad
            self.assertIsNone(frame_size(malformed))
        with patch('token_tv.board_beach.load', return_value=None):
            _, legacy = render_paradise(sample(), waves=2)
        self.assertEqual(legacy[0], 1)

    def test_only_paradise_changes_and_old_boards_keep_the_existing_format(self):
        with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_art()):
            old = render_board_pages(sample(), anim=True, waves=True)
            new = render_board_pages(sample(), anim=True, waves=2)
            fast = render_board_pages(sample(), anim=True, waves=3)
        self.assertEqual(old[:1] + old[2:], new[:1] + new[2:])
        self.assertEqual(new[:1] + new[2:], fast[:1] + fast[2:])
        self.assertEqual(old[1][153616], 1)
        self.assertEqual(new[1][153616], 2)
        self.assertEqual(fast[1][153616], 3)

    def test_optional_boat_and_malformed_fast_films(self):
        art = fictional_film_with_boat()
        payload = board_beach.encode(art, version=3)
        self.assertIn('boat_frames', board_beach.decode(payload))
        self.assertNotIn('boat_frames', board_beach.decode(board_beach.encode(art[:3], version=3)))
        for bad in (payload[:-1], payload + b'X', payload[:1] + b'\x02' + payload[2:],
                    payload[:10] + b'\x03' + payload[11:]):
            with self.assertRaises(ValueError):
                board_beach.decode(bad)


    def test_preparing_the_film_preserves_animated_foreground_from_the_source(self):
        from tools.prepare_paradise_film import prepare

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frames = []
            for phase in range(8):
                frame = Image.new('RGB', (384, 480), (65, 145, 160))
                draw = ImageDraw.Draw(frame)
                x = 245 + 2 * min(phase, 8 - phase)
                draw.rectangle((x, 218, x + 23, 267), fill=(240, 55, 40))  # drifting boat
                draw.rectangle((40 + 24 * phase, 425, 84 + 24 * phase, 465), fill=(245, 245, 230))
                frames.append(frame)
            source = root / 'reference.gif'
            frames[0].save(source, save_all=True, append_images=frames[1:], duration=80, loop=0, optimize=False)
            prepare(source, root / 'out')
            with Image.open(root / 'out' / 'water.png') as film:
                values = film.convert('RGB')
            first = values.crop((0, 0, 160, 54))
            halfway = values.crop((0, 4 * 54, 160, 5 * 54))
            self.assertIsNotNone(ImageChops.difference(first, halfway).getbbox(),
                                 'moving foam near the bottom of the source must remain visible')
            with Image.open(root / 'out' / 'background.png') as still:
                self.assertEqual(still.size, (320, 240))
                self.assertGreater(still.getpixel((212, 105))[0], 150, 'the fixed boat remains in the photograph')
            with Image.open(root / 'out' / 'boat.png') as boat:
                values = boat.convert('RGB')
            first = values.crop((0, 0, 40, 56))
            halfway = values.crop((0, 2 * 56, 40, 3 * 56))
            self.assertIsNotNone(ImageChops.difference(first, halfway).getbbox())
            self.assertEqual(first.getpixel((0, 20)), halfway.getpixel((0, 20)), 'edges stay fixed')

    def test_smooth_preparation_keeps_original_and_makes_a_returning_loop(self):
        from tools.prepare_paradise_smooth import prepare_smooth
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pictures = []
            for phase in range(32):
                frame = Image.new('RGB', (384, 480), (65, 145, 160))
                # Keep frames distinct but postpone the breaking wave until
                # after the source midpoint, where it used to get cut off.
                frame.putpixel((0, 0), (phase * 7, 0, 0))
                ImageDraw.Draw(frame).rectangle((110 + phase, 345, 125 + phase, 365), fill=(225, 220, 210))
                if phase > 16:
                    ImageDraw.Draw(frame).rectangle((175, 380, 215, 440), fill=(240, 240, 230))
                pictures.append(frame)
            source = root / 'source.gif'
            pictures[0].save(source, save_all=True, append_images=pictures[1:], duration=70, loop=0, optimize=False)
            original = source.read_bytes()
            out = root / 'prepared'
            out.mkdir()
            (out / 'water.png').write_bytes(b'existing film')
            target = prepare_smooth(source, out)
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual((out / 'water.png').read_bytes(), b'existing film')
            with Image.open(target) as film:
                self.assertEqual((film.mode, film.size), ('P', (160, 54 * 48)))
                values = film.tobytes()
                colours = film.convert('RGB')
                start = colours.getpixel((80, 35))
                end = colours.getpixel((80, 24 * 54 + 35))
            stride = 160 * 54
            self.assertEqual(values[stride:2 * stride], values[47 * stride:48 * stride])
            self.assertGreater(sum(abs(a - b) for a, b in zip(start, end)), 30,
                               'the wave reaches the end of the source before returning')
            with self.assertRaises(FileExistsError):
                prepare_smooth(source, out)

    def test_damaged_optional_boat_does_not_disable_the_beach(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            Image.new('RGB', (320, 240)).save(root / 'background.png')
            water = Image.new('P', (160, 54 * 8))
            water.putpalette([value for i in range(256) for value in (i, i, i)])
            water.save(root / 'water.png')
            (root / 'boat.png').write_bytes(b'broken')
            with patch.object(board_beach, 'ART_DIRECTORY', root):
                board_beach.load.cache_clear()
                art = board_beach.load()
                self.assertIsNotNone(art)
                self.assertIsNone(art[3])
                self.assertEqual(board_beach.decode(board_beach.encode(art, 3))['version'], 3)
            board_beach.load.cache_clear()

    def test_exhausted_codex_credits_remain_inside_the_codex_film_panel(self):
        from copy import deepcopy
        from tests.test_board_credits import sample as credit_sample

        with_credit = credit_sample(balance='137.5')
        without_credit = deepcopy(with_credit)
        without_credit['accounts']['codex']['quota_origin'] = 'unverified'
        with patch('time.time', return_value=1000), patch('token_tv.board_beach.load', return_value=fictional_art()):
            before = render_board_pages(without_credit, waves=2)[1]
            after = render_board_pages(with_credit, waves=2)[1]
        a = struct.unpack('<76800H', before[8:153608])
        b = struct.unpack('<76800H', after[8:153608])
        changes = [(i % 320, i // 320) for i, (left, right) in enumerate(zip(a, b)) if left != right]
        self.assertTrue(changes, 'the exhausted balance must actually be shown')
        self.assertTrue(all(8 <= x < 80 and 19 <= y < 55 for x, y in changes),
                        'credits must replace only the Codex weekly number, not Claude or the photo')
        self.assertEqual(before[153608:], after[153608:], 'credits must not alter the water animation')


    def test_varied_credit_balances_do_not_touch_other_paradise_data(self):
        from copy import deepcopy
        from tests.test_board_credits import sample as credit_sample

        for balance in ('1000000000', '0.000001', None):
            with self.subTest(balance=balance):
                data = credit_sample(balance=balance)
                control = deepcopy(data)
                control['accounts']['codex']['quota_origin'] = 'unverified'
                with patch('time.time', return_value=1000), patch('token_tv.board_beach.load', return_value=fictional_art()):
                    with_credits, _ = render_paradise(data, waves=2)
                    without_credits, _ = render_paradise(control, waves=2)
                changed = ImageChops.difference(with_credits, without_credits).getbbox()
                self.assertIsNotNone(changed)
                x0, y0, x1, y1 = changed
                self.assertTrue(8 <= x0 < x1 <= 80 and 18 <= y0 < y1 <= 55, changed)  # antialiased edge


@unittest.skipUnless(shutil.which('g++'), 'needs native compiler')
class NativeBeachFilmTests(unittest.TestCase):
    def test_smooth_film_rejects_bad_offsets_and_compressed_frames_on_board(self):
        import anim_harness
        art = fictional_smooth_art()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=art):
                image, original = render_paradise(sample(), waves=4)
            table = 12 + 512 + 7 * 4
            offset, size = struct.unpack_from('<IH', original, table)
            offset_error, run_error = bytearray(original), bytearray(original)
            struct.pack_into('<I', offset_error, table, len(original) + 10)
            run_error[offset:offset + size] = b'\xff' * size
            for index, broken in enumerate((offset_error, run_error)):
                page = root / f'broken{index}.tvf'
                page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(broken)) + broken)
                folder = root / f'out{index}'
                folder.mkdir()
                result = subprocess.run([str(exe), str(page), str(folder), '200'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('wave=0', result.stdout)

    def test_smooth_film_matches_reference_through_full_loop_with_or_without_cache(self):
        import anim_harness
        art = fictional_smooth_art()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=art):
                image, payload = render_paradise(sample(), waves=4)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image, waves=payload))
            background = struct.unpack('<76800H', rgb565_frame(image)[8:])
            film = board_wave.decode(payload)
            for mode in ('full_cache', 'no_cache'):
                folder = root / mode
                folder.mkdir()
                result = subprocess.run([str(exe), str(page), str(folder), '3200', '200', 'precise', '100', mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('wave=1', result.stdout)
                self.assertLess(int(re.search(r'pushedPixels=(\d+)', result.stdout).group(1)), 16 * 320 * 108 // 2)
                for tick in (1, 4, 8, 15, 16):
                    step = (tick * 200 % 3200) * (48 * 128) // 3200
                    expected = board_beach.render_words(background, film, step, water_substeps=128)
                    self.assertEqual((folder / f'screen_{tick}.bin').read_bytes(), struct.pack('<76800H', *expected), tick)

    def test_sparse_water_only_redraws_its_changed_area(self):
        """A localised wave keeps the rest of the photo and avoids drawing it."""
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            photo = Image.new('RGB', (320, 240), (160, 176, 160))
            palette = tuple(board_beach._word((i, i, i)) for i in range(256))
            stride = board_beach.WIDTH * board_beach.HEIGHT
            frames = bytearray([128] * (stride * board_beach.FRAMES))
            for phase in range(1, board_beach.FRAMES):
                for y in (*range(8, 16), *range(32, 48)):
                    for x in range(32 + (y // 8) * 4, 96 + (y // 8) * 4):
                        frames[phase * stride + y * board_beach.WIDTH + x] = 128 + 8 * phase
            art = (photo, palette, bytes(frames), None)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=art):
                image, payload = render_paradise(sample(), waves=3)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            folders = {}
            for mode in ('full_cache', 'no_cache'):
                folder = root / mode
                folder.mkdir()
                result = subprocess.run([str(exe), str(page), str(folder), '3200', '200', 'precise', '100', mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                pixels = int(re.search(r'pushedPixels=(\d+)', result.stdout).group(1))
                self.assertLess(pixels, 16 * 320 * 108 // 2, result.stdout)
                folders[mode] = folder
            background = struct.unpack('<76800H', rgb565_frame(image)[8:])
            film = board_beach.decode(payload)
            for tick in range(1, 17):
                actual = (folders['full_cache'] / f'screen_{tick}.bin').read_bytes()
                self.assertEqual((folders['no_cache'] / f'screen_{tick}.bin').read_bytes(), actual, tick)
                if tick in (1, 4, 8, 16):
                    step = (tick * 200 % 3200) * 128 // 400
                    expected = board_beach.render_words(background, film, step, water_substeps=128)
                    self.assertEqual(actual, struct.pack('<76800H', *expected), tick)

    def test_compact_water_film_still_loads_under_memory_pressure(self):
        """Compaction must not need a second large buffer while loading."""
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            folders = {}
            for mode in ('full_cache', 'tight_compact'):
                folder = root / mode
                folder.mkdir()
                result = subprocess.run([str(exe), str(page), str(folder), '3200', '200', 'precise', '100', mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('beachStreamed=1', result.stdout, mode + ': ' + result.stdout)
                folders[mode] = folder
            for tick in range(1, 17):
                self.assertEqual((folders['tight_compact'] / f'screen_{tick}.bin').read_bytes(),
                                 (folders['full_cache'] / f'screen_{tick}.bin').read_bytes(), tick)

    def test_water_is_presented_at_a_steady_cadence(self):
        """The board should draw consistently while the wave clock keeps time."""
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            result = subprocess.run([str(exe), str(page), str(root), '400', '10', 'precise', '100', 'observe_cadence'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            previous = (root / 'screen_0.bin').read_bytes()
            changes = []
            for tick in range(1, 41):
                current = (root / f'screen_{tick}.bin').read_bytes()
                if current != previous:
                    changes.append(tick)
                previous = current
            self.assertEqual(len(changes), 20, changes)
            self.assertTrue(all(b - a == 2 for a, b in zip(changes, changes[1:])), changes)
            # At 400 ms the last paced frame was drawn at 385 ms. It must
            # follow real time, not run more slowly because fewer frames draw.
            background = struct.unpack('<76800H', rgb565_frame(image)[8:])
            expected = board_beach.render_words(background, board_beach.decode(payload),
                                                385 * 128 // 400, boat_step=3, water_substeps=128)
            self.assertEqual(previous, struct.pack('<76800H', *expected))

    def test_tiny_colour_changes_are_spread_smoothly_over_the_transition(self):
        """A one-step change should not make the whole sea jump at once."""
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            neutral = board_beach._word((128, 128, 128))
            brighter = board_beach._word((128, 132, 128))  # one green display step
            palette = (neutral, brighter) + (neutral,) * 254
            stride = board_beach.WIDTH * board_beach.HEIGHT
            frames = bytes(stride) + bytes([1]) * (stride * 7)
            art = (Image.new('RGB', (320, 240), (160, 176, 160)), palette, frames, None)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=art):
                image, payload = render_paradise(sample(), waves=3)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            result = subprocess.run([str(exe), str(page), str(root), '400', '25', 'precise'],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            positions = [2 * (y * 320 + x) for y in range(148, 240, 2) for x in range(0, 320, 2)]
            previous = (root / 'screen_0.bin').read_bytes()
            changes = []
            for tick in range(1, 17):
                current = (root / f'screen_{tick}.bin').read_bytes()
                changes.append(sum(previous[i:i+2] != current[i:i+2] for i in positions))
                previous = current
            self.assertGreater(min(changes), 250, changes)
            self.assertLess(max(changes), 700, changes)

    def test_water_cache_retries_after_temporary_memory_pressure(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            folders = {}
            for mode in ('recover_cache', 'no_cache', 'broken_cache'):
                folder = root / mode
                folder.mkdir()
                result = subprocess.run([str(exe), str(page), str(folder), '6000', '250', 'precise', '100', mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if mode == 'recover_cache':
                    self.assertIn('beachCacheRows=0 ', result.stdout)
                    self.assertIn('beachFinalCacheRows=64 cacheStatus=5 cacheAttemptAt=5000', result.stdout)
                elif mode == 'broken_cache':
                    self.assertIn('beachFinalCacheRows=0 cacheStatus=4 cacheAttemptAt=0', result.stdout)
                folders[mode] = folder
            for tick in (4, 19, 20, 21, 24):
                expected = (folders['no_cache'] / f'screen_{tick}.bin').read_bytes()
                self.assertEqual((folders['recover_cache'] / f'screen_{tick}.bin').read_bytes(), expected)
                self.assertEqual((folders['broken_cache'] / f'screen_{tick}.bin').read_bytes(), expected)

    def test_cached_water_reads_less_without_changing_pixels_and_falls_back_safely(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            page = root / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            results = {}
            for mode in ('full_cache', 'partial_cache', 'no_cache', 'fragmented_cache', 'broken_cache'):
                folder = root / mode
                folder.mkdir()
                result = subprocess.run([str(exe), str(page), str(folder), '200', '25', 'precise', '100', mode],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                # Eight water frames reuse one file, and releasing the scene closes it.
                self.assertIn('animationFileOpens=1', result.stdout)
                self.assertIn('animationFileClosed=1', result.stdout)
                metrics = re.search(r'beachCacheRows=(\d+) renderReadBytes=(\d+)', result.stdout)
                self.assertIsNotNone(metrics, result.stdout)
                results[mode] = (tuple(map(int, metrics.groups())), folder)
            (full_rows, full_bytes), full = results['full_cache']
            (partial_rows, partial_bytes), partial = results['partial_cache']
            (no_rows, no_bytes), none = results['no_cache']
            (fragmented_rows, fragmented_bytes), fragmented = results['fragmented_cache']
            (broken_rows, broken_bytes), broken = results['broken_cache']
            self.assertEqual((full_rows, partial_rows, no_rows), (108, 64, 0))
            # Separate bands can use fragmented memory even when no single
            # allocation is large enough for the complete photograph.
            self.assertEqual((fragmented_rows, broken_rows), (108, 0))
            self.assertEqual(full_bytes, 0)
            self.assertEqual(fragmented_bytes, full_bytes)
            self.assertLess(partial_bytes, no_bytes)
            self.assertEqual(broken_bytes, no_bytes)
            for tick in range(1, 9):
                expected = (none / f'screen_{tick}.bin').read_bytes()
                self.assertEqual((partial / f'screen_{tick}.bin').read_bytes(), expected)
                self.assertEqual((full / f'screen_{tick}.bin').read_bytes(), expected)
                self.assertEqual((fragmented / f'screen_{tick}.bin').read_bytes(), expected)
                self.assertEqual((broken / f'screen_{tick}.bin').read_bytes(), expected)

    def test_water_tracks_irregular_frame_times_without_coarse_jumps(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exe = anim_harness.build(folder)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            background = struct.unpack('<76800H', rgb565_frame(image)[8:])
            film = board_beach.decode(payload)
            page = folder / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            # The real screen takes about 45 ms to draw; that does not align
            # with the old 25 ms water steps.
            result = subprocess.run([str(exe), str(page), str(folder), '225', '45', 'precise'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for tick in range(1, 6):
                elapsed = tick * 45
                step = (elapsed % 3200) * 128 // 400
                expected = board_beach.render_words(background, film, step, boat_step=elapsed // 100, water_substeps=128)
                actual = (folder / f'screen_{tick}.bin').read_bytes()
                self.assertEqual(actual, struct.pack('<76800H', *expected), f'{elapsed} ms')

    def test_native_water_adds_in_between_frames_without_changing_the_loop_speed(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exe = anim_harness.build(folder)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            background = struct.unpack('<76800H', rgb565_frame(image)[8:])
            film = board_beach.decode(payload)
            page = folder / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            result = subprocess.run([str(exe), str(page), str(folder), '200', '25', 'precise'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('wave=1', result.stdout)
            for tick in range(1, 9):
                expected = board_beach.render_words(background, film, tick, boat_step=tick // 4, water_substeps=16)
                self.assertEqual((folder / f'screen_{tick}.bin').read_bytes(), struct.pack('<76800H', *expected), f'tick {tick}')
            fallback = folder / 'fallback'
            fallback.mkdir()
            result = subprocess.run([str(exe), str(page), str(fallback), '200', '25', 'precise', '100', 'no_lut'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            for tick in range(1, 9):
                self.assertEqual((fallback / f'screen_{tick}.bin').read_bytes(), (folder / f'screen_{tick}.bin').read_bytes())
            start = board_beach.render_words(background, film, 0, boat_step=0, water_substeps=16)
            between = board_beach.render_words(background, film, 1, boat_step=0, water_substeps=16)
            old_next = board_beach.render_words(background, film, 1, boat_step=0)
            self.assertNotEqual(between, start)
            self.assertNotEqual(between, old_next)
            self.assertEqual(old_next, board_beach.render_words(background, film, 2, boat_step=0, water_substeps=16))
            self.assertEqual(start, board_beach.render_words(background, film, 128, boat_step=0, water_substeps=16))

    def test_native_fast_waves_and_boat_match_reference_for_a_full_shared_loop(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exe = anim_harness.build(folder)
            with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_film_with_boat()):
                image, payload = render_paradise(sample(), waves=3)
            background = struct.unpack('<76800H', rgb565_frame(image)[8:])
            film = board_beach.decode(payload)
            page = folder / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            result = subprocess.run([str(exe), str(page), str(folder), '6400', '50'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('wave=1', result.stdout)
            self.assertIn('beachStreamed=1', result.stdout)
            for tick in range(128):
                # The harness samples on 20 ms ticks, just before each 50 ms
                # capture boundary. The boat stays on its 100 ms clock.
                elapsed = ((tick + 1) * 50 - 1) // 20 * 20
                step = (elapsed % 3200) * 128 // 400
                expected = board_beach.render_words(background, film, step,
                                                    boat_step=(elapsed // 100) % 64, water_substeps=128)
                self.assertEqual((folder / f'screen_{tick}.bin').read_bytes(),
                                 struct.pack('<76800H', *expected), f'tick {tick}')
            self.assertEqual((folder / 'screen_6400.bin').read_bytes(), struct.pack('<76800H', *background))

    def test_native_board_matches_the_reference_across_two_complete_loops(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            exe = anim_harness.build(folder)
            image, payload, background, film = scene(sample())
            page = folder / 'page.tvf'
            page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(payload)) + payload)
            result = subprocess.run([str(exe), str(page), str(folder), '12800', '100'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stderr, '')
            self.assertIn('wave=1', result.stdout)
            for step in range(64):
                expected = struct.pack('<76800H', *board_beach.render_words(background, film, step))
                for cycle in (0, 64):
                    self.assertEqual((folder / f'screen_{step+cycle}.bin').read_bytes(), expected,
                                     f'phase {step+cycle}')
            self.assertEqual((folder / 'screen_12800.bin').read_bytes(),
                             struct.pack('<76800H', *background))

    def test_native_board_rejects_bad_private_film_without_touching_the_still(self):
        import anim_harness
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            exe = anim_harness.build(root)
            image, payload, background, _ = scene({'accounts': {}})
            fast = board_beach.encode(fictional_film_with_boat(), version=3)
            for index, bad in enumerate((payload[:-1], payload + b'X', payload[:2] + b'\x00' + payload[3:],
                                         fast[:-1], fast[:1] + b'\x02' + fast[2:],
                                         fast[:10] + b'\x03' + fast[11:])):
                folder = root / str(index)
                folder.mkdir()
                page = folder / 'bad.tvf'
                page.write_bytes(rgb565_frame(image) + b'WAVE' + struct.pack('<I', len(bad)) + bad)
                result = subprocess.run([str(exe), str(page), str(folder), '200'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stderr, '')
                self.assertIn('readAnim=0', result.stdout)
                self.assertIn('wave=0', result.stdout)
                self.assertEqual((folder / 'screen_200.bin').read_bytes(), struct.pack('<76800H', *background))
