"""TOKEN RUN: the road animates, the dials, numbers and scoreboard never do, and unrelated pages stay untouched."""
import math
import struct
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

from token_tv import board_anim, board_drive
from token_tv.board import MAX_PAGE_BYTES
from token_tv import board_dials
from token_tv.board_dials import CENTRES, RADIUS, render_dials
from token_tv.board_pages import PAGE_NAMES, frame_size, render_board_pages, rgb565_frame
from token_tv.sample import snapshot

NOW = 2000000000


def sample(used=27, session=True):
    data = snapshot(now=NOW, sample=[
        ('codex', 'CODEX', 'codex', [('WEEK', used, 6 * 86400 + 8 * 3600)]),
        ('claude', 'CLAUDE', 'claude', [('WEEK', used, 5 * 86400 + 16 * 3600)] +
         ([('5H', 41, 7200)] if session else []))])
    for provider in ('codex', 'claude'):
        data['accounts'][provider]['banked_resets'] = {'available': 2, 'confirmed_at': NOW, 'source': 'manual'}
    return data


def compose(background, spec, step):
    """Independent reference compositor in screen pixels, after RGB565 conversion."""
    words = list(struct.unpack('<76800H', rgb565_frame(background)[8:]))
    for sprite in spec['sprites']:
        frame, dx, dy = sprite['script'][step % len(sprite['script'])]
        for index, word in enumerate(sprite['frames'][frame]):
            if word == board_anim.KEY:
                continue
            x = sprite['x'] + dx + index % sprite['w'] * 2
            y = sprite['y'] + dy + index // sprite['w'] * 2
            for yy in (y, y + 1):
                for xx in (x, x + 1):
                    words[yy * 320 + xx] = word
    return words


