"""Stabilised private beach playback and compatibility with the native board."""

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


def scene(data):
    with patch('time.time', return_value=NOW), patch('token_tv.board_beach.load', return_value=fictional_art()):
        image, payload = render_paradise(data, waves=2)
    raw = rgb565_frame(image)
    return image, payload, struct.unpack('<76800H', raw[8:]), board_beach.decode(payload)


class BeachFilmTests(unittest.TestCase):
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
            for tick in range(128):
                # The harness samples on 20 ms ticks, just before each 50 ms
                # capture boundary. The boat stays on its 100 ms clock.
                elapsed = ((tick + 1) * 50 - 1) // 20 * 20
                expected = board_beach.render_words(background, film, (elapsed // 25) % 128,
                                                    boat_step=(elapsed // 100) % 64, water_substeps=16)
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
