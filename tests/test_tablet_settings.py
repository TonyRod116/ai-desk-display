import json
import os
import tempfile
import unittest
from pathlib import Path

from token_tv import tablet_settings
from token_tv.tablet_settings import Settings, apply, defaults

SCENES = ('city', 'paradise', 'surf')


class SettingsTests(unittest.TestCase):
    def test_a_patch_changes_only_known_fields_with_valid_values(self):
        patch = {'scene': 'paradise', 'motion': 'on', 'night': {'enabled': False, 'start': '22:15', 'level': 40, 'unknown': 1},
                 'sound': {'volume': 30, 'enabled': 'yes'}, 'alerts': {'quota': 15}, 'photos': {'seconds': 45},
                 'place': {'lat': 40, 'lon': -3.7}, 'nothing': {'at': 'all'}}
        out = apply(defaults(), patch, SCENES)
        self.assertEqual((out['scene'], out['motion']), ('paradise', 'on'))
        self.assertEqual(out['night'], {'enabled': False, 'start': '22:15', 'end': '07:30', 'level': 40, 'clock_only': False})
        self.assertEqual(out['sound'], {'enabled': True, 'volume': 30, 'at_night': False})        # 'yes' is not a boolean: kept as it was
        self.assertEqual((out['alerts']['quota'], out['photos']['seconds']), (15, 45))
        self.assertEqual(out['place'], {'lat': 40.0, 'lon': -3.7})
        self.assertNotIn('nothing', out)
        self.assertEqual(set(out), set(defaults()))

    def test_values_outside_their_range_are_ignored(self):
        bad = {'night': {'start': '24:00', 'end': '7:30', 'level': 3}, 'sound': {'volume': 101}, 'alerts': {'quota': 0, 'disk': 31},
               'photos': {'seconds': 4}, 'place': {'lat': 91, 'lon': float('nan')}, 'auto': {'mode': 'shuffle', 'minutes': 241},
               'scene': 'not-a-scene', 'motion': 'sometimes'}
        self.assertEqual(apply(defaults(), bad, SCENES), defaults())
        for wrong_type in ({'night': {'level': True}}, {'night': {'level': 25.5}}, {'sound': {'volume': '50'}}, {'night': 'dark'}, 'text', [1], None):
            self.assertEqual(apply(defaults(), wrong_type, SCENES), defaults(), wrong_type)

    def test_the_scene_is_a_known_id_auto_or_photos(self):
        for scene in ('auto', 'photos', 'city'):
            self.assertEqual(apply(defaults(), {'scene': scene}, SCENES)['scene'], scene)
        self.assertEqual(apply(defaults(), {'scene': 'unknown-adventure'}, SCENES)['scene'], 'auto')           # not in this catalogue

    def test_hidden_scenes_keep_at_least_one_and_persist_independently_of_rotation(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, 'settings.json')
            settings = Settings(path, SCENES)
            self.assertEqual(settings.get()['disabled_scenes'], [])
            settings.update({'disabled_scenes': ['surf', 'missing', 'surf'], 'auto': {'rotate': ['surf', 'city']}})
            restored = Settings(path, SCENES)
            self.assertEqual(restored.get()['disabled_scenes'], ['surf'])
            self.assertEqual(restored.update({'disabled_scenes': list(SCENES)})['disabled_scenes'], ['surf'])
            state = restored.update({'disabled_scenes': []})
            self.assertEqual(state['disabled_scenes'], [])
            self.assertEqual(state['auto']['rotate'], ['surf', 'city'])

    def test_settings_are_private_survive_a_restart_and_a_damaged_file_means_the_defaults(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, 'tablet-settings.json')
            first = Settings(path, SCENES)
            self.assertEqual(first.get(), defaults())
            self.assertFalse(path.exists())                                                       # nothing to save yet
            first.update({'scene': 'surf', 'night': {'level': 10}})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            again = Settings(path, SCENES)
            self.assertEqual((again.get()['scene'], again.get()['night']['level']), ('surf', 10))
            path.write_text('{ not json', encoding='utf-8')
            self.assertEqual(Settings(path, SCENES).get(), defaults())
            path.write_text(json.dumps({'scene': 'city', 'night': {'level': 9999}}), encoding='utf-8')
            loaded = Settings(path, SCENES).get()
            self.assertEqual((loaded['scene'], loaded['night']['level']), ('city', 25))
            path.write_text('x' * (tablet_settings.MAX_FILE + 1), encoding='utf-8')
            self.assertEqual(Settings(path, SCENES).get(), defaults())
            self.assertEqual([name for name in os.listdir(temp) if name.startswith('.settings-')], [])    # no half-written leftovers

    def test_get_returns_a_copy_and_an_unchanged_update_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp, 'tablet-settings.json')
            settings = Settings(path, SCENES)
            settings.get()['night']['level'] = 99
            self.assertEqual(settings.get()['night']['level'], 25)
            settings.update({'night': {'level': 25}})
            self.assertFalse(path.exists())

    def test_it_never_reaches_for_the_boards_own_state(self):
        source = Path(tablet_settings.__file__).read_text(encoding='utf-8')
        for forbidden in ('board_control', 'board-night', '.config', 'token-tv', 'import board', 'from token_tv.board'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()


class AutoSceneListTests(unittest.TestCase):
    """Which scenes the automatic modes may show (Tony, 2026-11-10): the rotation and each part of the day."""
    SCENES = ('city', 'paradise', 'surf', 'city-iso')

    def test_the_lists_start_empty_which_means_the_suggested_scenes(self):
        from token_tv import tablet_settings as ts
        auto = ts.defaults()['auto']
        self.assertEqual(auto['rotate'], [])
        self.assertEqual(auto['parts'], {'dawn': [], 'day': [], 'dusk': [], 'night': []})

    def test_a_valid_list_is_kept_in_order_without_repeats(self):
        from token_tv import tablet_settings as ts
        out = ts.apply(ts.defaults(), {'auto': {'rotate': ['surf', 'city', 'surf'], 'parts': {'dusk': ['paradise'], 'night': ['city-iso', 'surf']}}}, self.SCENES)
        self.assertEqual(out['auto']['rotate'], ['surf', 'city'])
        self.assertEqual(out['auto']['parts']['dusk'], ['paradise'])
        self.assertEqual(out['auto']['parts']['night'], ['city-iso', 'surf'])
        self.assertEqual(out['auto']['parts']['dawn'], [])                 # what was not sent is not touched

    def test_unknown_names_and_odd_values_are_dropped_and_a_non_list_is_ignored(self):
        from token_tv import tablet_settings as ts
        start = ts.apply(ts.defaults(), {'auto': {'rotate': ['surf']}}, self.SCENES)
        out = ts.apply(start, {'auto': {'rotate': ['nope', 5, None, 'city', ['x'], {'a': 1}], 'parts': {'day': 'city', 'dawn': ['../etc', 'paradise']}}}, self.SCENES)
        self.assertEqual(out['auto']['rotate'], ['city'])
        self.assertEqual(out['auto']['parts']['day'], [])                  # a string is not a list: unchanged
        self.assertEqual(out['auto']['parts']['dawn'], ['paradise'])
        self.assertEqual(ts.apply(start, {'auto': {'rotate': 'city'}}, self.SCENES)['auto']['rotate'], ['surf'])
        self.assertEqual(ts.apply(start, {'auto': {'rotate': {'city': 1}}}, self.SCENES)['auto']['rotate'], ['surf'])
        self.assertEqual(ts.apply(start, {'auto': 'x'}, self.SCENES)['auto']['rotate'], ['surf'])

    def test_an_empty_list_goes_back_to_the_suggested_scenes_and_only_known_part_names_exist(self):
        from token_tv import tablet_settings as ts
        start = ts.apply(ts.defaults(), {'auto': {'rotate': ['surf'], 'parts': {'day': ['city']}}}, self.SCENES)
        out = ts.apply(start, {'auto': {'rotate': [], 'parts': {'day': [], 'teatime': ['city']}}}, self.SCENES)
        self.assertEqual((out['auto']['rotate'], out['auto']['parts']['day']), ([], []))
        self.assertEqual(set(out['auto']['parts']), {'dawn', 'day', 'dusk', 'night'})

    def test_the_list_is_bounded(self):
        from token_tv import tablet_settings as ts
        many = tuple(f's{n}' for n in range(40))
        out = ts.apply(ts.defaults(), {'auto': {'rotate': list(many)}}, many)
        self.assertEqual(len(out['auto']['rotate']), ts.MAX_POOL)

    def test_the_lists_survive_a_restart_and_a_damaged_file_keeps_the_defaults(self):
        import json, tempfile
        from pathlib import Path
        from token_tv import tablet_settings as ts
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'settings.json'
            first = ts.Settings(path, self.SCENES)
            first.update({'auto': {'minutes': 60, 'rotate': ['surf', 'city']}})
            again = ts.Settings(path, self.SCENES).get()
            self.assertEqual((again['auto']['minutes'], again['auto']['rotate']), (60, ['surf', 'city']))
            path.write_text(json.dumps({'auto': {'rotate': ['gone', 'surf']}}), encoding='utf-8')
            self.assertEqual(ts.Settings(path, self.SCENES).get()['auto']['rotate'], ['surf'])
