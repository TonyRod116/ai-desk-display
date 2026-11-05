"""The quiet low-quota sign: a thin static line on the top edge of the provider's half, the same on every screen.

Tony (2026-11-03): calmer screens, nothing like a disco. Amber below 15 % left (the week; for Claude also the five-hour session),
red below 5 %; nothing at all when nothing is low, never for an unknown reading, still for an aged one.
"""
import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from token_tv import board_anim, board_cyber_scenes, board_low_quota as low
from token_tv.board_pages import PAGE_NAMES, render_board_pages
from token_tv.board_scenes import SCENES, render_archive
from tests.test_board_data_grammar import NOW, reading

BASE = 8 + 320 * 240 * 2
AMBER, RED = (255, 176, 32), (255, 64, 64)
ARCHIVED = tuple(scene for scene in SCENES if scene not in PAGE_NAMES)


def word(rgb):
    return ((rgb[0] >> 3) << 11) | ((rgb[1] >> 2) << 5) | (rgb[2] >> 3)


def words(frame):
    return struct.unpack('<76800H', frame[8:BASE])


def expected(name, provider):
    """Every pixel the line of `provider` may touch on page `name`, as (x, y)."""
    row, left, right = low.line(name, provider)
    return ({(x, row) for x in range(left, right + 1)} | {(x, row + 1) for x in range(left + 1, right)})


class Quiet(unittest.TestCase):
    """Private photographs and films are never part of a test."""
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.directory.cleanup)
        for filename in board_cyber_scenes.FILES.values():
            Image.new('RGB', (640, 480), (96, 70, 150)).save(Path(cls.directory.name) / filename)
        for each in (patch.object(board_cyber_scenes, 'ART', Path(cls.directory.name)),
                     patch('token_tv.board_arcade.local_stage.load', return_value=None),
                     patch('token_tv.board_beach.load', return_value=None),
                     patch('time.time', return_value=NOW)):
            each.start()
            cls.addClassCleanup(each.stop)
        board_cyber_scenes._cached_backdrop.cache_clear()
        cls.addClassCleanup(board_cyber_scenes._cached_backdrop.cache_clear)


@patch('time.time', return_value=NOW)
class WhenItLightsTests(unittest.TestCase):
    def test_amber_below_fifteen_and_red_below_five_by_the_figure_the_screens_show(self, _):
        for remaining, state in ((100, None), (50, None), (15, None), (14.6, None), (14.4, 'amber'), (14, 'amber'),
                                 (6, 'amber'), (5, 'amber'), (4.6, 'amber'), (4.4, 'red'), (4, 'red'), (.4, 'red'), (0, 'red'),
                                 (None, None)):
            self.assertEqual(low.level(remaining), state, remaining)

    def test_each_provider_has_its_own_line_and_claude_answers_to_the_lower_of_week_and_session(self, _):
        self.assertEqual(low.levels(reading()), {'codex': None, 'claude': None})
        self.assertEqual(low.levels(reading(codex_left=12)), {'codex': 'amber', 'claude': None})
        self.assertEqual(low.levels(reading(claude_left=3)), {'codex': None, 'claude': 'red'})
        self.assertEqual(low.levels(reading(codex_left=0, claude_left=14)), {'codex': 'red', 'claude': 'amber'})
        # the session stops work first: a healthy week with a nearly spent five hours is amber, or red below 5 %
        self.assertEqual(low.levels(reading(claude_left=60, five_left=9)), {'codex': None, 'claude': 'amber'})
        self.assertEqual(low.levels(reading(claude_left=60, five_left=2)), {'codex': None, 'claude': 'red'})
        self.assertEqual(low.levels(reading(claude_left=8, five_left=2)), {'codex': None, 'claude': 'red'})
        self.assertEqual(low.levels(reading(claude_left=3, five_left=90)), {'codex': None, 'claude': 'red'})

    def test_an_unknown_reading_never_lights_it(self, _):
        self.assertEqual(low.levels({'accounts': {}}), {'codex': None, 'claude': None})
        self.assertEqual(low.levels(reading(codex_left=None, claude_left=None, five_left=None)), {'codex': None, 'claude': None})
        # a reader that failed, a different login, a blocked Codex: no windows, never a zero
        for status in ('auth_required', 'error', 'rate_limited'):
            data = reading(codex_left=1, claude_left=1, five_left=1)
            for row in data['accounts'].values():
                row['status'], row['windows'] = status, []
            self.assertEqual(low.levels(data), {'codex': None, 'claude': None}, status)
        # an expired five-hour window is unknown, not empty
        data = reading(claude_left=60, five_left=1)
        next(w for w in data['accounts']['claude']['windows'] if w['label'] == '5H')['resets_at'] = NOW - 1
        self.assertEqual(low.levels(data)['claude'], None)
        # a missing week does not hide a known, nearly spent session
        self.assertEqual(low.levels(reading(claude_left=None, five_left=3))['claude'], 'red')

    def test_an_aged_reading_still_lights_it_but_an_old_number_kept_for_display_does_not(self, _):
        data = reading(codex_left=12, claude_left=3)
        for row in data['accounts'].values():
            row['reading_aged'] = True            # 3 to 8 minutes old: the number stays on screen (plan 2026-11-03)
        self.assertEqual(low.levels(data), {'codex': 'amber', 'claude': 'red'})
        stale = reading(codex_left=12, claude_left=3)
        for row in stale['accounts'].values():
            row['status'] = 'stale'
        self.assertEqual(low.levels(stale), {'codex': None, 'claude': None})
        for row in stale['accounts'].values():
            row['reading_aged'] = True
        self.assertEqual(low.levels(stale), {'codex': 'amber', 'claude': 'red'})

    def test_the_line_sits_inside_the_picture_clear_of_the_corners_and_of_the_other_half(self, _):
        for name in PAGE_NAMES + ARCHIVED:
            codex, claude = expected(name, 'codex'), expected(name, 'claude')
            self.assertFalse(codex & claude, name)
            for x, y in codex | claude:
                self.assertTrue(0 <= x < 320 and 0 <= y < 240, name)
            self.assertTrue(all(x < 160 for x, _ in codex) and all(x >= 160 for x, _ in claude), name)
            self.assertGreaterEqual(min(x for x, _ in codex | claude), 8, name)         # the Token Run tube has rounded corners
            self.assertLessEqual(max(x for x, _ in codex | claude), 311, name)
            self.assertEqual(len({y for _, y in codex}), 2, name)                         # two rows: one pixel lines shimmer here
        self.assertEqual({y for x, y in expected('countdown', 'codex')}, {0, 1})
        self.assertEqual({y for x, y in expected('arcade', 'codex')}, {16, 17})           # VERSUS spends its top rows on the score


