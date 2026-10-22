"""The countdown page (8): Manhattan seen from above at dusk; three buildings carry the usage, the rest is city."""
import unittest
from unittest.mock import patch

from PIL import Image

from token_tv import board_anim, board_art, board_city as bc
from token_tv.board_pages import PAGE_NAMES, render_board_pages
from token_tv.sample import snapshot
from token_tv.board_pages import rgb565_frame

NOW = 2000000000
DAY, HOUR = 86400, 3600


def compose(background, spec, step):
    """Independent reference compositor in screen pixels, after RGB565 conversion."""
    import struct
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
                    if 0 <= xx < 320 and 0 <= yy < 240:
                        words[yy * 320 + xx] = word
    return words


def case(used=27, session=('5H', 41, 2 * HOUR), hearts=2):
    windows = {'codex': [('WEEK', used, 6 * DAY + 8 * HOUR)],
               'claude': [('WEEK', used, 5 * DAY + 16 * HOUR)] + ([session] if session else [])}
    data = snapshot(now=NOW, sample=[('codex', 'CODEX', 'codex', windows['codex']),
                                     ('claude', 'CLAUDE', 'claude', windows['claude'])])
    for provider in ('codex', 'claude'):
        data['accounts'][provider]['banked_resets'] = {'available': hearts, 'confirmed_at': NOW, 'source': 'manual'}
    return data


def render(data):
    with patch('time.time', return_value=NOW):
        return bc.render_countdown(data)


def luminance(colour):
    channels = [v / 255 for v in colour[:3]]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def centre(quad):
    return round(sum(x for x, _ in quad) / 4), round(sum(y for _, y in quad) / 4)


def peak(image, quad):
    """The brightest pixel around a window's centre (a window is only two pixels wide after the page is reduced)."""
    x, y = centre(quad)
    return max((image.getpixel((x + dx, y + dy)) for dx in (-1, 0, 1) for dy in (-1, 0, 1)), key=sum)


def brightness(image, quad):
    return sum(peak(image, quad)) / 3


def lit_columns_measured(image, name, baseline):
    """For each floor of a tower from the street up, how many of its columns shine (compared with the page with no reading)."""
    return [sum(1 for column in columns if any(lit_against(image, baseline, q, 200, 0) for q in column))
            for columns in bc.tower_columns(name)]


def expected_columns(name, value):
    return [bc.lit_columns(f, bc.week_floors(value), len(columns)) for f, columns in enumerate(bc.tower_columns(name))]


def lit_against(image, baseline, quad, threshold, spread=1):
    """True if the window's light shines in `image` and not in `baseline` (the same page without any session). The
    quota windows are bright and the time windows dim, so each face has its own threshold (a lit corner window also
    spills a little light onto its neighbour across the corner)."""
    x, y = centre(quad)
    return max(sum(abs(a - b) for a, b in zip(image.getpixel((x + dx, y)), baseline.getpixel((x + dx, y))))
               for dx in range(-spread, spread + 1)) > threshold


def small_floors(image, side, baseline):
    """(lit windows, windows) of each floor of the five-hour building on one face (0 = left, 1 = right)."""
    threshold, spread = (350, 1) if side == 0 else (90, 0)
    return [(sum(1 for q in floor[side] if lit_against(image, baseline, q, threshold, spread)), len(floor[side])) for floor in bc.small_windows()]


