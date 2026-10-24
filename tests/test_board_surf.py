"""Surf stays decorative; weekly instruments must survive every animation step."""
import copy
import struct
import unittest
from unittest.mock import patch

from token_tv import board_anim
from token_tv.board import MAX_PAGE_BYTES
from token_tv.board_pages import PAGE_NAMES, render_board_pages, rgb565_frame
from token_tv.board_surf import render_surf
from test_board_forge import NOW, sample, compose


class SurfTests(unittest.TestCase):
    def test_left_break_has_visible_foam_that_churns_in_every_transition(self):
        from token_tv.board_surf import wave_pose
        def is_foam(color):
            return color[0] > 180 and color[1] > 225 and color[2] > 200
        foam = []
        for phase in range(4):
            image = wave_pose(phase).convert('RGB')
            foam.append({(x,y) for y in range(29,38) for x in range(3,33)
                         if is_foam(image.getpixel((x,y)))})
            self.assertGreater(len(foam[-1]), 40, phase)
        for before,after in zip(foam,foam[1:]+foam[:1]):
            self.assertGreater(len(before ^ after), 20)

    def test_outer_current_moves_down_the_face_including_the_loop_boundary(self):
        from PIL import Image, ImageDraw, ImageColor
        from token_tv.board_surf import _wave_motion
        highlights = []
        for phase in range(4):
            image = Image.new('RGBA', (120,40))
            _wave_motion(ImageDraw.Draw(image),phase)
            highlights.append({(x,y) for x in range(18,59) for y in range(8,37)
                               if image.getpixel((x,y))[:3] == ImageColor.getrgb('#82e9dc')})
        for before,after in zip(highlights,highlights[1:]+highlights[:1]):
            # Match painted water between frames, not just an increment sign.
            score,dx,dy = max((len({(x+dx,y+dy) for x,y in before}&after),dx,dy)
                             for dx in range(-6,7) for dy in range(-4,5))
            self.assertGreater(score,8)
            self.assertLess(dx,0)
            self.assertGreater(dy,0)

    def test_exterior_water_has_visible_flow_over_the_shoulder(self):
        from token_tv.board_surf import wave_pose
        frames = [wave_pose(i) for i in range(4)]
        for i, image in enumerate(frames):
            next_image = frames[(i+1)%4]
            # Left shoulder only: excludes the surfer and the inside of the tube.
            changed = sum(image.getpixel((x,y)) != next_image.getpixel((x,y))
                          for y in range(8,37) for x in range(10,49))
            self.assertGreater(changed, 70, i)

    def test_wave_foot_blends_into_the_sea_instead_of_ending_at_an_opaque_edge(self):
        from token_tv.board_surf import _wave_layer
        layer = _wave_layer()
        # The unbroken face used to end with an opaque dark outline. Its last
        # few rows must now share the underlying sea, away from the foam bank.
        for x in (30, 40, 50, 60):
            alpha = [layer.getpixel((x, y))[3] for y in range(layer.height)]
            edge = max(y for y, a in enumerate(alpha) if a)
            self.assertLess(alpha[edge], 100, x)
            self.assertGreater(alpha[edge - 5], 200, x)
            self.assertGreaterEqual(len(set(alpha[edge - 5:edge + 1])), 4, x)

    def test_board_is_stable_while_body_articulates_relative_to_it(self):
        from token_tv.board_surf import wave_pose
        board_positions, relative_bodies = [], []
        for phase in range(4):
            image = wave_pose(phase).convert('RGB')
            board = {(x,y) for y in range(40) for x in range(120)
                     if image.getpixel((x,y)) == (252,106,89)}
            self.assertTrue(board)
            anchor = (min(x for x,y in board), min(y for x,y in board))
            board_positions.append(anchor)
            relative_bodies.append(frozenset((x-anchor[0],y-anchor[1])
                for y in range(40) for x in range(120)
                if image.getpixel((x,y)) in ((255,212,160),(255,119,112))))
        self.assertEqual(len({x for x,y in board_positions}), 1)
        self.assertLessEqual(max(y for x,y in board_positions)-min(y for x,y in board_positions), 1)
        self.assertGreaterEqual(len(set(relative_bodies)), 3)

    def test_water_perimeter_matches_continuous_background_in_every_pose(self):
        from PIL import Image
        from token_tv.board_surf import beach, wave_pose, BOX
        background = beach().crop(BOX).resize((120, 40), Image.Resampling.NEAREST).convert('RGBA')
        # The former straight line was the bottom of the opaque animation crop.
        # All exterior edges now come from the same full-scene water geometry.
        for phase in range(4):
            frame = wave_pose(phase)
            for edge in ((0,0,120,2), (0,38,120,40), (0,0,2,40), (118,0,120,40)):
                self.assertEqual(frame.crop(edge).tobytes(), background.crop(edge).tobytes(),
                                 (phase, edge))

    @patch('time.time', return_value=NOW)
    def test_replaces_only_fourth_slot_and_static_matches_first_pose(self, _):
        self.assertEqual(PAGE_NAMES, ('game-boy','paradise','code-forge','surf','dials','arcade','cockpit','countdown'))
        bg,payload=render_surf(sample(),animated=True)
        frame=rgb565_frame(bg,anim=payload)
        self.assertEqual(render_board_pages(sample(),anim=True)[3],frame)
        self.assertLessEqual(len(frame),MAX_PAGE_BYTES)
        self.assertLessEqual(len(payload),40000)
        spec=board_anim.decode(payload)
        self.assertEqual(struct.pack('<76800H',*compose(bg,spec,0)),rgb565_frame(render_surf(sample()))[8:])
        self.assertEqual(len({tuple(compose(bg,spec,i)) for i in range(4)}),4)
        for sprite in spec['sprites']:
            self.assertLessEqual(sprite['w'],96)
            self.assertLessEqual(sprite['h'],96)
            for _,dx,dy in sprite['script']:
                self.assertGreaterEqual(sprite['y']+dy,96)
                self.assertGreaterEqual(sprite['x']+dx,0)
                self.assertLessEqual(sprite['x']+dx+sprite['w']*2,320)
                self.assertLessEqual(sprite['y']+dy+sprite['h']*2,240)

    @patch('time.time', return_value=NOW)
    def test_every_animated_box_is_disjoint_and_clear_of_the_instruments_and_the_logo(self, _):
        from token_tv.board_surf import LOGO_BOX
        _, payload = render_surf(sample(), animated=True)
        boxes = []
        for sprite in board_anim.decode(payload)['sprites']:
            dxs = [dx for _, dx, _ in sprite['script']]
            dys = [dy for _, _, dy in sprite['script']]
            boxes.append((sprite['x'] + min(dxs), sprite['y'] + min(dys),
                          sprite['x'] + max(dxs) + sprite['w'] * 2, sprite['y'] + max(dys) + sprite['h'] * 2))
        self.assertEqual(len(boxes), 4)                                        # two wave halves and two gulls
        overlap = lambda a, b: a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
        for i, a in enumerate(boxes):
            self.assertGreaterEqual(a[1], 96, a)                               # never into the weekly instruments
            self.assertFalse(overlap(a, LOGO_BOX), a)                          # nor across the logo
            for b in boxes[i + 1:]:
                self.assertFalse(overlap(a, b), (a, b))                        # restoring one must not erase another

    @patch('time.time', return_value=NOW)
    def test_the_scene_is_far_richer_than_the_first_flat_version(self, _):
        scene = render_surf(sample()).crop((0, 96, 320, 240))
        self.assertGreater(len(scene.getcolors(100000)), 200)                  # was about 130 with flat bands
        sky = scene.crop((0, 0, 320, 56))                                      # rows of sky above the horizon
        self.assertGreater(len({sky.getpixel((x, y)) for x in range(0, 320, 4) for y in range(56)}), 40)

    @patch('time.time', return_value=NOW)
    def test_unknown_week_hearts_reset_and_session_remain_independent(self, _):
        cases=[sample(0,hearts=0),sample(100,hearts=3),sample(hearts=None),{'accounts':{}}]
        changed=copy.deepcopy(cases[0]);changed['accounts']['codex']['windows'][0]['resets_at']+=86400;cases.append(changed)
        images,payloads=zip(*(render_surf(s,animated=True) for s in cases))
        self.assertEqual(len({im.crop((0,0,320,96)).tobytes() for im in images}),len(cases))
        self.assertEqual(len({im.crop((0,96,320,240)).tobytes() for im in images}),1)
        self.assertEqual(len(set(payloads)),1)
        with_session=render_surf(sample());without=render_surf(sample(session=False))
        self.assertEqual(with_session.crop((0,0,160,96)).tobytes(),without.crop((0,0,160,96)).tobytes())
        self.assertNotEqual(with_session.crop((160,62,320,72)).tobytes(),without.crop((160,62,320,72)).tobytes())
        self.assertEqual(with_session.crop((160,0,320,62)).tobytes(),without.crop((160,0,320,62)).tobytes())


if __name__ == '__main__':
    unittest.main()
