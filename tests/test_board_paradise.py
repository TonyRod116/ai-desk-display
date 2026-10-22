"""A calm tropical lagoon carries fresh readings and moves only decorative areas."""

import copy
import struct
import unittest
from unittest.mock import patch

from PIL import Image, ImageColor

from token_tv import board_anim
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_pages import (
    FACES,
    PAGE_NAMES,
    frame_size,
    render_board_pages,
    rgb565_frame,
)
from tests.test_board_forge import NOW, compose, sample


class ParadiseTests(unittest.TestCase):
    def test_paradise_replaces_only_pocket_on_the_board_and_keeps_the_album(self):
        from token_tv.board_paradise import render_paradise

        self.assertEqual(
            PAGE_NAMES,
            (
                "game-boy",
                "paradise",
                "code-forge",
                "surf",
                "dials",
                "arcade",
                "cockpit",
                "countdown",
            ),
        )
        self.assertIn("game-boy-pocket", FACES)
        with patch("time.time", return_value=NOW):
            background, payload = render_paradise(sample(), animated=True)
            pages = render_board_pages(sample(), stars=True, anim=True)
        self.assertEqual(len(pages), 8)
        self.assertEqual(pages[1], rgb565_frame(background, anim=payload))

    def test_calm_animation_fits_and_static_fallback_is_the_exact_first_pose(self):
        from token_tv.board_paradise import PALM_BOX, SURF_SCRIPT, render_paradise

        with patch("time.time", return_value=NOW):
            background, payload = render_paradise(sample(), animated=True)
            static = render_paradise(sample())
            later_payload = render_paradise(sample(), animated=True)[1]
        spec = board_anim.decode(payload)
        self.assertEqual(payload, later_payload)
        self.assertEqual(frame_size(rgb565_frame(background, anim=payload)), (320, 240))
        self.assertLessEqual(len(payload), 27000)
        self.assertLessEqual(
            len(rgb565_frame(background, anim=payload)), MAX_PAGE_BYTES
        )
        self.assertEqual(
            struct.pack("<76800H", *compose(background, spec, 0)),
            rgb565_frame(static)[8:],
        )
        self.assertFalse(spec["stars"])
        self.assertIsNone(spec["meteor"])
        for sprite in spec["sprites"]:
            self.assertGreaterEqual(sprite["step_ms"], 180)  # moving water, no flashes
        for step in range(max(len(s["script"]) for s in spec["sprites"])):
            boxes = []
            for sprite in spec["sprites"]:
                _, dx, dy = sprite["script"][step % len(sprite["script"])]
                x, y = sprite["x"] + dx, sprite["y"] + dy
                box = (x, y, x + 2 * sprite["w"], y + 2 * sprite["h"])
                self.assertTrue(0 <= box[0] < box[2] <= 188)
                self.assertTrue(30 <= box[1] < box[3] <= 240)
                boxes.append(box)
            for index, first in enumerate(boxes):
                for second in boxes[index + 1 :]:
                    self.assertTrue(
                        first[2] <= second[0]
                        or second[2] <= first[0]
                        or first[3] <= second[1]
                        or second[3] <= first[1]
                    )
        poses = [compose(background, spec, step) for step in range(len(SURF_SCRIPT))]

        def region(words, box):
            x0, y0, x1, y1 = box
            return tuple(
                v for y in range(y0, y1) for v in words[y * 320 + x0 : y * 320 + x1]
            )

        for box in ((40, 160, 186, 236), PALM_BOX):
            self.assertGreaterEqual(len({region(p, box) for p in poses}), 3)
        # Ten distinct positions on arrival; retreat visits those same images.
        self.assertGreaterEqual(len({region(p, (40, 160, 186, 236)) for p in poses}), 10)
        self.assertEqual(len({region(p, (188, 30, 320, 240)) for p in poses}), 1)
        # The foam must actually travel: stronger contrast change along the
        # photographed shoreline than a barely perceptible sparkle in the sea.
        a, b = poses[0], poses[9]

        def channels(word):
            return word >> 11, (word >> 5) & 63, word & 31

        moved = sum(
            max(abs(u - v) for u, v in zip(channels(a[y * 320 + x]), channels(b[y * 320 + x]))) >= 3
            for y in range(164, 226) for x in range(76, 140)
        )
        self.assertGreater(moved, 600)
        # A wave must visibly enter previously dry sand, not just ripple where
        # there is already water. This patch lies inland of the original foam.
        inland = sum(
            max(abs(u - v) for u, v in zip(channels(a[y * 320 + x]), channels(b[y * 320 + x]))) >= 3
            for y in range(198, 226) for x in range(50, 72)
        )
        self.assertGreater(inland, 220)

        def shoreline_edge(words, y):
            def rgb(x):
                r, g, b = channels(words[y * 320 + x])
                return r * 255 // 31, g * 255 // 63, b * 255 // 31

            return max(
                (sum(abs(u - v) for u, v in zip(rgb(x), rgb(x + 2))), x)
                for x in range(45, 91)
            )[1]

        # Track the leading photographic foam at two foreground slices, rather
        # than equating changed pixels in the sea with a wave entering the beach.
        for y in (206, 220):
            self.assertGreaterEqual(shoreline_edge(a, y) - shoreline_edge(b, y), 18)
        self.assertEqual(len({region(p, (0, 180, 38, 236)) for p in poses}), 1)
        self.assertEqual(poses[1], poses[19])  # surf returns without drift
        self.assertEqual(poses[0], poses[-1])
        # The actual full restoration box fits the previously proven scratch
        # allocation too, not only the bitmap/payload budget.
        for sprite in spec["sprites"]:
            xs = [sprite["x"] + dx for _, dx, _ in sprite["script"]]
            ys = [sprite["y"] + dy for _, _, dy in sprite["script"]]
            area = (max(xs) - min(xs) + sprite["w"] * 2) * (max(ys) - min(ys) + sprite["h"] * 2)
            self.assertLessEqual(area, 11136)

    def test_unknown_old_reset_dates_and_session_are_not_decorative_readings(self):
        from token_tv.board_paradise import render_paradise

        zero, missing = sample(hearts=0), sample(hearts=None)
        previous = copy.deepcopy(missing)
        previous["accounts"]["claude"]["banked_resets"]["last_known"] = 1
        changed = copy.deepcopy(zero)
        changed["accounts"]["claude"]["windows"][0]["resets_at"] += 86400
        cases = [
            zero,
            sample(100),
            sample(session=False),
            missing,
            previous,
            sample(hearts=4),
            changed,
            {"accounts": {}},
        ]
        with patch("time.time", return_value=NOW):
            renders = [render_paradise(data, animated=True) for data in cases]
            without = render_paradise(sample(session=False))
            with_session = render_paradise(sample())
        self.assertTrue(all(p == renders[0][1] for _, p in renders))
        self.assertEqual(
            len({im.crop((188, 30, 320, 240)).tobytes() for im, _ in renders}),
            len(cases),
        )
        self.assertEqual(
            without.crop((188, 30, 320, 135)).tobytes(),
            with_session.crop((188, 30, 320, 135)).tobytes(),
        )
        self.assertNotEqual(
            without.crop((188, 135, 320, 240)).tobytes(),
            with_session.crop((188, 135, 320, 240)).tobytes(),
        )
        self.assertTrue(
            all(
                im.crop((0, 30, 184, 240)).tobytes()
                == renders[0][0].crop((0, 30, 184, 240)).tobytes()
                for im, _ in renders[1:]
            )
        )

    def test_weekly_bars_are_equal_and_much_larger_than_the_session(self):
        from token_tv.board_paradise import render_paradise

        full, empty = sample(0), sample(100)
        session_empty = copy.deepcopy(full)
        full["accounts"]["claude"]["windows"][1]["used_percent"] = 0
        session_empty["accounts"]["claude"]["windows"][1]["used_percent"] = 100
        # Compare bar geometry on the same underlay. The real photograph shows
        # through the panels, so its different colours must not affect this check.
        with patch("time.time", return_value=NOW), patch(
            "token_tv.board_paradise._landscape",
            return_value=Image.new("RGB", (320, 240), "#84b5ae"),
        ):
            a, b, c = (
                render_paradise(full),
                render_paradise(empty),
                render_paradise(session_empty),
            )

        def mask(first, second, box):
            x, y = first.crop(box), second.crop(box)
            return x.size, [p != q for p, q in zip(x.tobytes(), y.tobytes())]

        codex, claude, session = (
            (200, 93, 308, 103),
            (200, 193, 308, 203),
            (216, 207, 292, 210),
        )
        self.assertEqual(mask(a, b, codex), mask(a, b, claude))
        self.assertTrue(any(mask(a, b, codex)[1]))
        self.assertTrue(any(mask(a, c, session)[1]))
        self.assertGreaterEqual(mask(a, b, codex)[0][1], mask(a, c, session)[0][1] * 3)

    def test_photo_is_visible_through_panels_and_ink_has_enough_contrast(self):
        from token_tv.board_paradise import COLORS, GLASS, INK, MUTED, _landscape, render_paradise

        with patch("time.time", return_value=NOW):
            image = render_paradise(sample(), animated=True)[0]
        photo = _landscape()
        alpha = GLASS[3] / 255

        def glass(pixel):
            return tuple(round(pixel[k] * (1 - alpha) + GLASS[k] * alpha) for k in range(3))

        # These empty spaces lie between the titles and large numbers. Their
        # colours must come from the real photograph, rather than a flat panel.
        for y in (52, 152):
            for x in (206, 236, 276, 306):
                expected = glass(photo.getpixel((x, y)))
                actual = image.getpixel((x, y))
                self.assertLessEqual(max(abs(a - b) for a, b in zip(actual, expected)), 6)
                self.assertGreater(max(abs(a - b) for a, b in zip(actual, GLASS[:3])), 12)

        def panel_colour(rgb):
            word = board_anim.rgb565(rgb)
            return ((word >> 11) * 255 // 31, ((word >> 5) & 63) * 255 // 63, (word & 31) * 255 // 31)

        def luminance(rgb):
            values = [c / 255 for c in rgb]
            values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
            return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722)))

        for provider, y in (("codex", 37), ("claude", 137)):
            data = photo.crop((200, y + 6, 308, y + 85)).tobytes()
            inks = [luminance(panel_colour(ImageColor.getrgb(c))) for c in (COLORS[provider], INK, MUTED)]
            for at in range(0, len(data), 3):
                background = luminance(panel_colour(glass(data[at:at + 3])))
                for ink in inks:
                    low, high = sorted((ink, background))
                    self.assertGreaterEqual((high + 0.05) / (low + 0.05), 4.5)


if __name__ == "__main__":
    unittest.main()