class CityTests(unittest.TestCase):
    def test_the_week_lights_ten_floors_from_the_street_up_and_the_last_one_window_by_window(self):
        baseline = render({'accounts': {}})
        for left in (100, 75, 73, 30, 8, 1, 0):
            image = render(case(used=100 - left))
            for name in ('codex', 'claude'):
                self.assertEqual(lit_columns_measured(image, name, baseline), expected_columns(name, left), (name, left))
        # 75 % is seven floors and half of the eighth: the left face of it, as the eye reads round the building
        columns = expected_columns('codex', 75)
        self.assertEqual(columns, [12] * 7 + [4, 0, 0])
        self.assertEqual([bc.week_floors(v) for v in (None, 0, 1, 2, 7.4, 75, 100)], [0, 0, .1, .2, .7, 7.5, 10])
        self.assertEqual([bc.lit_columns(7, 7.5, 8), bc.lit_columns(7, 7.04, 8), bc.lit_columns(7, 7.0, 8), bc.lit_columns(6, 7.5, 12)], [4, 1, 0, 12])

    def test_an_unknown_week_lights_nothing_and_never_looks_like_zero(self):
        image = render({'accounts': {}})
        for name in ('codex', 'claude'):
            for left, right in bc.tower_windows(name):                        # every window is the tower's own dark one
                for quad in left + right:
                    self.assertTrue(15 < sum(image.getpixel(centre(quad))) / 3 < 150, (name, sum(image.getpixel(centre(quad))) / 3))
        self.assertNotEqual(image.tobytes(), render(case(used=100)).tobytes())       # "0 % left" is a number, not dashes

    def test_the_small_building_is_claudes_five_hours_with_quota_on_the_left_face_and_time_on_the_right(self):
        without = render(case(session=None))
        image = render(case())                                            # 59 % left, two hours left
        self.assertEqual([lit for lit, _ in small_floors(image, 0, without)], [8, 8, 8, 0, 0])      # 3 floors of 20 %
        self.assertEqual([lit for lit, _ in small_floors(image, 1, without)], [8, 8, 0, 0, 0])      # 2 hours
        partial = render(case(session=('5H', 59, 90 * 60)))               # 41 % left, 1h30 left
        self.assertEqual([lit for lit, _ in small_floors(partial, 0, without)], [8, 8, 2, 0, 0])    # a quarter of the third floor
        self.assertEqual([lit for lit, _ in small_floors(partial, 1, without)], [8, 4, 0, 0, 0])    # an hour and half an hour
        nearly = render(case(session=('5H', 95, 10 * 60)))                # 5 % left, ten minutes left: one step each
        self.assertEqual([lit for lit, _ in small_floors(nearly, 0, without)], [2, 0, 0, 0, 0])
        self.assertEqual([lit for lit, _ in small_floors(nearly, 1, without)], [2, 0, 0, 0, 0])
        for side in (0, 1):                                               # no fresh reading: nothing lights
            self.assertEqual([lit for lit, _ in small_floors(without, side, without)], [0] * 5)

    def test_it_is_a_dense_city_and_only_three_buildings_react_to_readings(self):
        self.assertGreater(len(bc._city()), 150)
        a, b = render(case(used=20)), render(case(used=70, session=('5H', 80, HOUR), hearts=0))
        regions = []
        for name in ('codex', 'claude'):
            pts = [p for box in bc._hero_boxes(name) for face in bc._box_faces(*box)[:2] for p in face]
            pts += [bc.proj(bc.HEROES[name][0] + 1.5, bc.HEROES[name][1] + 1.5, 125)]            # its rooftop sign
            regions.append((min(x for x, _ in pts) - 12, min(y for _, y in pts) - 22, max(x for x, _ in pts) + 12, max(y for _, y in pts) + 12))
        small = [p for face in bc._box_faces(*bc._small_box())[:2] for p in face] + [bc.proj(bc.SMALL[0] + 1.5, bc.SMALL[1] + 1.5, 62)]
        regions.append((min(x for x, _ in small) - 12, min(y for _, y in small) - 14, max(x for x, _ in small) + 12, max(y for _, y in small) + 12))
        regions += [(0, 170, 160, 236), (160, 170, 320, 236)]                                       # the two cards
        for y in range(240):
            for x in range(320):
                if a.getpixel((x, y)) != b.getpixel((x, y)):
                    self.assertTrue(any(r[0] <= x <= r[2] and r[1] <= y <= r[3] for r in regions), (x, y))

    def test_each_tower_has_its_mascot_on_a_lit_rooftop_sign_and_each_keeps_its_colour(self):
        image = render(case())
        def region_colours(name):
            x, y = bc.proj(bc.HEROES[name][0] + 1.5, bc.HEROES[name][1] + 1.5, bc.TOWER_FLOORS * bc.HERO_FLOOR + 12 + 4 + 6)
            return [image.getpixel((px, py)) for py in range(round(y) - 8, round(y) + 9) for px in range(round(x) - 12, round(x) + 13)]
        self.assertTrue(any(b > 200 and r < 140 for r, g, b in region_colours('codex')))                 # the blue cloud
        self.assertTrue(any(r > 190 and 100 < g < 170 and b < 120 for r, g, b in region_colours('claude')))   # the orange critter
        for r, g, b in [peak(image, q) for left, right in bc.tower_windows('codex')[:6] for q in left + right]:
            self.assertTrue(r > 200 and g > 170 and b < 220 and r > b + 20, (r, g, b))               # warm yellow windows
        for r, g, b in [peak(image, q) for left, right in bc.tower_windows('claude')[:6] for q in left + right]:
            self.assertTrue(abs(r - g) < 30 and abs(g - b) < 45 and min(r, g, b) > 180, (r, g, b))      # stone-white windows

    def test_cards_stay_readable_and_the_session_changes_nothing_but_the_small_building(self):
        card = (12, 16, 26)
        for ink in (board_art._rgb(bc.LABEL), board_art._rgb(board_art.CODEX), board_art._rgb(board_art.CLAUDE), (234, 244, 255)):
            self.assertGreaterEqual(contrast(ink, card), 4.5, ink)
        with_session, without = render(case()), render(case(session=None))
        changed = [(x, y) for y in range(240) for x in range(320) if with_session.getpixel((x, y)) != without.getpixel((x, y))]
        self.assertTrue(changed)
        x0, y0, x1, y1 = bc._small_box()[:4]
        area = [p for face in bc._box_faces(*bc._small_box())[:2] for p in face]
        left, right = min(x for x, _ in area) - 14, max(x for x, _ in area) + 14
        top, bottom = min(y for _, y in area) - 24, max(y for _, y in area) + 14
        self.assertTrue(all(left <= x <= right and top <= y <= bottom for x, y in changed), 'the session changed more than its building')

    def test_the_page_marker_corner_stays_free_and_hearts_stay_in_their_row(self):
        image, bare = render(case()), bc.city_backdrop().resize((320, 240), Image.Resampling.LANCZOS).convert('RGB')
        for y in range(234, 240):
            for x in range(250, 320, 2):
                self.assertTrue(all(abs(a - b) < 16 for a, b in zip(image.getpixel((x, y)), bare.getpixel((x, y)))), (x, y))
        two, three = render(case(hearts=2)), render(case(hearts=3))
        changed = [(x, y) for y in range(240) for x in range(320) if two.getpixel((x, y)) != three.getpixel((x, y))]
        self.assertTrue(changed and all(176 <= y <= 198 for _, y in changed), 'a heart changed something outside its row')

    def test_the_colours_of_the_city_are_a_real_dusk_and_not_a_lilac_cast(self):
        picture = bc.city_backdrop().resize((320, 240), Image.Resampling.LANCZOS).convert('RGB')
        pixels = [picture.getpixel((x, y)) for y in range(30, 172) for x in range(320)]
        lilac = sum(1 for r, g, b in pixels if b > r + 12 and r > g + 6 and b > g + 20)         # violet / lilac
        magenta = sum(1 for r, g, b in pixels if r > g + 25 and b > g + 25)                      # pink / magenta
        self.assertLess(lilac / len(pixels), .02)
        self.assertLess(magenta / len(pixels), .02)
        means = [sum(c) / len(pixels) for c in zip(*pixels)]                                      # a neutral, slightly warm average
        self.assertLess(abs(means[0] - means[2]), 30)
        self.assertGreater(means[0] + 2, means[2] - 4)
        sky = bc._rgb(bc.SKY[0][0])
        self.assertTrue(sky[2] > sky[0] and sky[1] > sky[0], sky)                                 # the top of the sky is blue-teal
        self.assertEqual(bc._fog((10, 20, 30), 0), (10, 20, 30))                                  # and there is no haze at all

    def test_the_city_moves_a_gull_a_flock_a_car_and_ten_windows_that_come_and_go(self):
        sprites = bc.city_animation()
        self.assertEqual([s.get('name', 'car') for s in sprites], ['gull', 'flock', 'car', 'windows'])
        boxes = []
        for s in sprites:
            xs = [s['x'] + dx for _, dx, _ in s['script']]
            ys = [s['y'] + dy for _, _, dy in s['script']]
            frame = s['frames'][0]
            boxes.append((min(xs), min(ys), max(xs) + frame.width * 2, max(ys) + frame.height * 2))
            self.assertEqual(s['step_ms'], bc.ANIM_STEP_MS)
            self.assertLessEqual(len(s['script']), 32)
            self.assertLessEqual(len(s['frames']), 4)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertTrue(a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], (a, b))
        regions = bc._data_regions()                                     # the windows keep away from the data buildings, their signs and the cards
        box = boxes[3]
        self.assertFalse(any(not (box[2] <= r[0] or r[2] <= box[0] or box[3] <= r[1] or r[3] <= box[1]) for r in regions), box)
        polygons = bc._body_polygons()                                   # the cars never drive over the data buildings (their glow neither)
        for car, car_box in zip(sprites[2:3], boxes[2:3]):
            self.assertLessEqual(car_box[3], 172)
            seen = []
            for index, dx, dy in car['script']:
                opaque = [(i % car['frames'][index].width, i // car['frames'][index].width)
                          for i, p in enumerate(car['frames'][index].getdata()) if p[3]]
                seen.append(bool(opaque))
                for i, j in opaque:
                    point = (car['x'] + dx + i * 2 + 1, car['y'] + dy + j * 2 + 1)
                    self.assertFalse(any(bc._inside(point, poly, 1.0) for poly in polygons), (car['x'], dx, dy))
            run = best = 0
            for flag in seen + seen:                                     # each car is in view for a good stretch of the loop
                run = run + 1 if flag else 0
                best = max(best, run)
            self.assertGreaterEqual(min(best, len(seen)), 5)
        self.assertLessEqual(boxes[0][3], 60)                            # the gull stays in the sky, above the towers' windows
        gull = sprites[0]
        first, last = gull['script'][0], gull['script'][-1]
        self.assertGreaterEqual(gull['x'] + first[1], 320)               # it comes in over the right edge...
        self.assertLessEqual(gull['y'] + last[2] + gull['frames'][0].height * 2, 1)   # ...and leaves over the top: the loop restarts unseen
        # the lights come and go, one window at a time, and the cars fade in and out
        windows = sprites[3]
        lit = [sum(1 for j in range(f.height) for i in range(f.width) if f.getpixel((i, j))[3]) for f in windows['frames']]
        self.assertEqual(lit, [9, 9, 9, 9])
        self.assertEqual(len({f.tobytes() for f in windows['frames']}), 4)
        for car in sprites[2:3]:
            self.assertTrue(all(not any(p[3] for p in car['frames'][3].getdata()) for _ in (0,)))        # one frame is fully dark
            moves = {(dx, dy) for _, dx, dy in car['script']}
            self.assertGreater(len(moves), 12)

    def test_the_flock_crosses_the_upper_left_sky_and_leaves_unseen(self):
        flock = bc.city_animation()[1]
        self.assertEqual(flock['name'], 'flock')
        self.assertEqual(len({f.tobytes() for f in flock['frames']}), 4)                    # the wings beat: four poses
        width, height = flock['frames'][0].size
        xs = [flock['x'] + dx for _, dx, _ in flock['script']]
        ys = [flock['y'] + dy for _, _, dy in flock['script']]
        self.assertLessEqual(max(dx for _, dx, _ in flock['script']), 127)                  # a sprite never travels more than 127 px
        self.assertLessEqual(xs[0] + width * 2, 0)                                           # it starts beyond the left edge...
        self.assertLessEqual(ys[-1] + height * 2, 0)                                         # ...and ends above the top: the loop restarts unseen
        whole = sum(1 for x, y in zip(xs, ys) if x >= 0 and y >= 0)
        self.assertGreaterEqual(whole, 10)                                                   # entirely in view for a good stretch of the loop
        polygons = bc._body_polygons()                                                       # it never crosses a data building
        for index, dx, dy in flock['script']:
            for i, p in enumerate(flock['frames'][index].getdata()):
                if p[3]:
                    point = (flock['x'] + dx + (i % width) * 2 + 1, flock['y'] + dy + (i // width) * 2 + 1)
                    self.assertFalse(any(bc._inside(point, poly, 4.0) for poly in polygons), (dx, dy))

    def test_the_first_pose_is_the_static_picture_and_nothing_animated_covers_a_reading(self):
        with patch('time.time', return_value=NOW):
            static = bc.render_countdown(case())
            background, payload = bc.render_countdown(case(), animated=True)
            other, _ = bc.render_countdown(case(used=80, session=('5H', 90, HOUR), hearts=0), animated=True)
        spec = board_anim.decode(payload)
        self.assertLess(len(payload), board_anim.MAX_PAYLOAD)
        self.assertEqual(len(spec['sprites']), 4)
        import struct
        self.assertEqual(struct.pack('<76800H', *compose(background, spec, 0)), rgb565_frame(static)[8:])
        readings = {y * 320 + x for y in range(240) for x in range(320) if background.getpixel((x, y)) != other.getpixel((x, y))}
        for sprite in spec['sprites']:
            for step in range(len(sprite['script'])):
                index, dx, dy = sprite['script'][step]
                for i, word in enumerate(sprite['frames'][index]):
                    if word == board_anim.KEY:
                        continue
                    x = sprite['x'] + dx + i % sprite['w'] * 2
                    y = sprite['y'] + dy + i // sprite['w'] * 2
                    for px, py in ((x, y), (x + 1, y), (x, y + 1), (x + 1, y + 1)):
                        if 0 <= px < 320 and 0 <= py < 240:
                            self.assertNotIn(py * 320 + px, readings, (sprite['x'], sprite['y'], step))

    def test_the_skyline_has_many_skyscrapers_and_many_kinds_of_top(self):
        visible = [b for b in bc._city() if b.kind == 'city']
        self.assertGreaterEqual(sum(1 for b in visible if b.h > 80), 25)              # plenty of skyscrapers
        self.assertGreaterEqual(sum(1 for b in visible if b.h > 100), 15)
        crowns = {}
        for b in visible:
            crowns[b.style['crown']] = crowns.get(b.style['crown'], 0) + 1
        self.assertGreaterEqual(len(crowns), 9, crowns)                                # spire, mast, pyramid, dome, twin, ...
        self.assertLess(max(crowns.values()) / len(visible), .3, crowns)               # and no one top rules the skyline
        towers = [b for b in visible if b.h > 80]
        self.assertGreaterEqual(len({b.style['crown'] for b in towers}), 6)            # the tall ones differ among themselves too

    def test_the_top_of_the_picture_is_city_not_sky(self):
        picture = bc.city_backdrop().resize((320, 240), Image.Resampling.LANCZOS).convert('RGB')
        sky = bc._gradient_sky((320 * bc.S, 240 * bc.S))
        bare = [(x, y) for y in range(0, 36) for x in range(320)
                if all(abs(a - b) < 10 for a, b in zip(picture.getpixel((x, y)), sky.getpixel((x * bc.S, y * bc.S))))]
        self.assertEqual(bare, [], bare[:6])                             # no patch of blue sky above the first streets

    def test_buildings_tell_apart_roof_lighter_than_walls_and_the_light_wall_on_the_right(self):
        import random
        from PIL import ImageDraw
        for material in bc.MATERIALS:
            canvas = Image.new('RGBA', (320 * bc.S, 240 * bc.S), (0, 0, 0, 255))
            bc._paint_box(ImageDraw.Draw(canvas), 20, 30, 23, 33, 0, 36, material, 1.0, random.Random(3), 0, windows=False, style={'tone': 0.0})
            def at(point):
                return canvas.getpixel((round(point[0] * bc.S), round(point[1] * bc.S)))
            left, right, roof = bc._box_faces(20, 30, 23, 33, 0, 36)
            centre = lambda quad: (sum(x for x, _ in quad) / 4, sum(y for _, y in quad) / 4)
            lum = lambda c: luminance(c)
            self.assertGreater(lum(at(centre(roof))), lum(at(centre(right))) * 1.1, material)      # the roof catches the sky
            self.assertGreater(lum(at(centre(right))), lum(at(centre(left))), material)             # the right wall is lit, the left one in shade

    def test_the_page_is_deterministic_and_carries_no_star_trailer(self):
        self.assertEqual(render(case()).tobytes(), render(case()).tobytes())
        self.assertEqual(render(case()).size, (320, 240))
        with patch('time.time', return_value=NOW):
            plain = render_board_pages(case())
            twinkling = render_board_pages(case(), stars=True)
        index = PAGE_NAMES.index('countdown')
        self.assertEqual(plain[index], twinkling[index])               # no sky is left to twinkle


if __name__ == '__main__':
    unittest.main()
