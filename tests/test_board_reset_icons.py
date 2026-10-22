"""Each board page counts its saved resets with an icon of its own (the user, 2026-10-20), with the hearts' meaning."""
import unittest
from unittest.mock import patch

from token_tv import board_reset_icons as icons
from token_tv.board_arcade import render_arcade
from token_tv.board_art import render_cockpit, render_countdown
from token_tv.board_dials import render_dials
from token_tv.board_forge import render_forge
from token_tv.board_paradise import render_paradise
from token_tv.board_surf import render_surf
from token_tv.sample import snapshot

NOW = 1_800_000_000
PAGES = {'paradise': render_paradise, 'code-forge': render_forge, 'surf': render_surf, 'dials': render_dials,
         'cockpit': render_cockpit, 'countdown': render_countdown}


def case(hearts=2, last_known=None):
    data = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', 27, 6 * 86400 + 8 * 3600)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', 27, 5 * 86400 + 16 * 3600), ('5H', 41, 7200)])])
    for provider in ('codex', 'claude'):
        data['accounts'][provider]['banked_resets'] = (
            {'available': hearts, 'confirmed_at': NOW, 'source': 'manual'} if hearts is not None or last_known is None
            else {'available': None, 'last_known': last_known})
    return data


def draw(render, data):
    with patch('time.time', return_value=NOW):
        image = render(data)
    return (image[0] if isinstance(image, tuple) else image).convert('RGB')


class ResetIconTests(unittest.TestCase):
    def test_every_pixel_icon_is_a_clean_grid_with_a_body_and_a_silhouette(self):
        self.assertEqual(set(icons.ICONS), set(icons.DETAIL))
        for name, rows in icons.ICONS.items():
            self.assertEqual(len({len(r) for r in rows}), 1, name)
            self.assertTrue(set(''.join(rows)) <= set('#o.'), name)
            self.assertLessEqual(icons.size(name)[0], 10, name)
            cells = list(icons.cells(name))
            self.assertTrue(cells and any(edge for *_, edge in cells), name)
            self.assertEqual(len(cells), sum(c != '.' for r in rows for c in r), name)

    def test_a_reset_that_is_not_available_is_a_faint_version_of_the_same_icon(self):
        for name in icons.ICONS:
            solid = {(x, y) for x, y, *_ in icons.cells(name)}
            faint = set(icons.hollow(name))
            self.assertTrue(faint and faint <= solid, name)
            self.assertLess(len(faint), len(solid), name)                          # never as solid as an available one
        self.assertTrue(all(any(x == 0 for x, _ in icons.hollow('flag')) for _ in (0,)))   # the flag keeps its pole, not a letter P

    def test_unknown_and_old_write_no_text_and_get_one_dot_after_the_icons_while_more_than_three_gets_a_plus(self):
        self.assertTrue(icons.marked(None, False) and icons.marked(None, True) and icons.marked(2, True) and icons.marked(0, True))
        self.assertFalse(icons.marked(0, False) or icons.marked(3, False))              # zero is three faint icons and no dot
        self.assertEqual([icons.mark(None, False), icons.mark(None, True), icons.mark(2, True), icons.mark(0, False)], [''] * 4)
        self.assertEqual([icons.mark(4, False), icons.mark(5, True)], ['+', '+'])

    def test_each_page_shows_one_more_icon_per_saved_reset_and_marks_unknown_and_old_with_a_dot_not_text(self):
        for name, render in PAGES.items():
            images = [draw(render, case(h)).tobytes() for h in (0, 1, 2, 3)]
            self.assertEqual(len(set(images)), 4, name)                      # none, one, two, three icons all differ
            self.assertNotEqual(draw(render, case(4)).tobytes(), images[3], name)          # more than three: a plus
            unknown = draw(render, case(None)).tobytes()
            old = draw(render, case(None, last_known=2)).tobytes()
            self.assertNotEqual(unknown, images[0], name)                    # unknown is not zero: the dot at the end of the row
            self.assertNotEqual(old, unknown, name)                          # an old count keeps its icons, unknown shows them faint
            self.assertNotEqual(old, draw(render, case(2)).tobytes(), name)  # and the dot tells it is not a fresh count

    def test_the_dot_is_the_only_difference_between_zero_and_unknown(self):
        for name, render in PAGES.items():
            zero, unknown = draw(render, case(0)), draw(render, case(None))
            changed = [(x, y) for y in range(240) for x in range(320) if zero.getpixel((x, y)) != unknown.getpixel((x, y))]
            self.assertTrue(changed, name)
            self.assertLessEqual(len(changed), 120, name)                    # two tiny dots (one per provider), no text and no icons

    def test_the_icons_are_not_the_old_hearts(self):
        heart = ('.##.##.', '#######', '#######', '.#####.', '..###..', '...#...')
        for name, rows in icons.ICONS.items():
            self.assertNotEqual(rows, heart, name)

    def test_versus_and_game_boy_keep_what_they_had(self):
        from token_tv.personal_faces import RENDERERS
        game_boy = RENDERERS['game-boy']
        with patch('time.time', return_value=NOW):
            two, three = game_boy(case(2), screen=(320, 240)), game_boy(case(3), screen=(320, 240))
        self.assertNotEqual(two.tobytes(), three.tobytes())                          # the Game Boy still counts with its hearts
        self.assertNotEqual(draw(render_arcade, case(2)).tobytes(), draw(render_arcade, case(3)).tobytes())   # VERSUS: reserve bars
        for render in (render_arcade,):
            self.assertNotEqual(draw(render, case(None)).tobytes(), draw(render, case(0)).tobytes())     # a dot there too


if __name__ == '__main__':
    unittest.main()