class OnThePagesTests(Quiet):
    def eight(self, data, **options):
        return render_board_pages(data, anim=True, anim_frames=8, **options)

    def test_nothing_low_nothing_drawn_every_page_and_every_archived_version_is_byte_identical(self):
        quiet = reading()
        with patch.object(low, 'apply_low_quota', lambda images, names, snapshot: images), \
                patch.object(low, 'apply_one', lambda image, name, snapshot: image):
            baseline_pages = self.eight(quiet)
            baseline_library = {scene: render_archive(scene, quiet, animated=True) for scene in ARCHIVED}
        self.assertEqual(self.eight(quiet), baseline_pages)
        for scene in ARCHIVED:
            image, payload = render_archive(scene, quiet, animated=True)
            self.assertEqual((image.tobytes(), payload), (baseline_library[scene][0].tobytes(), baseline_library[scene][1]), scene)

    def test_low_quota_changes_only_the_providers_own_line_on_every_page_and_version(self):
        for label, data, lit in (('codex', reading(codex_left=12), {'codex': AMBER}),
                                 ('claude', reading(claude_left=3), {'claude': RED}),
                                 ('session', reading(claude_left=60, five_left=9), {'claude': AMBER}),
                                 ('both', reading(codex_left=0, claude_left=14), {'codex': RED, 'claude': AMBER})):
            with patch.object(low, 'apply_low_quota', lambda images, names, snapshot: images), \
                    patch.object(low, 'apply_one', lambda image, name, snapshot: image):
                plain_pages = self.eight(data)
                plain_library = {scene: render_archive(scene, data)[0] for scene in ARCHIVED} if label == 'both' else {}
            pages = self.eight(data)
            for name, before, after in zip(PAGE_NAMES, plain_pages, pages):
                a, b = words(before), words(after)
                changed = {(i % 320, i // 320) for i in range(76800) if a[i] != b[i]}
                allowed = set().union(*(expected(name, p) for p in lit))
                self.assertTrue(changed and changed <= allowed, (label, name, sorted(changed - allowed)[:5]))
                for provider, colour in lit.items():
                    own = expected(name, provider)
                    self.assertTrue(all(b[y * 320 + x] == word(colour) for x, y in own), (label, name, provider))
                self.assertEqual(before[BASE:], after[BASE:], (label, name))             # the animation trailer is untouched
            for scene, plain in plain_library.items():
                image = render_archive(scene, data)[0]
                changed = {(x, y) for y in range(240) for x in range(320) if image.getpixel((x, y)) != plain.getpixel((x, y))}
                allowed = set().union(*(expected(scene, p) for p in lit))
                self.assertTrue(changed and changed <= allowed, (label, scene, sorted(changed - allowed)[:5]))
                for provider, colour in lit.items():
                    self.assertTrue(all(image.getpixel(xy) == colour for xy in expected(scene, provider)), (label, scene))

    def test_the_library_previews_carry_the_sign_too(self):
        from io import BytesIO
        from token_tv.board_control import BoardControl
        data = reading(codex_left=12, claude_left=3)
        for scene in ('deep-space', 'countdown', 'neon-district'):
            png = BoardControl(None).archive_preview(scene, data)
            image = Image.open(BytesIO(png)).convert('RGB')
            row, left, right = low.line(scene, 'claude')
            self.assertEqual(image.getpixel(((left + right) // 2, row)), word_to_rgb(word(RED)), scene)
            row, left, right = low.line(scene, 'codex')
            self.assertEqual(image.getpixel(((left + right) // 2, row)), word_to_rgb(word(AMBER)), scene)

    def test_the_scrolling_platform_page_carries_the_line_in_its_overlay_not_on_the_still(self):
        data = reading(codex_left=12, claude_left=3)
        untouched = Image.new('RGB', (320, 240), (10, 20, 30)).tobytes()

        def cockpit(version):
            with patch('token_tv.board_platform.render_platform',
                       return_value=(Image.new('RGB', (320, 240), (10, 20, 30)), bytes([version]) + bytes(30))), \
                    patch('token_tv.board_pages.rgb565_frame', side_effect=lambda image, **kw: image.tobytes()):
                return render_board_pages(data, anim=True, scroll=4)[PAGE_NAMES.index('cockpit')]
        self.assertEqual(cockpit(4), untouched)          # not drawn on the still: the full-screen overlay owns it
        self.assertNotEqual(cockpit(3), untouched)       # the older versions keep their HUD on the still, so it is drawn there
        self.assertNotEqual(cockpit(2), untouched)

    def test_the_beach_film_never_repaints_the_line_while_the_water_moves(self):
        from token_tv import board_beach, board_wave
        from tests.test_board_beach import fictional_art
        data = reading(codex_left=12, claude_left=3)
        with patch('token_tv.board_beach.load', return_value=fictional_art()):
            frame = render_board_pages(data, anim=True, waves=3)[PAGE_NAMES.index('paradise')]
        self.assertEqual(frame[BASE:BASE + 4], b'WAVE')
        spec = board_wave.decode(frame[BASE + 8:])
        background = words(frame)
        for provider, colour in (('codex', AMBER), ('claude', RED)):
            self.assertTrue(all(background[y * 320 + x] == word(colour) for x, y in expected('paradise', provider)))
        for step in (0, 9, 24, 40, 63):
            moving = board_beach.render_words(background, spec, step)
            self.assertEqual(moving[:board_beach.TOP * 320], list(background[:board_beach.TOP * 320]), step)   # sky and HUD stand still

    def test_the_real_scrolling_overlay_keeps_the_line_on_every_tick_when_the_private_art_is_installed(self):
        from token_tv import board_scroll
        try:
            board_scroll.encode(3)
        except (OSError, ValueError):
            self.skipTest('the private platform art is not installed here')
        data = reading(codex_left=12, claude_left=3)
        with patch.object(low, 'apply_low_quota', lambda images, names, snapshot: images), \
                patch.object(low, 'apply_one', lambda image, name, snapshot: image):
            plain = render_board_pages(data, anim=True, scroll=4)[PAGE_NAMES.index('cockpit')]
        frame = render_board_pages(data, anim=True, scroll=4)[PAGE_NAMES.index('cockpit')]
        self.assertEqual(frame[BASE:BASE + 4], b'SCRO')
        spec = board_scroll.decode(frame[BASE + 8:])
        self.assertEqual(spec['version'], 4)
        background = words(frame)
        plain_spec = board_scroll.decode(plain[BASE + 8:])
        for tick in (0, 37, 150, 311):
            lit, quiet = board_scroll.render_words(background, spec, tick), board_scroll.render_words(words(plain), plain_spec, tick)
            for provider, colour in (('codex', AMBER), ('claude', RED)):
                own = expected('cockpit', provider)
                got = sum(lit[y * 320 + x] == word(colour) for x, y in own)
                self.assertGreaterEqual(got, .95 * len(own), (tick, provider))          # the 6-bit overlay palette may bend a pixel
                self.assertEqual(sum(quiet[y * 320 + x] == word(colour) for x, y in own), 0, (tick, provider))

    def test_versus_keeps_its_danger_and_the_dials_their_red_ring_the_line_never_covers_them(self):
        # VERSUS' DANGER label and red life bars, TOKEN RUN's red outer ring: every pixel of them is exactly where it was,
        # because the only pixels that change are the line's own rows (the bars' upper edge, and the sky above the dials).
        data = reading(codex_left=12, claude_left=3)
        with patch.object(low, 'apply_low_quota', lambda images, names, snapshot: images):
            plain = self.eight(data)
        lined = self.eight(data)
        for name, rows in (('arcade', (16, 17)), ('dials', (0, 1))):
            i = PAGE_NAMES.index(name)
            a, b = words(plain[i]), words(lined[i])
            self.assertEqual([k for k in range(76800) if a[k] != b[k] and k // 320 not in rows], [], name)
        from token_tv.board_arcade import HEALTH_RED
        arcade = words(lined[PAGE_NAMES.index('arcade')])
        for colour in (HEALTH_RED['mid'], ):
            rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))
            self.assertGreater(sum(arcade[y * 320 + x] == word(rgb) for y in range(20, 32) for x in range(8, 320)), 100)
        from token_tv.board_dials import RADIUS, CENTRES
        ring = lined[PAGE_NAMES.index('dials')]
        image = Image.frombytes('RGB', (320, 240), ring[8:BASE], 'raw', 'BGR;16')
        for provider, (cx, cy) in CENTRES.items():
            reach = int(RADIUS) + 1                              # a nearly empty week lights one or two red blocks of the ring
            red = sum(1 for y in range(2 * (cy - reach), min(240, 2 * (cy + reach)))
                      for x in range(max(0, 2 * (cx - reach)), min(320, 2 * (cx + reach)))
                      if image.getpixel((x, y))[0] > 180 and image.getpixel((x, y))[1] < 90 and image.getpixel((x, y))[2] < 90)
            self.assertGreater(red, 6, provider)

    def test_the_sign_never_disturbs_the_animation_boxes_or_the_first_pose(self):
        data = reading(codex_left=12, claude_left=3)

        def first_pose(frame):
            """What the board shows at step zero: the stored page with each sprite's first pose over it."""
            spec = board_anim.decode(frame[BASE + 8:])
            composed = list(words(frame))
            for sprite in spec['sprites']:
                step, dx, dy = sprite['script'][0]
                for index, colour in enumerate(sprite['frames'][step]):
                    if colour == board_anim.KEY:
                        continue
                    x, y = sprite['x'] + dx + index % sprite['w'] * 2, sprite['y'] + dy + index // sprite['w'] * 2
                    for yy in (y, y + 1):
                        for xx in (x, x + 1):
                            if 0 <= xx < 320 and 0 <= yy < 240:
                                composed[yy * 320 + xx] = colour
            return spec, composed

        with patch.object(low, 'apply_low_quota', lambda images, names, snapshot: images):
            plain_moving, plain_still = self.eight(data), render_board_pages(data, anim=False)
        moving, still = self.eight(data), render_board_pages(data, anim=False)
        for name, before, after, quiet_still, static in zip(PAGE_NAMES, plain_moving, moving, plain_still, still):
            if after[BASE:BASE + 4] != b'ANIM':
                continue
            spec, composed = first_pose(after)
            _, plain_composed = first_pose(before)
            line_pixels = expected(name, 'codex') | expected(name, 'claude')
            for sprite in spec['sprites']:
                for _, dx, dy in sprite['script']:
                    x0, y0 = sprite['x'] + dx, sprite['y'] + dy
                    touching = {(x, y) for x, y in line_pixels if x0 <= x < x0 + 2 * sprite['w'] and y0 <= y < y0 + 2 * sprite['h']}
                    if name != 'countdown':           # the gull and the flock fly in over the top edge by design
                        self.assertFalse(touching, (name, sprite['x'], sprite['y']))
            # the first pose composed from the stored page equals the static page, line included: the sign adds no difference
            differs = lambda a, b: {i for i in range(76800) if a[i] != b[i]}
            self.assertEqual(differs(composed, words(static)), differs(plain_composed, words(quiet_still)), name)
            stored = words(after)
            for provider, colour in (('codex', AMBER), ('claude', RED)):          # the stored page, which the sprites restore from
                self.assertTrue(all(stored[y * 320 + x] == word(colour) for x, y in expected(name, provider)), (name, provider))
            if name != 'countdown':
                self.assertTrue(all(composed[y * 320 + x] == word(AMBER if x < 160 else RED) for x, y in line_pixels), name)


def word_to_rgb(value):
    """What a preview shows for an RGB565 word: the decoder the control room uses."""
    return Image.frombytes('RGB', (1, 1), struct.pack('<H', value), 'raw', 'BGR;16').getpixel((0, 0))


if __name__ == '__main__':
    unittest.main()
