"""Tidal Rush: compact weekly panels, a leading surfer who climbs and drops along the wave, a lip that really falls and a moment of
action every few seconds (Tony, 2026-11-03). Surf stays decorative; the weekly instruments survive every animation step."""
import copy
import struct
import unittest
from unittest.mock import patch

from token_tv import board_anim
from token_tv import board_surf_rider as rider
from token_tv import board_surf_wave as wave
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_pages import PAGE_NAMES, render_board_pages, rgb565_frame
from token_tv.board_surf import CREST, FACE, LIP, PANEL_BOTTOM, PLAN, RIDER, STEP_MS, _scene, beach, render_surf
from test_board_forge import NOW, sample, compose

RIDER_SPRITE, FACE_SPRITE, CREST_SPRITE, LIP_SPRITE = range(4)
word = lambda rgb: board_anim.rgb565(rgb)


def spec_of(frames=8, data=None):
    with patch('time.time', return_value=NOW):
        image, payload = render_surf(data or sample(), animated=True, anim_frames=frames)
    return image, payload, board_anim.decode(payload)


def box_of(sprite):
    """The screen box a sprite can ever touch, offsets included: the engine restores all of it on every beat."""
    dx = [d for _, d, _ in sprite['script']]
    dy = [d for _, _, d in sprite['script']]
    return (sprite['x'] + min(dx), sprite['y'] + min(dy), sprite['x'] + 2 * sprite['w'] + max(dx), sprite['y'] + 2 * sprite['h'] + max(dy))


