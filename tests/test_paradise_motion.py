"""Visibility and continuity checks for the locally prepared beach motion."""

import unittest

from PIL import Image, ImageDraw

from tools.refine_paradise_film import returning_water, swaying_boat


class ParadiseMotionTests(unittest.TestCase):
    def test_shore_returns_while_the_open_sea_keeps_advancing(self):
        film = Image.new('RGB', (160, 54 * 8))
        for phase in range(8):
            ImageDraw.Draw(film).rectangle((0, phase * 54, 159, phase * 54 + 53),
                                          fill=(80 + phase * 20, 128, 128))
        film = film.quantize(colors=256, dither=Image.Dither.NONE)
        out = returning_water(film).convert('RGB')
        near = [out.getpixel((45, 24 + 54 * phase))[0] for phase in range(8)]
        far = [out.getpixel((145, 24 + 54 * phase))[0] for phase in range(8)]
        self.assertEqual(near[1], near[7])
        self.assertEqual(near[2], near[6])
        self.assertEqual(near[3], near[5])
        self.assertLess(near[0], near[1])
        self.assertLess(near[1], near[2])
        self.assertLess(near[2], near[3])
        self.assertLess(near[3], near[4])
        self.assertEqual(far, sorted(far))
        self.assertGreater(far[7], far[4])

    def test_sailboat_has_a_visible_two_sided_sway_with_fixed_edges(self):
        photo = Image.new('RGB', (320, 240), (80, 150, 210))
        draw = ImageDraw.Draw(photo)
        draw.polygon(((217, 78), (204, 123), (231, 123)), fill=(240, 235, 215))
        draw.line(((217, 78), (217, 124)), fill=(15, 20, 25), width=2)
        boat = swaying_boat(photo).convert('RGB')

        def reconstructed(phase, x, y):
            base = photo.getpixel((199 + x, 76 + y))
            zero = boat.getpixel((x, y))
            delta = boat.getpixel((x, y + phase * 56))
            return tuple(max(0, min(255, base[c] + delta[c] - zero[c])) for c in range(3))

        y = 14  # 90 px: near the masthead, where sway is most visible
        right = [sum(reconstructed(1, x, y)) for x in range(10, 30)]
        left = [sum(reconstructed(3, x, y)) for x in range(10, 30)]
        self.assertGreater(right.index(min(right)) - left.index(min(left)), 5)
        self.assertEqual(reconstructed(1, 0, 20), reconstructed(0, 0, 20))
        self.assertEqual(reconstructed(3, 39, 20), reconstructed(0, 39, 20))
        self.assertEqual(boat.crop((0, 0, 40, 56)).tobytes(),
                         boat.crop((0, 2 * 56, 40, 3 * 56)).tobytes())


if __name__ == '__main__':
    unittest.main()
