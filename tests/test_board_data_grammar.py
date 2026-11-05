"""The same information on every screen of the library (Tony, 2026-11-03).

Every scene the board can show, the eight of the rotation and every archived version, answers to the same grammar:

  - the week's quota left, of Codex and of Claude;
  - Claude's five-hour session: its quota left and its time left;
  - the weekly reset of each provider;
  - the saved resets of each provider;
  - and an unknown reading never looks like an empty one: a missing week, a missing session and an unknown number of saved
    resets each differ from the same thing at zero.

Changing any of these must change the picture. A scene that cannot show one of them without becoming cluttered is listed in
`CANNOT`, with the reason, and the test checks that the gap is still real: fix the scene and the test asks to delete the line.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from token_tv import board_cyber_scenes
from token_tv.board_arcade import render_arcade
from token_tv.board_art import render_countdown
from token_tv.board_dials import render_dials
from token_tv.board_gameboy import render_gameboy_board
from token_tv.board_neon_bridge import render_neon_bridge
from token_tv.board_pages import LCD_GRID, PAGE_NAMES, PAGE_SIZE
from token_tv.board_paradise import render_paradise
from token_tv.board_platform import render_platform
from token_tv.board_scenes import SCENES, render_archive
from token_tv.board_surf import render_surf
from token_tv.sample import snapshot
from tests.test_board_beach import fictional_art

NOW, HOUR, DAY = 1_800_000_000, 3600, 86400

# The eight pages of the rotation draw through their own renderers; every other scene goes through render_archive.
PAGES = {
    'game-boy': lambda data: render_gameboy_board(data, screen=PAGE_SIZE, grid=LCD_GRID['game-boy']),
    'paradise': render_paradise,
    'code-forge': render_neon_bridge,
    'surf': render_surf,
    'dials': render_dials,
    'arcade': render_arcade,
    'cockpit': render_platform,
    'countdown': render_countdown,
}
# The beach Tony actually sees has a private film: its compact panels are a separate layout from the legacy beach.
FILM = 'paradise (film)'

# scene -> {check: why this scene cannot show it without clutter}. Proposal for both (Tony's call, nothing is hidden here):
# hide them from the library, Neon District replaced them in the rotation. NOTE: code-forge is also the factory-default page 3
# (PAGE_NAMES), so hiding it means choosing another default first.
NO_ROOM_ON_THE_BRIDGE = (
    'The only text on this art is a 4.7 px name and a percentage on two small signs hanging under the bridge (Claude\'s already '
    'carries the five-hour plate); a weekly reset and three saved-reset icons would be two more rows of 5 px text on each sign.')
NO_ROOM_ON_THE_TOWERS = (
    'The two signs are 38 and 44 px panels projected onto slanted facades; a reset row plus three icons does not fit the 38 px '
    'Claude panel and would have to cover the facade art around it, in text smaller than anything else on the board.')
GAP = ('codex reset', 'claude reset', 'codex saved resets', 'claude saved resets', 'unknown saved resets are not zero')
CANNOT = {'code-forge': {check: NO_ROOM_ON_THE_BRIDGE for check in GAP},
          'neon-towers': {check: NO_ROOM_ON_THE_TOWERS for check in GAP}}

CHECKS = ('codex week', 'claude week', 'five-hour quota', 'five-hour time', 'codex reset', 'claude reset',
          'codex saved resets', 'claude saved resets',
          'unknown week is not zero (codex)', 'unknown week is not zero (claude)', 'unknown session is not empty',
          'unknown saved resets are not zero')


def reading(codex_left=62, claude_left=41, five_left=58, five_secs=2 * HOUR + 600, codex_secs=3 * DAY + 10 * HOUR,
            claude_secs=5 * DAY + 4 * HOUR, saved=(2, 1)):
    """A fictional snapshot. `None` for a quota drops that window: the reading is unknown. `saved` is (codex, claude)."""
    codex = [('WEEK', 100 - codex_left, codex_secs)] if codex_left is not None else []
    claude = [('WEEK', 100 - claude_left, claude_secs)] if claude_left is not None else []
    if five_left is not None:
        claude.append(('5H', 100 - five_left, five_secs))
    data = snapshot(now=NOW, sample=[('codex', 'CODEX', 'codex', codex), ('claude', 'CLAUDE', 'claude', claude)])
    for provider, count in zip(('codex', 'claude'), saved):
        if count is not None:
            data['accounts'][provider]['banked_resets'] = {'available': count, 'confirmed_at': NOW, 'source': 'manual'}
    return data


# Each check is a pair of readings that must give two different pictures.
PAIRS = {
    'codex week': (reading(), reading(codex_left=35)),
    'claude week': (reading(), reading(claude_left=70)),
    'five-hour quota': (reading(), reading(five_left=25)),
    'five-hour time': (reading(), reading(five_secs=4 * HOUR + 1200)),
    'codex reset': (reading(), reading(codex_secs=1 * DAY + 2 * HOUR)),
    'claude reset': (reading(), reading(claude_secs=2 * DAY + 6 * HOUR)),
    'codex saved resets': (reading(), reading(saved=(3, 1))),
    'claude saved resets': (reading(), reading(saved=(2, 3))),
    'unknown week is not zero (codex)': (reading(codex_left=None), reading(codex_left=0)),
    'unknown week is not zero (claude)': (reading(claude_left=None), reading(claude_left=0)),
    'unknown session is not empty': (reading(five_left=None), reading(five_left=0)),
    'unknown saved resets are not zero': (reading(saved=(None, None)), reading(saved=(0, 0))),
}


class DataGrammarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Private photographs and films are optional and never part of a test: every scene is drawn from fictional art.
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        for filename in board_cyber_scenes.FILES.values():
            Image.new('RGB', (640, 480), (96, 70, 150)).save(Path(cls.directory.name) / filename)
        patches = [patch.object(board_cyber_scenes, 'ART', Path(cls.directory.name)),
                   patch('token_tv.board_arcade.local_stage.load', return_value=None),
                   patch('token_tv.board_beach.load', return_value=None),
                   patch('time.time', return_value=NOW)]
        for each in patches:
            each.start()
            cls.addClassCleanup(each.stop)
        board_cyber_scenes._cached_backdrop.cache_clear()
        cls.addClassCleanup(board_cyber_scenes._cached_backdrop.cache_clear)
        cls.cache = {}

    def picture(self, scene, data):
        key = (scene, repr(sorted(data['accounts'].items(), key=lambda item: item[0])))
        if key not in self.cache:
            if scene == FILM:
                with patch('token_tv.board_beach.load', return_value=fictional_art()):
                    image = render_paradise(data, waves=2)[0]
            elif scene in PAGES:
                image = PAGES[scene](data)
            else:
                image = render_archive(scene, data)[0]
            self.cache[key] = image.convert('RGB').tobytes()
        return self.cache[key]

    def test_every_scene_of_the_library_is_covered(self):
        self.assertEqual(len(SCENES), 25)
        self.assertEqual(set(PAGES), set(PAGE_NAMES))
        self.assertTrue(set(PAGE_NAMES) <= set(SCENES))
        self.assertTrue(set(CANNOT) <= set(SCENES) | {FILM})
        for scene, gaps in CANNOT.items():
            self.assertTrue(set(gaps) <= set(CHECKS), scene)
            self.assertTrue(all(isinstance(reason, str) and len(reason) > 30 for reason in gaps.values()), scene)

    def test_a_scene_drawn_twice_from_the_same_reading_gives_the_same_picture(self):
        # Without this a "different picture" proves nothing: nothing may depend on chance, the clock or a cache.
        for scene in (*SCENES, FILM):
            with self.subTest(scene=scene):
                first = self.picture(scene, reading())
                self.cache.clear()
                self.assertEqual(first, self.picture(scene, reading()))

    def test_every_scene_answers_to_the_same_grammar(self):
        failures = []
        for scene in (*SCENES, FILM):
            for check in CHECKS:
                before, after = PAIRS[check]
                changed = self.picture(scene, before) != self.picture(scene, after)
                excused = check in CANNOT.get(scene, {})
                if not changed and not excused:
                    failures.append(f'{SCENES.get(scene, scene)} ({scene}) does not show: {check}')
                if changed and excused:
                    failures.append(f'{scene} now shows "{check}": delete it from CANNOT')
        self.assertEqual(failures, [], '\n' + '\n'.join(failures))


if __name__ == '__main__':
    unittest.main()