def overlap(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def picture(sprite, frame):
    """{(x, y): word} of the opaque pixels of one frame of a decoded sprite, in sprite pixels."""
    return {(i % sprite['w'], i // sprite['w']): w for i, w in enumerate(sprite['frames'][frame]) if w != board_anim.KEY}


def luminance(rgb):
    values = [c / 255 for c in rgb]
    values = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * w for v, w in zip(values, (.2126, .7152, .0722)))


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + .05) / (lb + .05)


class PanelTests(unittest.TestCase):
    @patch('time.time', return_value=NOW)
    def test_the_panels_are_compact_and_the_title_is_gone(self, _):
        # Tony, 2026-11-03: the weekly panels took 94 of 240 px; now about 58, and no "TIDAL RUSH". The sky runs to the top.
        self.assertLessEqual(PANEL_BOTTOM['claude'] + 1, 62)
        self.assertLessEqual(PANEL_BOTTOM['codex'] + 1, 56)
        page = render_surf(sample()).convert('RGB')
        scene = beach().convert('RGB')
        below = PANEL_BOTTOM['claude'] + 1
        # nothing below the panels but scenery and the first poses of the moving things (the sky, where the title sat, is untouched)
        self.assertEqual(page.crop((0, below, 320, 130)).tobytes(), scene.crop((0, below, 320, 130)).tobytes())

    @patch('time.time', return_value=NOW)
    def test_the_panel_inks_stay_readable_on_their_panel(self, _):
        from token_tv import board_surf
        panel = (16, 42, 76)                                                       # '#102a4c'
        for ink in (board_surf.CREAM, board_surf.YELLOW, board_surf.STONE, board_surf.RESET_INK):
            rgb = tuple(int(ink[i:i + 2], 16) for i in (1, 3, 5))
            self.assertGreaterEqual(contrast(rgb, panel), 4.5, ink)

    def test_the_credits_badge_replaces_the_number_inside_the_codex_panel(self):
        from token_tv.board_credits import BOXES
        x0, y0, x1, y1 = BOXES['surf']
        self.assertTrue(3 < x0 and x1 < 155 and 14 < y0 and y1 < PANEL_BOTTOM['codex'] - 2)       # inside the panel, under the name row
        self.assertLess(x1, 100)                                                   # clear of the reset at the right


class WaveTests(unittest.TestCase):
    def test_falling_lip_sits_between_the_two_previous_curves(self):
        image = _scene(0).convert('RGB')
        # Over these nine rows the previous curves shifted by 10 and 3 pixels.
        # Keep this version visibly between the two, neither flat nor vertical.
        edges = []
        for y in (90, 99):
            row = [x for x in range(45, 80)
                   if (lambda c: c[0] > 150 and c[1] > 230 and c[2] > 200)(image.getpixel((x, y)))]
            self.assertTrue(row, y)
            edges.append(min(row))
        self.assertGreaterEqual(abs(edges[1] - edges[0]), 6)
        self.assertLessEqual(abs(edges[1] - edges[0]), 8)

    def test_the_wave_continues_behind_the_shore_instead_of_stopping_at_a_vertical_edge(self):
        from token_tv.board_surf import _scenery, _shore_foreground
        sea = _scenery().convert('RGB')
        scene = _scene(0).convert('RGB')
        # Before the fix, no water existed left of x=36: the whole shoulder
        # was clipped there. It should still be visible behind the beach.
        for x in (25, 28, 31, 34, 35):
            visible_water = sum(scene.getpixel((x, y)) != sea.getpixel((x, y)) for y in range(78, 107))
            self.assertGreaterEqual(visible_water, 3, x)
        # Where the new water reaches a palm or the sand, those foreground
        # pixels stay visible instead of being painted over by the wave.
        shore = _shore_foreground()
        layer = wave.wave_layer(0)
        overlap = [(x, y) for x in range(12, 36) for y in range(78, 110)
                   if shore.getpixel((x, y))[3] and
                   layer.getpixel((x - wave.ORIGIN[0], y - wave.ORIGIN[1]))[3]]
        self.assertGreater(len(overlap), 20)
        for point in overlap:
            self.assertEqual(scene.getpixel(point), shore.getpixel(point)[:3], point)

    def test_every_pose_of_the_lip_changes_only_the_lips_box(self):
        base = _scene(0).convert('RGB')
        lx0, ly0, lx1, ly1 = LIP
        self.assertLessEqual(lx1, RIDER[0])                                        # the breaking lip is to the surfer's left
        self.assertGreater(FACE[0], lx1)                                           # the face and its moving foam are on the right
        self.assertEqual(len({_scene(p).convert('RGB').tobytes() for p in range(wave.POSES)}), wave.POSES)     # eight poses, all different
        for pose in range(1, wave.POSES):
            image = _scene(pose).convert('RGB')
            for y in range(120):
                for x in range(160):
                    if not (lx0 <= x < lx1 and ly0 <= y < ly1):
                        self.assertEqual(image.getpixel((x, y)), base.getpixel((x, y)), (pose, x, y))

    def test_the_lip_falls_lands_and_rises_without_jumps(self):
        # cocked back (-1) to fallen (+1): no two neighbouring beats of the loop are far apart, the wrap included
        lift = [wave.LIFT[p] for _, _, _, p in PLAN]
        for a, b in zip(lift, lift[1:] + lift[:1]):
            self.assertLessEqual(abs(a - b), 1.5)
        self.assertEqual(wave.LIFT[0], 0.0)
        self.assertEqual((min(wave.LIFT), max(wave.LIFT)), (-1.0, 1.0))
        self.assertEqual((PLAN[0][3], PLAN[-1][3]), (0, 0))                        # calm at the wrap

    def test_the_wave_foot_blends_into_the_sea_instead_of_ending_at_an_opaque_edge(self):
        layer = wave.wave_layer(0)
        for x in (117, 107, 97, 87):
            alpha = [layer.getpixel((x, y))[3] for y in range(layer.height)]
            edge = max(y for y, a in enumerate(alpha) if a)
            self.assertLess(alpha[edge], 100, x)
            self.assertGreater(alpha[edge - 5], 200, x)
            self.assertGreaterEqual(len(set(alpha[edge - 5:edge + 1])), 4, x)

    def test_the_outer_current_moves_down_and_right_including_the_loop_boundary(self):
        from PIL import ImageColor
        highlights = []
        for phase in range(wave.FLOW_PHASES):
            image = wave.flow_overlay(phase)
            highlights.append({(x, y) for x in range(89, 130) for y in range(8, 37)
                               if image.getpixel((x, y))[:3] == ImageColor.getrgb('#82e9dc')})
        for before, after in zip(highlights, highlights[1:] + highlights[:1]):
            # Match painted water between frames, not just an increment sign.
            score, dx, dy = max((len({(x + dx, y + dy) for x, y in before} & after), dx, dy)
                                for dx in range(-6, 7) for dy in range(-4, 5))
            self.assertGreater(score, 8)
            self.assertGreater(dx, 0)
            self.assertGreater(dy, 0)

    def test_the_billows_at_the_right_foot_and_the_face_move_in_every_transition_of_the_current(self):
        _, _, spec = spec_of()
        face = spec['sprites'][FACE_SPRITE]
        self.assertEqual(len({f for f, _, _ in face['script']}), 4)

        def is_foam(w):
            return w != board_anim.KEY and ((w >> 11) << 3) > 180 and (((w >> 5) & 63) << 2) > 225 and ((w & 31) << 3) > 200
        foam = []
        for k in range(4):
            pic = picture(face, k)
            foam.append({xy for xy, w in pic.items() if is_foam(w) and 98 <= xy[1] + FACE[1] < 106})
            self.assertGreater(len(foam[-1]), 20, k)
        for a, b in zip(foam, foam[1:] + foam[:1]):
            self.assertGreater(len(a ^ b), 10)                                     # the foam churns: it is never the same picture
        for k in range(4):
            changed = sum(a != b for a, b in zip(face['frames'][k], face['frames'][(k + 1) % 4]))
            self.assertGreater(changed, 120, k)                                    # and the face flows around it

    def test_left_of_the_surfer_has_no_broad_sheet_of_foam(self):
        def is_bright_foam(pixel):
            r, g, b = pixel
            return r >= 170 and g >= 215 and b >= 195

        for pose in range(wave.POSES):
            image = _scene(pose, 0).convert('RGB')
            bright = sum(is_bright_foam(image.getpixel((x, y))) for y in range(100, 119) for x in range(36, 74))
            self.assertLess(bright, 100, pose)

    def test_right_foam_returns_to_the_lighter_original_amount(self):
        for phase in range(wave.FLOW_PHASES):
            alpha = wave._breaking_foam(phase).getchannel('A')
            coverage = sum(value > 0 for value in alpha.tobytes())
            # The old billows occupied 123–146 pixels, before the enlarged
            # foam obscured much more of the wave. Keep them light again.
            self.assertGreaterEqual(coverage, 90, phase)
            self.assertLessEqual(coverage, 160, phase)
            # The moving foam must blend into the water at the tile's inner
            # edge, otherwise it looks like a straight vertical cut.
            self.assertEqual(alpha.crop((29, 0, 30, alpha.height)).getextrema(), (0, 0), phase)

    def test_foam_remains_inside_its_animation_tile_in_every_phase(self):
        for phase in range(wave.FLOW_PHASES):
            alpha = wave._breaking_foam(phase).getchannel('A')
            box = alpha.getbbox()
            self.assertIsNotNone(box, phase)
            self.assertGreaterEqual(box[0], 2, phase)
            self.assertLessEqual(box[2], 28, phase)


class RiderTests(unittest.TestCase):
    def test_breaking_foam_remains_visible_around_the_surfer(self):
        # Tony liked the strong splash around the surfer; a few thin streaks
        # alone made the effect disappear on the small display.
        for frame, minimum in ((5, 120), (6, 120), (7, 75)):
            image = rider.pictures()[frame]
            pale_water = 0
            for y in range(image.height):
                for x in range(image.width):
                    r, g, b, a = image.getpixel((x, y))
                    if a and r >= 80 and g >= 180 and b >= 170 and g >= r and b >= r:
                        pale_water += 1
            self.assertGreater(pale_water, minimum, frame)

    def test_surfer_and_board_face_left_with_the_wake_behind(self):
        # The face, raised nose, fin and wake must all agree about the direction of travel.
        self.assertLess(rider._deck(-16, 0), rider._deck(16, 0))
        for name, pose in rider.POSES.items():
            grid = rider.Grid(*rider.FRAME, ox=rider.ANCHOR[0], oy=rider.ANCHOR[1])
            rider._surfer(grid, pose)
            pixels = [(x - grid.ox, colour) for row in grid.p for x, colour in enumerate(row) if colour is not None]
            eye = [x for x, colour in pixels if colour == rider.EYE]
            hair = [x for x, colour in pixels if colour in rider.HAIR]
            fins = [x for x, colour in pixels if colour == rider.FIN]
            self.assertEqual(len(eye), 1, name)
            self.assertGreater(sum(hair) / len(hair), eye[0] + 1, name)
            self.assertTrue(fins and min(fins) > 0, name)
        grid = rider.Grid(*rider.FRAME, ox=rider.ANCHOR[0], oy=rider.ANCHOR[1])
        rider._wake(grid, 8, 0)
        wake = [x - grid.ox for row in grid.p for x, colour in enumerate(row) if colour is not None]
        self.assertTrue(wake and min(wake) >= 15)

    def test_all_surfer_poses_are_drawn_inside_their_frame(self):
        class BoundedGrid(rider.Grid):
            def put(self, x, y, colour):
                if not (0 <= x + self.ox < self.w and 0 <= y + self.oy < self.h):
                    raise AssertionError(f'pixel outside the rider frame: {(x, y)}')
                super().put(x, y, colour)

        with patch.object(rider, 'Grid', BoundedGrid):
            for index in range(8):
                with self.subTest(pose=index):
                    rider._picture(index)

    def test_he_is_a_person_in_four_tones_whose_colours_belong_to_him_alone(self):
        # in the animated part of the page, the board's, the skin's and the shirt's base colours are his and nobody else's
        _, _, spec = spec_of()
        mine = {'board': (252, 106, 89), 'skin': (255, 212, 160), 'shirt': (255, 119, 112)}
        region = (36, 60, 160, 119)
        for name, rgb in mine.items():
            for pose in range(wave.POSES):
                for phase in (None, 0, 1, 2, 3):
                    colours = {c for _, c in _scene(pose, phase).convert('RGB').crop(region).getcolors(100000)}
                    self.assertNotIn(rgb, colours, (name, pose, phase))
            self.assertTrue(any(word(rgb) in frame for frame in spec['sprites'][RIDER_SPRITE]['frames']), name)
        for ramp in (rider.SKIN, rider.SHIRT, rider.SHORTS, rider.HAIR, rider.BOARD):    # four distinct tones, lit from the upper left
            self.assertEqual(len({word(t) for t in ramp}), 4)
            lights = [luminance(t) for t in ramp]
            self.assertEqual(lights, sorted(lights))

    def test_eight_pictures_and_a_path_over_a_real_stretch_of_the_wave_without_jumps(self):
        _, _, spec = spec_of()
        sprite = spec['sprites'][RIDER_SPRITE]
        self.assertEqual((len(sprite['frames']), len(sprite['script']), sprite['step_ms']), (8, 32, STEP_MS))
        dys = [dy for _, _, dy in sprite['script']]
        dxs = [dx for _, dx, _ in sprite['script']]
        self.assertGreaterEqual((max(dys) - min(dys)) // 2, 8)                      # climbs and drops at least eight logical pixels
        self.assertGreaterEqual((max(dxs) - min(dxs)) // 2, 3)
        self.assertEqual(len({f for f, _, _ in sprite['script']}), 8)               # cruise, rise, crouch, skim, tuck, under, burst, stand
        for (_, ax, ay), (_, bx, by) in zip(sprite['script'], sprite['script'][1:] + sprite['script'][:1]):
            self.assertLessEqual(abs(ax - bx), 4)                                   # never more than two logical pixels a beat,
            self.assertLessEqual(abs(ay - by), 4)                                   # the loop's wrap included
        self.assertEqual(sprite['script'][0][1:], (0, 0))                           # he begins at home and ends one pixel from it,
        self.assertLessEqual(max(abs(v) for v in sprite['script'][-1][1:]), 2)      # so the wrap is the same smooth step as any other

    def test_the_board_never_teleports_between_beats(self):
        _, _, spec = spec_of()
        sprite = spec['sprites'][RIDER_SPRITE]
        board = word((252, 106, 89))
        middle = []                                                                 # the middle of the board's extent, while it can be seen
        for frame, dx, dy in sprite['script']:                                     # (under the foam, pictures 5 and 6, the overlap test below
            pixels = [xy for xy, w in picture(sprite, frame).items() if w == board]  # is what judges him)
            self.assertTrue(pixels, frame)
            xs, ys = [x for x, _ in pixels], [y for _, y in pixels]
            middle.append(None if frame in (5, 6) else ((min(xs) + max(xs)) / 2 + dx / 2, (min(ys) + max(ys)) / 2 + dy / 2))
        for a, b in zip(middle, middle[1:] + middle[:1]):
            if a and b:
                self.assertLessEqual(abs(a[0] - b[0]), 3.0, (a, b))
                self.assertLessEqual(abs(a[1] - b[1]), 3.0, (a, b))

    def test_consecutive_pictures_overlap_so_nothing_pops_in_or_out(self):
        # the opaque pixels of each beat, placed on the page, overlap the next beat's: he changes, he never appears from nowhere
        _, _, spec = spec_of()
        sprite = spec['sprites'][RIDER_SPRITE]
        shown = [{(x + dx // 2, y + dy // 2) for (x, y) in picture(sprite, frame)} for frame, dx, dy in sprite['script']]
        for a, b in zip(shown, shown[1:] + shown[:1]):
            self.assertGreater(len(a & b) / min(len(a), len(b)), 0.34, (len(a), len(b), len(a & b)))

    def test_every_picture_fits_its_frame_and_the_figure_is_larger_than_the_old_one(self):
        for index, image in enumerate(rider.pictures()):
            self.assertEqual(image.size, rider.FRAME)
            box = image.getchannel('A').getbbox()
            self.assertTrue(box, index)
            self.assertGreater(box[0], 0, index)                                    # nothing is cut by the left or top edge
            self.assertGreater(box[1], 0, index)
            self.assertLess(box[3], image.height, index)                            # the cropped bottom row is always transparent
        stand = rider.pictures()[0].getchannel('A').getbbox()
        self.assertGreaterEqual(stand[3] - stand[1], 28)                           # head to wake: was 22 rows to the board's underside
        self.assertGreaterEqual(stand[2] - stand[0], 33)                           # a 33-pixel board with its wake (the old board was 22)


class AnimationTests(unittest.TestCase):
    @patch('time.time', return_value=NOW)
    def test_capable_boards_recover_both_gulls_without_disturbing_the_wave(self, _):
        legacy_image, legacy_payload = render_surf(sample(), animated=True)
        image, payload = render_surf(sample(), animated=True, extended_anim=True)
        legacy = board_anim.decode(legacy_payload)
        spec = board_anim.decode(payload)
        self.assertEqual(len(legacy['sprites']), 4)
        self.assertEqual(len(spec['sprites']), 6)
        self.assertEqual([(s['w'], s['h']) for s in spec['sprites'][4:]], [(11, 5), (9, 4)])
        self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
        self.assertEqual(render_board_pages(sample(), anim=True, extended_anim=True)[3], rgb565_frame(image, anim=payload))
        self.assertEqual(struct.pack('<76800H', *compose(image, spec, 0)),
                         rgb565_frame(render_surf(sample(), extended_anim=True))[8:])

        # The optimized water tiles must draw exactly the same changed pixels
        # as the legacy tiles for every pose; only their unused borders shrink.
        self.assertEqual(legacy_image.tobytes(), image.tobytes())
        background = struct.unpack('<76800H', rgb565_frame(image)[8:])
        for old, new in zip(legacy['sprites'][1:4], spec['sprites'][1:4]):
            self.assertEqual(old['script'], new['script'])
            for before, after in zip(old['frames'], new['frames']):
                def changes(sprite, frame):
                    return {(sprite['x'] + 2 * (i % sprite['w']), sprite['y'] + 2 * (i // sprite['w'])): pixel
                            for i, pixel in enumerate(frame)
                            if pixel != background[(sprite['y'] + 2 * (i // sprite['w'])) * 320 + sprite['x'] + 2 * (i % sprite['w'])]}
                self.assertEqual(changes(old, before), changes(new, after))

        # An extended flag cannot override a board's four-frame limit.
        _, limited = render_surf(sample(), animated=True, anim_frames=4, extended_anim=True)
        self.assertEqual(len(board_anim.decode(limited)['sprites']), 4)

    @patch('time.time', return_value=NOW)
    def test_gull_flight_is_a_bounded_loop_clear_of_the_hud_and_water(self, _):
        _, payload = render_surf(sample(), animated=True, extended_anim=True)
        sprites = board_anim.decode(payload)['sprites']
        boxes = []
        restored = 0.0
        for sprite in sprites:
            x0, y0, x1, y1 = box_of(sprite)
            box = (max(0, x0), max(0, y0), min(320, x1), min(240, y1))
            restored += (box[2] - box[0]) * (box[3] - box[1]) * STEP_MS / sprite['step_ms']
            for other in boxes:
                self.assertFalse(overlap(box, other), (box, other))
            boxes.append(box)
        self.assertLessEqual(restored, 22000)
        for sprite, box in zip(sprites[4:], boxes[4:]):
            self.assertGreater(box[1], PANEL_BOTTOM['claude'])
            self.assertLessEqual(box[3], CREST[1] * 2)
            self.assertEqual((len(sprite['script']), sprite['step_ms']), (128, STEP_MS))
            for current, following in zip(sprite['script'], sprite['script'][1:] + sprite['script'][:1]):
                if abs(current[1] - following[1]) > 2:
                    self.assertLessEqual(sprite['x'] + current[1] + 2 * sprite['w'], 0)
                    self.assertTrue(all(pixel == board_anim.KEY for pixel in sprite['frames'][following[0]]))
        self.assertEqual(len(board_anim.decode(payload)['sprites']), 6)

    @patch('time.time', return_value=NOW)
    def test_replaces_only_the_fourth_slot_and_the_static_page_is_the_first_pose(self, _):
        self.assertEqual(PAGE_NAMES, ('game-boy', 'paradise', 'code-forge', 'surf', 'dials', 'arcade', 'cockpit', 'countdown'))
        for frames in (8, 4):
            bg, payload = render_surf(sample(), animated=True, anim_frames=frames)
            self.assertLessEqual(len(rgb565_frame(bg, anim=payload)), MAX_PAGE_BYTES)
            self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
            spec = board_anim.decode(payload)
            self.assertEqual(struct.pack('<76800H', *compose(bg, spec, 0)), rgb565_frame(render_surf(sample(), anim_frames=frames))[8:])
            for sprite in spec['sprites']:
                self.assertLessEqual(sprite['w'], 96)
                self.assertLessEqual(sprite['h'], 96)
                self.assertLessEqual(len(sprite['frames']), frames)
        bg, payload = render_surf(sample(), animated=True)
        self.assertEqual(render_board_pages(sample(), anim=True)[3], rgb565_frame(bg, anim=payload))
        # the still is the same picture on a board with eight frames and on one with four
        self.assertEqual(rgb565_frame(render_surf(sample(), anim_frames=8)), rgb565_frame(render_surf(sample(), anim_frames=4)))

    @patch('time.time', return_value=NOW)
    def test_the_payload_and_the_work_per_beat_stay_inside_the_budget(self, _):
        _, payload, spec = spec_of()
        self.assertLessEqual(len(payload), board_anim.MAX_PAYLOAD)
        self.assertGreater(len(payload), 60000)                                     # the eight pictures really are there
        restored = 0.0
        for sprite in spec['sprites']:
            x0, y0, x1, y1 = box_of(sprite)
            restored += (x1 - x0) * (y1 - y0) * STEP_MS / sprite['step_ms']         # pixels the engine restores and pushes per beat
        self.assertLessEqual(restored, 22000)                                       # VERSUS: about 21,000 per 120 ms; this is per 150 ms

    @patch('time.time', return_value=NOW)
    def test_every_animated_box_is_disjoint_and_clear_of_the_instruments_the_low_quota_line_and_the_page_markers(self, _):
        _, _, spec = spec_of()
        boxes = [box_of(sprite) for sprite in spec['sprites']]
        self.assertEqual(len(boxes), 4)                                             # the surfer, the face, the crest and the lip
        for i, a in enumerate(boxes):
            self.assertGreater(a[1], PANEL_BOTTOM['claude'], a)                     # never into the weekly instruments (the line is above them)
            self.assertGreaterEqual(a[0], 0)
            self.assertLessEqual(a[2], 320)
            self.assertLessEqual(a[3], 240)
            self.assertFalse(overlap(a, (0, 228, 40, 240)), a)                      # the firmware's rotation indicator (bottom left) ...
            self.assertFalse(overlap(a, (248, 232, 320, 240)), a)                   # ... and its page-marker dots (bottom right) stay free
            for b in boxes[i + 1:]:
                self.assertFalse(overlap(a, b), (a, b))                             # restoring one must not erase another
        self.assertEqual(boxes[RIDER_SPRITE], tuple(2 * v for v in RIDER))          # the surfer's reach is what the design says it is

    @patch('time.time', return_value=NOW)
    def test_the_tiles_around_him_equal_the_page_wherever_they_meet_still_water(self, _):
        image, _, spec = spec_of()
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))
        tiles = [spec['sprites'][k] for k in (FACE_SPRITE, CREST_SPRITE, LIP_SPRITE)]
        boxes = [box_of(sprite) for sprite in tiles]
        ring = 2 * 2                                                                 # two logical pixels
        for index, (sprite, box) in enumerate(zip(tiles, boxes)):
            others = [b for j, b in enumerate(boxes) if j != index]
            for k, frame in enumerate(sprite['frames']):
                for i, w in enumerate(frame):
                    x, y = box[0] + i % sprite['w'] * 2, box[1] + i // sprite['w'] * 2
                    # the pixel just outside each edge this one lies within the ring of
                    outside = []
                    if x - box[0] < ring:
                        outside.append((box[0] - 2, y))
                    if box[2] - 2 - x < ring:
                        outside.append((box[2], y))
                    if y - box[1] < ring:
                        outside.append((x, box[1] - 2))
                    if box[3] - 2 - y < ring:
                        outside.append((x, box[3]))
                    # beside another moving tile it is part of one picture with it, and at the page's own edge there is no seam
                    shared = [not (0 <= ox < 320 and 0 <= oy < 240) or any(o[0] <= ox < o[2] and o[1] <= oy < o[3] for o in others)
                              for ox, oy in outside]
                    if not outside or all(shared):
                        continue
                    self.assertEqual(w, background[y * 320 + x], (index, k, x, y))

    @patch('time.time', return_value=NOW)
    def test_the_loop_is_one_story_calm_then_the_tube_then_calm_with_no_jump_at_the_wrap(self, _):
        _, _, spec = spec_of()
        rider_sprite, lip_sprite = spec['sprites'][RIDER_SPRITE], spec['sprites'][LIP_SPRITE]
        self.assertEqual([s['step_ms'] * len(s['script']) for s in spec['sprites']], [4800] * 4)       # four sprites, one 4.8 s loop
        poses = [f for f, _, _ in lip_sprite['script']]
        self.assertEqual(poses[:16], [0] * 16)                                      # sixteen calm beats first
        self.assertEqual(set(poses), set(range(8)))                                 # then the lip's whole fall
        self.assertEqual(poses[-4:], [0] * 4)
        used = [f for f, _, _ in rider_sprite['script']]
        self.assertTrue({4, 5, 6, 7} <= set(used[16:28]))                           # tuck, under the lip, burst, stand: in that part only
        self.assertFalse({4, 5, 6} & set(used[:16] + used[28:]))
        self.assertEqual(used[-3:], [0, 0, 0])
        last, first = rider_sprite['script'][-1], rider_sprite['script'][0]
        self.assertEqual(last[0], first[0])                                         # beat 31 shows the picture beat 0 shows,
        self.assertLessEqual(max(abs(a - b) for a, b in zip(last[1:], first[1:])), 2)     # one logical pixel away from it

    @patch('time.time', return_value=NOW)
    def test_no_beat_is_a_freeze_and_none_is_a_pop_the_loop_wrap_included(self, _):
        # Tony, 2026-11-03: "it must never teleport or pop". Every beat of the loop is composed with the engine's own timing (the
        # two clocks), and how much of the picture changes from one beat to the next stays within a calm band, also at the wrap.
        image, _, spec = spec_of()
        background = list(struct.unpack('<76800H', rgb565_frame(image)[8:]))

        def beat(n):
            words = list(background)
            for sprite in spec['sprites']:
                frame, dx, dy = sprite['script'][(n * STEP_MS // sprite['step_ms']) % len(sprite['script'])]
                for i, w in enumerate(sprite['frames'][frame]):
                    if w != board_anim.KEY:
                        x, y = sprite['x'] + dx + i % sprite['w'] * 2, sprite['y'] + dy + i // sprite['w'] * 2
                        for yy in (y, y + 1):
                            for xx in (x, x + 1):
                                words[yy * 320 + xx] = w
            return words
        shots = [beat(n) for n in range(33)]
        self.assertEqual(shots[32], shots[0])                                       # the loop closes exactly
        counts = [sum(a != b for a, b in zip(shots[n], shots[n + 1])) // 4 for n in range(32)]    # logical pixels
        self.assertGreater(min(counts), 150, counts)                                # never a frozen beat, the wrap included (31 -> 0)
        self.assertLess(max(counts), 1300, counts)                                  # never a pop: the tube's busiest beat is no wilder
        self.assertLess(max(counts[16:28]), 1.5 * max(counts[:16]))                 # than a calm one by more than half again

    @patch('time.time', return_value=NOW)
    def test_four_picture_boards_keep_a_complete_version_of_the_same_story(self, _):
        _, payload, spec = spec_of(4)
        for sprite in spec['sprites']:
            self.assertLessEqual(len(sprite['frames']), 4)
        self.assertEqual([len(s['script']) for s in spec['sprites']], [32, 16, 16, 32])
        self.assertEqual(len({tuple(f) for f in spec['sprites'][LIP_SPRITE]['frames']}), 4)
        self.assertLess(len(payload), len(spec_of(8)[1]) * 0.7)                      # a lighter payload than the eight-picture story

    @patch('time.time', return_value=NOW)
    def test_the_scene_is_far_richer_than_the_first_flat_version(self, _):
        scene_top = PANEL_BOTTOM['claude'] + 1
        scene = render_surf(sample()).crop((0, scene_top, 320, 240))
        self.assertGreater(len(scene.getcolors(100000)), 200)                       # was about 130 with flat bands
        sky = scene.crop((0, 96 - scene_top, 320, 152 - scene_top))                 # the sky between the old panels' bottom and the horizon
        self.assertGreater(len({sky.getpixel((x, y)) for x in range(0, 320, 4) for y in range(56)}), 40)

    @patch('time.time', return_value=NOW)
    def test_unknown_week_hearts_reset_and_session_remain_independent(self, _):
        cases = [sample(0, hearts=0), sample(100, hearts=3), sample(hearts=None), {'accounts': {}}]
        changed = copy.deepcopy(cases[0]); changed['accounts']['codex']['windows'][0]['resets_at'] += 86400; cases.append(changed)
        images, payloads = zip(*(render_surf(s, animated=True) for s in cases))
        below = PANEL_BOTTOM['claude'] + 1
        self.assertEqual(len({im.crop((0, 0, 320, below)).tobytes() for im in images}), len(cases))
        self.assertEqual(len({im.crop((0, below, 320, 240)).tobytes() for im in images}), 1)
        self.assertEqual(len(set(payloads)), 1)
        with_session = render_surf(sample()); without = render_surf(sample(session=False))
        self.assertEqual(with_session.crop((0, 0, 160, below)).tobytes(), without.crop((0, 0, 160, below)).tobytes())
        self.assertNotEqual(with_session.crop((160, 51, 320, 60)).tobytes(), without.crop((160, 51, 320, 60)).tobytes())
        self.assertEqual(with_session.crop((160, 0, 320, 51)).tobytes(), without.crop((160, 0, 320, 51)).tobytes())


if __name__ == '__main__':
    unittest.main()
