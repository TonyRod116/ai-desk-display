"""Screen choices are local, persistent, and never mistaken for delivery."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PIL import ImageChops

from token_tv.board import publish_pages
from token_tv.board_pages import PAGE_NAMES, frame_size, render_board_pages
from token_tv.board_scenes import ARCHIVED_SCENES, BoardScenes, render_archive
from token_tv.sample import snapshot


class SceneSettingsTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'scenes.json'
        self.changed = threading.Event()
        self.scenes = BoardScenes(self.path, self.changed)

    def test_gallery_starts_with_new_cities_and_ends_with_older_versions(self):
        from unittest.mock import patch
        with patch('token_tv.board_scenes.available', return_value=True):
            catalog = self.scenes.status()['scene_catalog']
        ids = [item['id'] for item in catalog]
        self.assertEqual(ids[:2], ['violet-horizon', 'neon-district'])
        self.assertLess(ids.index('neon-towers'), ids.index('neon-smooth'))
        self.assertLess(ids.index('neon-smooth'), ids.index('neon-pixel'))
        self.assertLess(ids.index('code-editor'), ids.index('code-workshop'))
        self.assertTrue(all(item['archived'] for item in catalog[10:]))

    def test_defaults_then_persist_without_changing_other_slots(self):
        self.assertEqual(self.scenes.snapshot(), PAGE_NAMES)
        self.assertFalse(self.path.exists())
        self.scenes.confirm(PAGE_NAMES)
        self.scenes.select({'slot': 6, 'scene': 'deep-space'})
        desired = self.scenes.snapshot()
        self.assertEqual(desired[:6], PAGE_NAMES[:6])
        self.assertEqual(desired[6:], ('deep-space', PAGE_NAMES[7]))
        self.assertTrue(self.changed.is_set())
        self.assertTrue(self.scenes.status()['scene_pending'][6])
        self.assertEqual(BoardScenes(self.path, threading.Event()).snapshot(), desired)
        self.scenes.confirm(desired)
        self.assertFalse(self.scenes.status()['scene_pending'][6])

    def test_reorder_is_saved_as_one_change_and_remains_pending_until_delivered(self):
        self.scenes.confirm(PAGE_NAMES)
        order = [1, 3, 0, 2, 4, 5, 7, 6]
        self.scenes.reorder({'expected': list(PAGE_NAMES), 'order': order})
        desired = tuple(PAGE_NAMES[i] for i in order)
        self.assertEqual(self.scenes.snapshot(), desired)
        self.assertEqual(BoardScenes(self.path, threading.Event()).snapshot(), desired)
        self.assertTrue(self.changed.is_set())
        status = self.scenes.status()
        self.assertEqual(status['scene_delivered_ids'], list(PAGE_NAMES))
        self.assertEqual(status['scene_pending'], [i != order[i] for i in range(8)])

    def test_reorder_rejects_stale_or_invalid_input_without_changing_screens(self):
        original = list(PAGE_NAMES)
        for value in (
            {'expected': original, 'order': [0] * 8},
            {'expected': original, 'order': list(range(7))},
            {'expected': original, 'order': list(range(7)) + [True]},
            {'expected': original, 'order': list(range(7)) + [8]},
            {'expected': original[::-1], 'order': list(range(8))},
            {'expected': original, 'order': list(range(8)), 'extra': 1},
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.scenes.reorder(value)
        self.assertEqual(self.scenes.snapshot(), PAGE_NAMES)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.changed.is_set())

    def test_reorder_preserves_duplicate_screens_and_saved_settings_on_write_failure(self):
        from unittest.mock import patch
        self.scenes.select({'slot': 1, 'scene': PAGE_NAMES[0]})
        before = self.scenes.snapshot()
        previous_file = self.path.read_bytes()
        self.changed.clear()
        order = [1, 2, 0, 3, 4, 5, 6, 7]
        with patch.object(Path, 'replace', side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):
                self.scenes.reorder({'expected': list(before), 'order': order})
        self.assertEqual(self.scenes.snapshot(), before)
        self.assertEqual(self.path.read_bytes(), previous_file)
        self.assertFalse(self.changed.is_set())
        self.scenes.reorder({'expected': list(before), 'order': order})
        self.assertEqual(self.scenes.snapshot(), tuple(before[i] for i in order))

    def test_out_of_order_delivery_remains_pending(self):
        self.scenes.confirm(PAGE_NAMES)
        self.scenes.select({'slot': 6, 'scene': 'deep-space'})
        in_flight = self.scenes.snapshot()
        self.scenes.select({'slot': 6, 'scene': 'cockpit'})
        self.scenes.confirm(in_flight)
        status = self.scenes.status()
        self.assertEqual(status['scene_delivered_ids'][6], 'deep-space')
        self.assertTrue(status['scene_pending'][6])
        self.scenes.confirm(self.scenes.snapshot())
        self.assertFalse(self.scenes.status()['scene_pending'][6])

    def test_invalid_or_corrupt_settings_never_replace_the_current_screens(self):
        for value in ({'slot': True, 'scene': 'deep-space'}, {'slot': 8, 'scene': 'deep-space'},
                      {'slot': 0, 'scene': '../image'}, {'slot': 0, 'scene': []},
                      {'slot': 0, 'scene': 'deep-space', 'extra': 1}):
            with self.assertRaises(ValueError):
                self.scenes.select(value)
        self.assertFalse(self.path.exists())
        self.path.write_text('{broken')
        damaged = BoardScenes(self.path, self.changed)
        self.assertTrue(damaged.status()['scene_settings_error'])
        with self.assertRaises(ValueError):
            damaged.snapshot()
        with self.assertRaises(OSError):
            damaged.select({'slot': 0, 'scene': 'deep-space'})
        self.assertEqual(self.path.read_text(), '{broken')

    def test_publisher_confirms_only_after_a_successful_transfer(self):
        class FakePublisher:
            capacity = 8
            def __init__(self):
                self.pages = {}
                self.fail = False
            def ping(self):
                return ''.join('1' if i in self.pages else '0' for i in range(8))
            def upload(self, index, image):
                if self.fail:
                    raise OSError('simulated connection loss')
                self.pages[index] = image
                return {'page': index}

        board = FakePublisher()
        sent = {}
        original = [str(i).encode() for i in range(8)]
        publish_pages(board, original, sent)
        self.scenes.confirm(PAGE_NAMES)
        self.scenes.select({'slot': 6, 'scene': 'deep-space'})
        desired = self.scenes.snapshot()
        replacement = list(original)
        replacement[6] = b'space'
        board.fail = True
        with self.assertRaises(OSError):
            publish_pages(board, replacement, sent)
        self.assertTrue(self.scenes.status()['scene_pending'][6])
        board.fail = False
        receipts = publish_pages(board, replacement, sent)
        self.scenes.confirm(desired[:board.capacity])
        self.assertEqual([receipt['page'] for receipt in receipts], [6])
        self.assertEqual(board.pages[6], b'space')
        self.assertFalse(self.scenes.status()['scene_pending'][6])
        self.assertTrue(all(board.pages[i] == original[i] for i in range(8) if i != 6))

    def test_each_verified_slot_is_reported_even_if_a_later_one_fails(self):
        class InterruptedBoard:
            capacity = 8
            def ping(self): return '00000000'
            def upload(self, index, image):
                if index == 2:
                    raise OSError('simulated interruption')
                return {'page': index}
        ids = self.scenes.snapshot()
        with self.assertRaises(OSError):
            publish_pages(InterruptedBoard(), [b'demo'] * 8, {},
                          on_verified=lambda slot: self.scenes.confirm_slot(slot, ids[slot]))
        status = self.scenes.status()
        self.assertEqual(status['scene_delivered_ids'][:3], [PAGE_NAMES[0], PAGE_NAMES[1], None])
        self.assertEqual(status['scene_pending'][:3], [False, False, True])


class SceneRenderingTests(unittest.TestCase):
    def setUp(self):
        self.demo = snapshot(time.time(), [
            ('codex', 'CODEX', 'codex', [('WEEK', 25, 5 * 86400)]),
            ('claude', 'CLAUDE', 'claude', [('WEEK', 40, 4 * 86400), ('5H', 15, 8000)]),
        ])

    def test_archives_render_at_screen_size_and_space_keeps_its_animation(self):
        space, animation = render_archive('deep-space', self.demo, animated=True)
        pocket, no_animation = render_archive('game-boy-pocket', self.demo, animated=True)
        self.assertEqual(space.size, (320, 240))
        self.assertEqual(pocket.size, (320, 240))
        self.assertTrue(animation)
        self.assertIsNone(no_animation)

    def test_exhausted_codex_credits_change_all_recovered_screens(self):
        row = self.demo['accounts']['codex']
        row.update(quota_origin='codex_official_cli', credits_balance='12.5')
        row['windows'][0]['used_percent'] = 100
        for scene in ARCHIVED_SCENES:
            credited, _ = render_archive(scene, self.demo)
            del row['credits_balance']
            unknown, _ = render_archive(scene, self.demo)
            self.assertIsNotNone(ImageChops.difference(credited, unknown).getbbox(), scene)
            row['credits_balance'] = '12.5'

    def test_credits_stay_in_the_codex_row_with_one_or_three_providers(self):
        for count in (1, 3):
            accounts = [('codex', 'CODEX', 'codex', [('WEEK', 100, 5 * 86400)])]
            if count == 3:
                accounts += [
                    ('claude', 'CLAUDE', 'claude', [('WEEK', 40, 4 * 86400)]),
                    ('grok', 'GROK', 'grok', [('BUDGET', 20, 3 * 86400)]),
                ]
            demo = snapshot(time.time(), accounts)
            row = demo['accounts']['codex']
            row.update(quota_origin='codex_official_cli', credits_balance='12.5')
            for scene, next_row in [('pixel-retro', 82), ('amber-terminal', 116), ('orbit', 109)]:
                with self.subTest(count=count, scene=scene):
                    credited, _ = render_archive(scene, demo)
                    del row['credits_balance']
                    unknown, _ = render_archive(scene, demo)
                    row['credits_balance'] = '12.5'
                    difference = ImageChops.difference(credited, unknown).getbbox()
                    self.assertIsNotNone(difference)
                    if count == 3:
                        self.assertLessEqual(difference[3], next_row)

    def test_each_archive_produces_a_valid_frame_and_compatible_animation(self):
        from token_tv.board_anim import decode
        from token_tv.board_pages import rgb565_frame
        for scene in ARCHIVED_SCENES:
            with self.subTest(scene=scene):
                image, payload = render_archive(scene, self.demo, animated=True)
                self.assertEqual(image.size, (320, 240))
                self.assertEqual(frame_size(rgb565_frame(image, anim=payload)), (320, 240))
                if payload:
                    decoded = decode(payload)
                    self.assertLessEqual(len(decoded['sprites']), 4)
                    self.assertTrue(all(s['w'] <= 96 and s['h'] <= 96 for s in decoded['sprites']))

    def test_replacement_is_only_the_chosen_slot(self):
        original = render_board_pages(self.demo)
        selection = list(PAGE_NAMES)
        selection[6] = 'deep-space'
        changed = render_board_pages(self.demo, scene_ids=selection)
        self.assertEqual(changed[:6], original[:6])
        self.assertEqual(changed[7:], original[7:])
        self.assertNotEqual(changed[6], original[6])
        self.assertEqual(frame_size(changed[6]), (320, 240))