class DrivingSceneTests(unittest.TestCase):
    def test_the_sea_continues_below_the_road_horizon_instead_of_floating_above_it(self):
        # The old bay ended at the vanishing point and became sand underneath,
        # so it looked like a shelf of water in the sky. The coast must reach
        # toward the viewer, visibly beside the road, before the left dial.
        image = board_drive.scene(0)
        pixels = [image.getpixel((x, y)) for y in range(board_drive.HORIZON + 2, board_drive.HORIZON + 12)
                  for x in range(3, 37)]
        water = sum(g > r * 1.35 and b > r * 1.25 for r, g, b in pixels)
        self.assertGreater(water, len(pixels) * .5)

    def test_first_pose_matches_static_fallback_and_payload_is_stable_without_account_activity(self):
        with patch('time.time', return_value=NOW):
            data = sample()
            static = render_dials(data)
            background, payload = render_dials(data, animated=True)
            spec = board_anim.decode(payload)
            self.assertEqual(struct.pack('<76800H', *compose(background, spec, 0)), rgb565_frame(static)[8:])
            phases = [compose(background, spec, step) for step in range(4)]
            self.assertEqual(len({struct.pack('<76800H', *phase) for phase in phases}), 4)
            # Animation is a stored script, not a stream of time-dependent uploads from the PC.
            with patch('time.time', return_value=NOW + 1):
                self.assertEqual(render_dials(data, animated=True)[1], payload)
            frame = rgb565_frame(background, anim=payload)
            self.assertEqual(frame_size(frame), (320, 240))
            self.assertLessEqual(len(frame), MAX_PAGE_BYTES)
            self.assertLess(len(payload), board_anim.MAX_PAYLOAD)
            self.assertTrue(all(sprite['w'] <= 96 and sprite['h'] <= 96 for sprite in spec['sprites']))

    def test_all_poses_preserve_the_dials_numbers_session_rings_and_scoreboard(self):
        cases = [sample(0), sample(100), sample(session=False), {'accounts': {}}]
        with patch('time.time', return_value=NOW):
            backgrounds = [render_dials(data, animated=True)[0] for data in cases]
        # Find actual reading pixels by changing quota/session/heart data, independently of the scene mask.
        pixels = [image.tobytes() for image in backgrounds]
        readings = {i // 3 for i, value in enumerate(pixels[0])
                    if any(row[i] != value for row in pixels[1:])}
        self.assertGreater(len(readings), 1000)
        for data in cases:
            with self.subTest(known=bool(data['accounts'])), patch('time.time', return_value=NOW):
                background, payload = render_dials(data, animated=True)
                spec = board_anim.decode(payload)
                self.assertEqual(len(spec['sprites']), 4)
                for number, sprite in enumerate(spec['sprites']):
                    for step in range(len(sprite['script'])):
                        index, dx, dy = sprite['script'][step]
                        for i, word in enumerate(sprite['frames'][index]):
                            if word == board_anim.KEY:
                                continue
                            x = sprite['x'] + dx + i % sprite['w'] * 2
                            y = sprite['y'] + dy + i // sprite['w'] * 2
                            for p in ((x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)):
                                self.assertTrue(0 <= p[0] < 320 and (number or 2 * board_drive.WINDOW[1] <= p[1] < 240))
                                # the dial is the whole disc, rim included, on the 160x120 grid
                                self.assertTrue(all(math.dist((p[0] // 2, p[1] // 2), centre) > RADIUS
                                                    for centre in CENTRES.values()))
                                self.assertNotIn(p[1] * 320 + p[0], readings)

    def test_only_the_road_window_changes_between_poses_and_the_loop_closes(self):
        x0, y0, x1, y1 = board_drive.WINDOW
        first = board_drive.scene(0).convert('RGB')
        for phase in range(1, board_drive.PHASES):
            diff = ImageChops.difference(first, board_drive.scene(phase).convert('RGB'))
            box = diff.getbbox()
            self.assertIsNotNone(box, phase)
            self.assertGreaterEqual(box[1], y0, 'the far strip above the window must be identical in every pose')
            # Outside the window nothing may differ except what a dial covers anyway (the sprite never reaches it).
            for y in range(board_drive.H):
                for x in range(board_drive.W):
                    if x0 <= x < x1 and y0 <= y < y1:
                        continue
                    if any(math.hypot(x - cx, y - cy) <= RADIUS for cx, cy in CENTRES.values()):
                        continue
                    self.assertEqual(diff.getpixel((x, y)), (0, 0, 0), (phase, x, y))
        # After the last pose the first one returns exactly: the stored loop has no jump.
        self.assertEqual(board_drive.scene(board_drive.PHASES).tobytes(), first.tobytes())

    def test_the_painted_page_is_hard_2x2_pixels_with_a_crt_look(self):
        with patch('time.time', return_value=NOW):
            image = render_dials(sample())
        self.assertEqual(image.size, (320, 240))
        for y in range(0, 240, 2):
            for x in range(0, 320, 2):
                block = {image.getpixel((x, y)), image.getpixel((x + 1, y)),
                         image.getpixel((x, y + 1)), image.getpixel((x + 1, y + 1))}
                self.assertEqual(len(block), 1, (x, y))
        # Test the CRT on a flat field: scenery can now contain water, palms or
        # boats here. Horizontal shading must stay subtle, without a column grid.
        flat = board_dials._crt(Image.new('RGB', (160, 120), '#ecd08a')).resize((320, 240), Image.Resampling.NEAREST)
        def average(rows, columns):
            return sum(sum(flat.getpixel((x, y))) / 3 for y in rows for x in columns) / (len(rows) * len(columns))
        bright, dark = average(range(104, 116, 4), range(8, 40, 2)), average(range(106, 118, 4), range(8, 40, 2))
        self.assertLess(dark, bright * 0.95)
        self.assertGreater(dark, bright * 0.80)
        columns = [average(range(104, 116, 2), range(x, x + 1)) for x in range(8, 40, 2)]
        self.assertLess(max(columns) / min(columns), 1.08)
        self.assertEqual(image.getpixel((0, 0)), board_dials.BEZEL)                  # rounded screen corner
        self.assertEqual(image.getpixel((319, 239)), board_dials.BEZEL)

    def test_the_slow_sky_things_move_a_little_inside_their_own_boxes(self):
        with patch('time.time', return_value=NOW):
            background, payload = render_dials(sample(), animated=True)
            static = render_dials(sample())
        spec = board_anim.decode(payload)
        sprites = spec['sprites']
        boxes = []
        for number, sprite in enumerate(sprites):
            xs = [dx for _, dx, _ in sprite['script']]
            ys = [dy for _, _, dy in sprite['script']]
            boxes.append((sprite['x'] + min(xs), sprite['y'] + min(ys),
                          sprite['x'] + sprite['w'] * 2 + max(xs), sprite['y'] + sprite['h'] * 2 + max(ys)))
            self.assertEqual(sprite['step_ms'], sprites[0]['step_ms'])            # one clock for all of them
            self.assertEqual(sprite['script'][0][1:], (0, 0))                     # the static picture is step zero
            if number:
                self.assertGreaterEqual(boxes[-1][1], 36, 'the scoreboard strip must stay free')
                self.assertGreaterEqual(len({offset[1:] for offset in sprite['script']}), 3, 'it should really move')
                self.assertLessEqual(max(abs(v) for v in xs + ys), 16, 'only a little')
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b))
        # The stored picture has none of the sky things (they would be left behind as ghosts); a board that cannot
        # animate gets them in the first pose.
        changed = ImageChops.difference(background, static).getbbox()
        self.assertIsNotNone(changed)
        for y in range(240):
            for x in range(320):
                if background.getpixel((x, y)) != static.getpixel((x, y)):
                    self.assertTrue(any(box[0] <= x < box[2] and box[1] <= y < box[3] for box in boxes[1:]), (x, y))

    def test_the_weekly_ring_changes_colour_with_where_the_blocks_sit_red_amber_green(self):
        def block_colours(data, provider):
            with patch('time.time', return_value=NOW):
                image = render_dials(data)
            cx, cy = CENTRES[provider]
            found = []
            for k in range(board_dials.BLOCKS):
                angle = math.radians(board_dials.START + board_dials.SWEEP * (k + .5) / board_dials.BLOCKS)
                x, y = round(cx + math.cos(angle) * 19.5), round(cy + math.sin(angle) * 19.5)
                found.append(image.getpixel((x * 2, y * 2)))
            return found

        def kind(pixel):
            r, g, b = pixel
            if r > 140 and g < 110:
                return 'red'
            if r > 150 and 110 <= g < 210 and b < 110:
                return 'amber'
            if g > 130 and r < 150 and b < 140:
                return 'green'
            if r > 150 and g > 120 and b > 110 and max(pixel) - min(pixel) < 90:
                return 'pale'
            return 'dark'
        for provider in ('codex', 'claude'):
            # Hardly anything left: the single lit block is a plain red, not a pale one.
            self.assertEqual(kind(block_colours(sample(used=95), provider)[0]), 'red', provider)
            # Little left: only red blocks are lit (the last one paler), the rest of the ring is dark.
            lows = [kind(p) for p in block_colours(sample(used=82), provider)]
            self.assertEqual(lows[:3], ['red'] * 3, provider)
            self.assertNotIn('amber', lows)
            self.assertNotIn('green', lows)
            # The empty part of the ring stays quiet: far darker than any lit block, so the level reads at a glance.
            colours = block_colours(sample(used=82), provider)
            brightest_empty = max(sum(p) / 3 for p in colours[5:])
            dimmest_lit = min(sum(p) / 3 for p in colours[:3])
            self.assertLess(brightest_empty, 45)
            self.assertGreater(dimmest_lit, 2.5 * brightest_empty)
            # A middling quota reaches amber but not green; a lot reaches green.
            mid = [kind(p) for p in block_colours(sample(used=62), provider)]      # 38 % left: 8 blocks
            self.assertEqual(mid[:4], ['red'] * 4)
            self.assertIn('amber', mid)
            self.assertNotIn('green', mid)
            high = [kind(p) for p in block_colours(sample(used=14), provider)]      # 86 % left: 17 blocks
            self.assertEqual(high[:4], ['red'] * 4)
            self.assertEqual(set(high[4:9]), {'amber'})
            self.assertEqual(set(high[10:16]), {'green'})
            # Unknown lights no block at all, and no traffic-light colour appears.
            unknown = [kind(p) for p in block_colours({'accounts': {}}, provider)]
            self.assertEqual(set(unknown), {'dark'})

    def test_unknown_readings_change_only_the_scoreboard_and_the_dials(self):
        with patch('time.time', return_value=NOW):
            known = render_dials(sample())
            unknown = render_dials({'accounts': {}})
        self.assertIsNotNone(ImageChops.difference(known, unknown).getbbox())
        # The two renders differ only in the scoreboard strip and inside the dials, never in the road scenery.
        for y in range(40, 240):
            for x in range(0, 320):
                if known.getpixel((x, y)) != unknown.getpixel((x, y)):
                    self.assertTrue(any(math.hypot(x // 2 - cx, y // 2 - cy) <= RADIUS for cx, cy in CENTRES.values()),
                                    (x, y))

    def test_board_only_adds_driving_animation_to_the_requested_cockpit(self):
        with patch('time.time', return_value=NOW):
            data = sample()
            static = render_board_pages(data, stars=True)
            moving = render_board_pages(data, stars=True, anim=True)
            for name, before, after in zip(PAGE_NAMES, static, moving):
                if name not in ('dials', 'arcade', 'code-forge', 'surf', 'paradise', 'countdown'):
                    self.assertEqual(before, after, name)
            at = 8 + 320 * 240 * 2
            self.assertEqual(moving[PAGE_NAMES.index('dials')][at:at + 4], b'ANIM')


if __name__ == '__main__':
    unittest.main()
