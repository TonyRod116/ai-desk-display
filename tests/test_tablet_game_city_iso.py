"""The tablet's CITY IN THE SKY atlas (scripts/prepare_game_city_iso.py): the files it writes and the numbers in them, drawn small and fast (--quick) from the
project's own code and two mascots: no private art, no Tony's pictures, no network. The scene itself is tested in tests/test_tablet_game_city_iso.mjs."""
import contextlib
import io
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageChops

from scripts import prepare_game_city_iso as city
from scripts import tablet_media as media
from token_tv import tablet_server


def pixels(image):
    """The pixels of a picture as a flat sequence (Pillow renames getdata)."""
    return (getattr(image, 'get_flattened_data', None) or image.getdata)()


class RoofSigns(unittest.TestCase):
    def test_the_main_towers_have_four_small_panels_attached_to_their_roof_edges(self):
        for name, hero in city.place_heroes().items():
            with self.subTest(name=name), mock.patch.object(city, 'roof_sign_panel') as panel:
                city.paint_hero(city.Cv(s=1), city.Rec(), hero)
                if hero.small:
                    panel.assert_not_called()
                    continue
                self.assertEqual(panel.call_count, 4)
                x0, y0, x1, y1, _, top = hero.boxes()[-1]
                expected = {frozenset(edge) for edge in (
                    ((x0, y0), (x1, y0)), ((x0, y0), (x0, y1)),
                    ((x0, y1), (x1, y1)), ((x1, y0), (x1, y1)))}
                actual = {frozenset((call.args[1], call.args[2])) for call in panel.call_args_list}
                self.assertEqual(actual, expected)
                for call in panel.call_args_list:
                    self.assertEqual(call.args[3], top, 'the panel rests on the roof')
                    self.assertLessEqual(call.args[4], 8, 'the panel does not tower over the building')
                rear = [call for call in panel.call_args_list if call.kwargs.get('rear')]
                self.assertEqual(len(rear), 2, 'only the far-facing signs show their backs')
                self.assertEqual({frozenset((call.args[1], call.args[2])) for call in rear},
                                 {frozenset(((x0, y0), (x1, y0))), frozenset(((x0, y0), (x0, y1)))})

    def test_a_sign_back_draws_metal_supports_without_pasting_the_logo(self):
        cv = city.Cv(s=1)
        x0, y0, x1, _, _, z = city.place_heroes()['codex'].boxes()[-1]
        with mock.patch.object(city, 'skewed', side_effect=AssertionError('a rear face must not draw a logo')):
            city.roof_sign_panel(cv, (x0, y0), (x1, y0), z, 8, (96, 150, 255), city.mascot('codex', 10), rear=True)
        self.assertIn(city.METAL, set(pixels(cv.cls)))
        self.assertNotIn(city.SIGN, set(pixels(cv.cls)))


class Built(unittest.TestCase):
    """One quick build shared by the tests that only read its result."""

    @classmethod
    def setUpClass(cls):
        cls.atlas, cls.data, cls.thumb = city.build(2026, quick=True)
        cls.pictures = {name: cls.atlas.crop((x, y, x + w, y + h)) for name, (x, y, w, h) in cls.data['frames'].items()}

    def test_living_city_uses_visible_real_rooftops_and_pitch(self):
        living = self.data['living']
        self.assertGreaterEqual(len(living['pads']), 3)
        self.assertIn('hospital', {p.get('role') for p in living['pads']})
        self.assertGreaterEqual(len(living['stadiums']), 1)
        self.assertGreaterEqual(len(living['cranes']), 1)
        self.assertGreaterEqual(len(living['markets']), 1)
        self.assertGreaterEqual(len(living['parks']), 1)
        self.assertGreater(len(living['stalls']), 0)
        self.assertGreater(len(living['shelters']), 0)
        self.assertGreaterEqual(len(living['fan_route']), 3)
        self.assertEqual(len(living['bridge_grid']), len(city.BRIDGES))
        self.assertIsNotNone(living['station'])
        ids = self.pictures['idmap'].convert('RGB')
        def owner(point):
            x, y = city.proj(*point)
            r, g, _ = ids.getpixel((round(x), round(y)))
            return r + 256 * g
        buildings, _ = city.make_plan(2026)
        hero_ids = {b.id for b in buildings if b.kind == 'hero'}
        for pad in living['pads']:
            self.assertEqual(owner(pad['point']), pad['id'], 'a pad must not be hidden by another building')
            self.assertNotIn(pad['id'], hero_ids)
        field = living['stadiums'][0]
        x0, y0, x1, y1, z = field['field']
        self.assertGreater(x1, x0); self.assertGreater(y1, y0)
        self.assertEqual(owner(((x0 + x1) / 2, (y0 + y1) / 2, z)), field['id'])

    def test_riverfront_has_distinct_forms_materials_and_heights_on_both_banks(self):
        buildings, _ = city.make_plan(2026)
        front = [b for b in buildings if b.kind == 'city' and b.style.get('riverfront')]
        self.assertTrue(any(b.y1 < city.CANAL[0] for b in front))
        self.assertTrue(any(b.y0 > city.CANAL[1] for b in front))
        self.assertGreaterEqual(len({b.style['arch'] for b in front}), 7)
        self.assertGreaterEqual(len({b.material for b in front}), 3)
        self.assertGreaterEqual(max(b.h for b in front) - min(b.h for b in front), 15)
        for b in front:
            self.assertLessEqual(b.h, city.height_cap(b, city.place_heroes()))

    def test_foreground_has_varied_shapes_and_does_not_hide_the_helipad_support(self):
        buildings, _ = city.make_plan(2026)
        front = [b for b in buildings if b.kind == 'city' and b.style.get('foreground')]
        self.assertGreaterEqual(len(front), 5)
        self.assertGreaterEqual(len({b.style['arch'] for b in front}), 5)
        edge = [b for b in front if b.style.get('foreground_edge')]
        self.assertEqual(len(edge), 3)
        self.assertEqual({b.style['arch'] for b in edge}, {'wedge', 'terrace_block', 'round'})
        pad = next(p for p in self.data['living']['pads'] if p.get('role') == 'garage')
        x, y = city.proj(*pad['point'])
        ids = self.pictures['idmap'].convert('RGB')
        owner = lambda xx, yy: (lambda c: c[0] + 256*c[1])(ids.getpixel((round(xx), round(yy))))
        self.assertGreaterEqual(sum(owner(x, y + dy) == pad['id'] for dy in range(4, 18)), 6,
                                'enough of the supporting building is visible below the roof')

    def test_supporter_route_follows_streets_and_is_partly_visible(self):
        route = self.data['living']['fan_route']
        buildings, heroes = city.make_plan(2026)
        _, covered = city.plan_regions(buildings)
        covered += city.streets_under(heroes)
        ids = self.pictures['idmap'].convert('RGB')
        visible = total = 0
        for a, b in zip(route, route[1:]):
            self.assertTrue(abs(a[0] - b[0]) < 1e-6 or abs(a[1] - b[1]) < 1e-6, 'each segment follows a street')
            steps = max(1, math.ceil(math.dist(a, b) * 3))
            for i in range(steps + 1):
                t = i / steps
                gx, gy = a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t
                self.assertFalse(any(r[0] - .05 <= gx <= r[2] + .05 and r[1] - .05 <= gy <= r[3] + .05 for r in covered))
                x, y = city.proj(gx, gy)
                if 0 <= round(x) < ids.width and 0 <= round(y - 1) < ids.height:
                    rgb = ids.getpixel((round(x), round(y - 1)))
                    visible += rgb[0] + 256 * rgb[1] == 0
                    total += 1
        self.assertGreater(visible / max(1, total), .35, 'supporters should be visible for a meaningful part of the walk')

    def test_industrial_gallery_and_chimney_have_actual_supports(self):
        buildings, _ = city.make_plan(2026)
        b = next(b for b in buildings if getattr(b, 'style', {}).get('arch') == 'silos')
        layout = city.silo_layout(b)
        self.assertEqual(len(layout['stacks']), 3)
        self.assertLess(layout['gallery_z'], min(h for _, _, h in layout['stacks']))
        self.assertGreater(layout['chimney_base'], 0)
        self.assertGreater(layout['chimney_top'], layout['chimney_base'])
        for x, y, h in layout['stacks']:
            self.assertTrue(b.x0 < x < b.x1 and b.y0 < y < b.y1 and h > layout['gallery_z'])

    def test_the_atlas_follows_the_contract_of_the_game_engine(self):
        self.assertLessEqual(self.atlas.width, 4096)
        self.assertLessEqual(self.atlas.height, 4096)
        self.assertIn('frames', self.data)
        for name, (x, y, w, h) in self.data['frames'].items():
            self.assertTrue(0 <= x and 0 <= y and x + w <= self.atlas.width and y + h <= self.atlas.height, name)
        boxes = sorted(self.data['frames'].values())
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertTrue(a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1], f'{a} overlaps {b}')
        self.assertEqual(self.data['size'], list(city.VIEW))
        self.assertLessEqual(city.VIEW[0], 512)
        self.assertLessEqual(city.VIEW[1], 768)
        self.assertTrue(abs(city.VIEW[0] * 3 - 800) <= 2 and abs(city.VIEW[1] * 3 - 1280) <= 2, 'x3 is the tablet panel: that is why this size was chosen')
        self.assertEqual(self.data['world'][0], city.VIEW[0] + 2 * city.MARGIN[0], 'a margin all round for the camera drift')

    def test_every_time_of_day_has_its_pictures(self):
        names = self.data['frames']
        for phase in city.PHASES:
            self.assertEqual(names['city-' + phase][2:], list(city.WORLD))
            self.assertEqual(names['sky-' + phase][2:], [city.WORLD[0], city.SKY_ROWS])
            for n in range(3):
                self.assertIn(f'cloud-{n}-{phase}', names)
        for k in range(city.BUCKETS):
            self.assertEqual(names[f'lights-{k}'][2:], list(city.WORLD))
        self.assertEqual(names['idmap'][2:], list(city.WORLD))
        self.assertEqual(self.data['buckets'], city.BUCKETS)
        self.assertEqual(self.data['phases'], list(city.PHASES))

    def test_the_four_times_of_day_look_different_and_follow_the_sun(self):
        def mean(name):
            picture = self.pictures[name].convert('RGBA')
            r = g = b = n = 0
            for (pr, pg, pb, pa) in pixels(picture.crop((40, 200, 250, 400))):
                if pa > 200:
                    r, g, b, n = r + pr, g + pg, b + pb, n + 1
            return (r + g + b) / (3 * max(1, n)), (r, g, b)
        brightness = {p: mean('city-' + p)[0] for p in city.PHASES}
        self.assertGreater(brightness['day'], brightness['gold'] * 0.9)
        self.assertGreater(brightness['gold'], brightness['blue'])
        self.assertGreater(brightness['blue'], brightness['night'] * 1.2)
        self.assertLess(brightness['night'], 90, 'night is dark')
        gold = mean('city-gold')[1]
        self.assertGreater(gold[0], gold[2], 'golden hour is warm')
        night = mean('city-night')[1]
        self.assertGreater(night[2], night[0], 'night is blue')
        for table in ({p: city.light_table(p) for p in city.PHASES},):
            wall = {p: sum(table[p][city.WALL_R][0]) for p in city.PHASES}
            self.assertTrue(wall['day'] > wall['gold'] > wall['blue'] > wall['night'], wall)

    def test_the_sky_is_transparent_at_the_top_of_the_city_and_solid_below(self):
        for phase in city.PHASES:
            picture = self.pictures['city-' + phase]
            self.assertLess(picture.getpixel((140, 2))[3], 10, 'the very top is sky: the scene draws it behind')
            self.assertEqual(picture.getpixel((140, 330))[3], 255)
        self.assertEqual(self.pictures['sky-day'].getpixel((10, 5))[3], 255)

    def test_window_lights_come_in_ten_batches_that_are_sparse_and_different(self):
        counts = []
        for k in range(city.BUCKETS):
            alpha = self.pictures[f'lights-{k}'].getchannel('A')
            lit = sum(1 for v in pixels(alpha) if v > 60)
            counts.append(lit)
            self.assertLess(lit, alpha.width * alpha.height * 0.08, 'a batch is a scatter of windows, not a wash')
        self.assertTrue(all(c > 40 for c in counts), counts)
        total = sum(counts)
        self.assertTrue(max(counts) < total * 0.3, 'no batch holds most of the windows')
        a = self.pictures['lights-0'].getchannel('A').tobytes()
        b = self.pictures['lights-1'].getchannel('A').tobytes()
        self.assertNotEqual(a, b)

    def test_a_window_stays_inside_its_own_frame_without_a_glow_on_nearby_walls(self):
        size = tuple(n * city.S for n in city.WORLD)
        canvas = SimpleNamespace(s=city.S, albedo=Image.new('RGB', size), ids=Image.new('RGB', size, city.id_colour(7)))
        records = SimpleNamespace(wins=[([(20, 220), (23, 220), (23, 217), (20, 217)], (255, 220, 180), 0, 7, False)])
        layers, kept = city.render_lights(records, canvas)
        self.assertEqual(kept, 1)
        self.assertGreater(layers[0].getpixel((21, 218))[3], 0)
        for point in ((16, 218), (27, 218), (21, 212), (21, 224)):
            self.assertEqual(layers[0].getpixel(point)[3], 0, point)

    def test_the_id_picture_says_which_building_owns_a_pixel(self):
        ids = self.pictures['idmap'].convert('RGB')
        self.assertTrue(all(p[2] == 0 for p in pixels(ids.crop((0, 100, 291, 140)))), 'two channels carry the number')
        seen = {r + 256 * g for r, g, _ in pixels(ids)}
        boxes = self.data['boxes']
        self.assertEqual(boxes[0], None)
        self.assertTrue(max(seen) < len(boxes))
        self.assertIn(0, seen)
        solid = [i for i in seen if i and boxes[i]]
        self.assertGreater(len(solid), 60, 'a dense city')
        for i in solid:
            x0, y0, x1, y1, z0, z1, rail = boxes[i]
            self.assertTrue(x1 > x0 and y1 > y0 and z1 > z0 and rail in (0, 1, 3), boxes[i])
        for name, tower in self.data['towers'].items():
            hero = city.place_heroes()[name]
            front = tower['front']
            owner = ids.getpixel((front[0] - 2 if name != 'small' else front[0] - 4, front[1] - 8))
            self.assertEqual(owner[0] + 256 * owner[1] != 0, True, f'{name}: its own pixels are in the picture')

    def test_the_three_data_buildings_describe_every_window(self):
        towers = self.data['towers']
        self.assertEqual(sorted(towers), ['claude', 'codex', 'small'])
        for name in ('codex', 'claude'):
            tower = towers[name]
            self.assertEqual((tower['floors'], tower['cols'], len(tower['cells'])), (10, 10, 100), 'ten floors of ten windows: one a percent')
            self.assertEqual(tower['rows'], [[1, 3], [5, 7]])
            self.assertEqual(tower['w'], 1)
            for floor in range(10):
                cells = tower['cells'][floor * 10:(floor + 1) * 10]
                self.assertEqual([c[2] for c in cells], [1] * 5 + [-1] * 5, 'left face first, then the right face, from the corner out')
                xs_left, xs_right = [c[0] for c in cells[:5]], [c[0] for c in cells[5:]]
                self.assertEqual(xs_left, sorted(xs_left))
                self.assertEqual(xs_right, sorted(xs_right))
                self.assertLess(xs_left[-1], xs_right[0], 'the left face ends where the right one begins')
                if floor:
                    below = tower['cells'][(floor - 1) * 10:floor * 10]
                    for a, b in zip(below, cells):
                        self.assertTrue(7 <= a[1] - b[1] <= 14, f'{name} floor {floor}: the next floor stays above the last through the setback')
            self.assertTrue(tower['cells'][99][1] < tower['cells'][0][1] - 70, 'floors count from the ground up: the top floor is high above the first')
            self.assertEqual(len(tower['lit']), 3)
            self.assertEqual(len(tower['socket']), 3)
        small = towers['small']
        self.assertEqual((small['floors'], small['cols'], len(small['quota']), len(small['time'])), (5, 8, 40, 40))
        self.assertTrue(all(c[2] == 1 for c in small['quota']) and all(c[2] == -1 for c in small['time']), 'left face quota, right face time')

    def test_unknown_is_a_different_look_from_a_known_empty_building(self):
        for name in ('codex', 'claude', 'small'):
            socket, unknown = self.data['towers'][name]['socket'], self.data['towers'][name]['unknown']
            self.assertGreater(math.dist(socket, unknown), 45, f'{name}: unknown must not look like zero')
        for name in ('codex', 'claude'):
            tower = self.data['towers'][name]
            self.assertGreater(math.dist(tower['lit'], tower['unknown']), 80)

    def test_the_windows_are_drawn_on_whole_pixels_inside_the_building(self):
        owners = self.pictures['idmap'].convert('RGB')
        for name in ('codex', 'claude'):
            tower = self.data['towers'][name]
            box = tower['box']
            front = tower['front']
            owner = owners.getpixel((front[0] - 2, front[1] - 8))
            image = Image.new('RGBA', (city.WORLD[0], city.WORLD[1]), (0, 0, 0, 0))
            city.draw_tower(image, tower, 37)
            lit = tower['lit'], tower['lit_left']
            counts = {'lit': 0, 'dark': 0}
            for i, (x, yb, s) in enumerate(tower['cells']):
                top = math.floor(yb - tower['rows'][0][1] + .5)
                colour = image.getpixel((x, top))
                self.assertEqual(colour[3], 255, f'{name} cell {i} is drawn')
                if i < 37:
                    strength = (1, 1, .95, 1, .9, 1, .97, 1)[i % 8]
                    base = lit[1] if s > 0 else lit[0]
                    self.assertEqual(list(colour[:3]), [math.floor(c * strength + .5) for c in base], f'{name} cell {i} lit')
                    counts['lit'] += 1
                else:
                    self.assertEqual(list(colour[:3]), tower['socket'], f'{name} cell {i} dark')
                    counts['dark'] += 1
                self.assertTrue(box[0] <= x and x + tower['w'] <= box[2] and box[1] <= top and top + 4 <= box[3], f'{name} cell {i} is inside its box')
                for lo, hi in tower['rows']:
                    row_top = math.floor(yb - hi + .5)
                    for yy in range(row_top, row_top + hi - lo):
                        self.assertEqual(owners.getpixel((x, yy)), owner, f'{name} cell {i} belongs to its tower, including at the setback')
            self.assertEqual(counts, {'lit': 37, 'dark': 63})
        for lit in (0, 1, 100):
            image = Image.new('RGBA', city.WORLD, (0, 0, 0, 0))
            city.draw_tower(image, self.data['towers']['codex'], lit)
            on = sum(1 for (x, yb, s) in self.data['towers']['codex']['cells'] if list(image.getpixel((x, math.floor(yb - self.data['towers']['codex']['rows'][0][1] + .5)))[:3]) != self.data['towers']['codex']['socket'])
            self.assertEqual(on, lit)

    def test_the_five_hour_building_draws_its_two_faces_apart(self):
        small = self.data['towers']['small']
        image = Image.new('RGBA', city.WORLD, (0, 0, 0, 0))
        city.draw_tower(image, small, 11, 'quota')
        city.draw_tower(image, small, 16, 'time')
        for mode, lit in (('quota', 11), ('time', 16)):
            on = 0
            for (x, yb, s) in small[mode]:
                pixel = image.getpixel((x, math.floor(yb - small['rows'][0][1] + .5)))
                on += tuple(pixel[:3]) in (tuple(small['lit_quota']), tuple(small['lit_time']))
            self.assertEqual(on, lit, mode)

    def test_the_numbers_for_the_traffic_the_water_and_the_rail_make_sense(self):
        data = self.data
        self.assertGreater(len(data['lanes']), 12)
        self.assertGreater(len(data['walks']), 10)
        self.assertGreaterEqual(len(data['boats']), 2)
        for lane in data['lanes']:
            self.assertIn(lane['axis'], ('x', 'y'))
            self.assertIn(lane['sign'], (1, -1))
            along = 0 if lane['axis'] == 'x' else 1
            self.assertEqual(lane['a'][1 - along], lane['b'][1 - along], 'a straight lane')
            self.assertEqual((lane['b'][along] - lane['a'][along]) > 0, lane['sign'] > 0, 'a to b is the way the traffic goes')
            for stop, light in lane['cross']:
                self.assertTrue(0 < stop < abs(lane['b'][along] - lane['a'][along]) and 0 <= light < len(data['lights']), lane)
        c0, c1 = city.CANAL
        for lane in data['lanes'] + [w for w in data['walks'] if w['axis'] != 'p']:
            for gx, gy in (lane['a'], lane['b']):
                if lane['axis'] == 'y' and c0 <= gy < c1:
                    self.assertIn(round((gx - .32) / 5), [round((gx - .08) / 5)] + list(city.BRIDGES), f'a street over the canal is a bridge: {lane}')
        for lane in data['lanes']:
            for gx, gy in (lane['a'], lane['b']):
                self.assertFalse(lane['axis'] == 'y' and c0 < gy < c1 and int(gx // 5) not in city.BRIDGES, f'nothing drives on the water: {lane}')
        for boat in data['boats']:
            for gx, gy in (boat['a'], boat['b']):
                self.assertTrue(c0 < gy < c1, 'boats sail in the canal')
            self.assertTrue(set(boat['kinds']) <= set('fst'))
        self.assertEqual(len(data['bridges']), len(city.BRIDGES))
        self.assertTrue(all(len(q) == 4 for q in data['bridges']))
        rail = data['rail']
        self.assertTrue(rail['a'][0] < rail['b'][0] and rail['z'] > 8)
        self.assertEqual(rail['a'][1], city.RAIL_Y)
        self.assertLessEqual(len(data['poke']), 2600)
        for x, y, w, h in data['poke']:
            self.assertTrue(0 <= x < city.WORLD[0] and 40 <= y < city.WORLD[1] and w >= 1 and h >= 1)
        self.assertGreater(len(data['beacons']), 8)
        self.assertGreater(len(data['screens']), 3)
        self.assertGreater(len(data['fountains']), 2)
        self.assertEqual(data['canal'], list(city.CANAL))
        self.assertTrue(40 <= data['place']['lat'] <= 42 and 1 <= data['place']['lon'] <= 3, 'Barcelona by default')

    def test_the_visible_band_is_a_dense_city_with_no_open_water(self):
        # rows 0 .. 247 of the native picture (the engine's view.bottom above the glass dock) and the whole picture, from the prepared numbers
        data, width = self.data, city.WORLD[0]
        top = city.MARGIN[1]
        band = range(top, top + 248)
        water = sum(data['waterRows'][y] for y in band)
        built = sum(data['buildingRows'][y] for y in band)
        total = width * len(band)
        self.assertEqual(len(data['waterRows']), city.WORLD[1])
        self.assertLess(water / total, 0.01, 'almost no open water above the dock')
        self.assertGreater(built / total, 0.6, 'buildings fill the visible band')
        # The continuous park opens a little more space between the
        # foreground buildings, but no row may become an empty strip.
        self.assertTrue(all(data['buildingRows'][y] > width * 0.10 for y in range(top + 50, top + 248)), 'buildings in every row below the horizon haze')
        self.assertGreater(sum(data['waterRows']), 3 * width, 'the canal is there, in the picture mode')
        self.assertLess(sum(data['waterRows']) / (width * city.WORLD[1]), 0.08)
        self.assertEqual(max(data['waterRows'][y] for y in band), 0, 'not one pixel of water in the band')
        inside = [lane for lane in data['lanes'] if city.proj(*lane['a'])[1] < top + 248 and city.proj(*lane['b'])[1] < top + 248]
        self.assertGreaterEqual(len(inside), 8, 'traffic on streets that are in the visible band')

    def test_the_thumbnail_is_the_pickers_size(self):
        self.assertEqual(self.thumb.size, (240, 160))
        self.assertEqual(self.thumb.mode, 'RGB')

    def test_the_whole_json_fits_what_the_server_allows(self):
        self.assertLess(len(json.dumps(self.data, separators=(',', ':')).encode()), 512 * 1024)


class Round3(unittest.TestCase):
    """Tony, 2026-11-10: more detail, parks that differ and are real, vehicles at scale, no fog over the far buildings, many tall towers behind, and the five-hour
    building standing on its block instead of floating over a street, lower and quieter."""

    @classmethod
    def setUpClass(cls):
        if not hasattr(Built, 'data'):
            Built.setUpClass()
        cls.buildings, cls.heroes = city.make_plan(2026)
        cls.cv, cls.rec = city.paint_world(cls.buildings, cls.heroes, s=2)

    # ------------------------------------------------------------------------------------------------------------------ the five-hour building
    def test_each_data_building_stands_inside_one_block_with_no_street_under_it(self):
        for name, hero in self.heroes.items():
            bx, by = int(hero.x0 // 5), int(hero.y0 // 5)
            self.assertTrue(5 * bx + 1 - 1e-6 <= hero.x0 and hero.x1 <= 5 * bx + 5 + 1e-6 and 5 * by + 1 - 1e-6 <= hero.y0 and hero.y1 <= 5 * by + 5 + 1e-6,
                            f'{name}: footprint {hero.x0, hero.y0, hero.x1, hero.y1} must fit inside one lot')
            for m in range(-4, 30):
                self.assertFalse(hero.x0 < 5 * m + 1 - 1e-6 and hero.x1 > 5 * m + 1e-6, f'{name} straddles street x = {5 * m}')
                self.assertFalse(hero.y0 < 5 * m + 1 - 1e-6 and hero.y1 > 5 * m + 1e-6, f'{name} straddles street y = {5 * m}')
            for b in self.buildings:
                if b is not hero and b.kind != 'rail':
                    self.assertTrue(b.x1 <= hero.x0 + 1e-6 or b.x0 >= hero.x1 - 1e-6 or b.y1 <= hero.y0 + 1e-6 or b.y0 >= hero.y1 - 1e-6,
                                    f'{name}: a {b.kind} overlaps the tower lot')

    def test_no_vehicle_lane_and_no_walk_passes_under_a_data_building(self):
        for name, hero in self.heroes.items():
            for lane in Built.data['lanes'] + [w for w in Built.data['walks'] if w['axis'] != 'p']:
                along = 0 if lane['axis'] == 'x' else 1
                fixed = lane['a'][1 - along]
                lo, hi = sorted((lane['a'][along], lane['b'][along]))
                box = (hero.x0, hero.x1) if along == 0 else (hero.y0, hero.y1)
                across = (hero.y0, hero.y1) if along == 0 else (hero.x0, hero.x1)
                crosses = across[0] + 1e-6 < fixed < across[1] - 1e-6 and lo < box[1] - 1e-6 and hi > box[0] + 1e-6
                self.assertFalse(crosses, f'a {lane["axis"]} lane at {fixed} runs through the {name} building: {lane}')

    def test_the_five_hour_building_touches_the_ground_of_its_lot_and_nothing_else_is_on_it(self):
        hero = self.heroes['small']
        for b in self.buildings:
            if b is not hero and b.kind != 'rail':
                self.assertTrue(b.x1 <= hero.x0 + 1e-6 or b.x0 >= hero.x1 - 1e-6 or b.y1 <= hero.y0 + 1e-6 or b.y0 >= hero.y1 - 1e-6,
                                f'a {b.kind} block overlaps the lot of the five-hour building')
        ids = Built.pictures['idmap'].convert('RGB')
        fx, fy = Built.data['towers']['small']['front']
        def owner(x, y):
            r, g, _ = ids.getpixel((x, y))
            return r + 256 * g
        mine = owner(fx - 1, fy - 3)
        self.assertNotEqual(mine, 0, 'the walls come down to the front corner')
        self.assertEqual(owner(fx, fy + 3), 0, 'below the front corner there is the ground of the crossing, not a wall')
        for dx in (-9, 9):                                                               # and along both walls the base is on the ground line: just under it is no building
            x = fx + dx
            base_y = fy - abs(dx) / 2
            self.assertEqual(owner(x, int(base_y) - 2), mine, 'the wall stands there')
            self.assertEqual(owner(x, int(base_y) + 4), 0, 'the street is under the wall, not a second building')

    def test_the_five_hour_building_is_low_and_quiet(self):
        hero = self.heroes['small']
        tower = self.heroes['codex']
        self.assertLessEqual(hero.top, 36, 'about thirty pixels: lower than a data tower (ninety)')
        self.assertLess(hero.top, tower.top / 2)
        x0, y0, x1, y1 = hero.screen_box()
        self.assertLess(y1 - y0, hero.top + 40, 'no sign or billboard above it: the box holds only the building and its roof machinery')
        self.assertEqual(Built.data['towers']['small']['floors'], 5)
        self.assertEqual(Built.data['towers']['small']['cols'], 8)
        self.assertEqual(len(Built.data['towers']['small']['quota']), 40)
        self.assertEqual(len(Built.data['towers']['small']['time']), 40)
        walls = city.HERO_WALL['small']
        self.assertLess(max(walls[1]), 150, 'a calm, dark grey: the two big towers are the stars')
        for x, y, s in Built.data['towers']['small']['quota'] + Built.data['towers']['small']['time']:
            self.assertTrue(hero.front[0] - 24 <= x and x + 2 <= hero.front[0] + 24 + 1, 'every window is on one of its two faces')

    # --------------------------------------------------------------------------------------------------------------------------------- the parks
    def test_the_parks_differ_from_one_another(self):
        designs = [r.design for r in self.rec.regions]
        self.assertGreaterEqual(len(set(designs)), 7, sorted(set(designs)))
        for design in ('great_park', 'sports', 'formal', 'plaza', 'market', 'pocket', 'garden', 'boulevard'):
            self.assertIn(design, designs)
        big = [r for r in self.rec.regions if r.design == 'great_park']
        self.assertEqual(len(big), 1)
        self.assertEqual(len(big[0].blocks), 4, 'the park keeps four connected blocks and the streets between them')
        planned = [block for _, blocks in city.REGION_PLAN for block in blocks]
        self.assertEqual(len(planned), len(set(planned)), 'planned parks do not overlap')
        kinds = {item[0] for r in self.rec.regions for item in r.items}
        for kind in ('tree', 'bench', 'lamp', 'swing', 'slide', 'goal', 'net', 'hoop', 'stall', 'table', 'gazebo', 'topiary'):
            self.assertIn(kind, kinds)
        species = {item[3] for r in self.rec.regions for item in r.items if item[0] == 'tree'}
        self.assertGreaterEqual(len(species), 8, 'trees of many kinds')
        self.assertTrue(set(species) <= set(city.TREES))
        self.assertGreater(len(self.rec.fountains), 6)

    def test_trees_have_a_shadow_and_a_volume_and_a_height_of_their_own(self):
        self.assertGreater(len(self.rec.trees), 500, 'a city of trees')
        heights = {round(h, 1) for _, _, _, h, _ in self.rec.trees}
        self.assertGreater(len(heights), 40, 'no two trees alike in height')
        masks = city.shadow_masks(self.buildings, self.rec.trees, scale=1)
        with_trees = sum(1 for v in pixels(masks['gold']) if v > 60)
        without = sum(1 for v in pixels(city.shadow_masks(self.buildings, (), scale=1)['gold']) if v > 60)
        self.assertGreater(with_trees, without + 400, 'the trees cast their shadow in the light of the low sun')

    def test_no_tree_stands_in_front_of_a_data_building(self):
        from PIL import ImageDraw  # noqa: F401  (the canvas below is the script's own)
        for name, hero in self.heroes.items():
            cv, rec = city.Cv(city.WORLD, 1), city.Rec()
            gx, gy = (hero.x0 + hero.x1) / 2 + 1.2, hero.y1 + .8                       # in front of the data building, on the screen box that must stay clear
            self.assertTrue(city.in_keep(city.proj(gx, gy), 0), name)
            city.paint_item(cv, rec, ('tree', gx, gy, 'oak', 1.0))
            self.assertIsNone(cv.cls.getbbox(), f'a tree was painted in front of the {name} building')
        cv, rec = city.Cv(city.WORLD, 1), city.Rec()
        city.paint_item(cv, rec, ('tree', 45.0, 58.0, 'oak', 1.0))                       # and one far from them is painted, with a shadow to come
        self.assertIsNotNone(cv.cls.getbbox())
        self.assertEqual(len(rec.trees), 1)

    def test_the_props_of_a_block_are_painted_in_front_of_what_is_behind_and_behind_what_is_in_front(self):
        # a prop belongs to the block it stands in (the street that leads into a block is its own), so it is painted with that block, in the painters' order
        self.assertEqual(city.block_of(41.5, 26.2), (8, 5))
        self.assertEqual(city.block_of(40.5, 26.2), (8, 5), 'the street that leads into a block belongs to it')
        self.assertEqual(city.block_of(45.5, 30.5), (9, 6))

    # ---------------------------------------------------------------------------------------------------------------- the back of the city, the haze
    def test_many_tall_towers_stand_behind_the_data_buildings(self):
        behind = [b for b in self.buildings if b.kind == 'city' and 78 <= city.proj(b.x1, b.y1)[1] < 150]       # the rows behind the data buildings
        tall = [b for b in behind if b.h >= 60]
        self.assertGreater(len(behind), 30)
        self.assertGreaterEqual(len(tall), 22, 'a dense downtown going away: most of the back rows are tall towers')
        self.assertGreater(len([b for b in behind if b.h >= 80]), 12, 'and a good number are skyscrapers')
        tops = sorted(city.proj(b.x1, b.y1)[1] - b.h for b in tall)
        self.assertLess(tops[0], 40, 'the tallest reach almost to the top of the picture')
        self.assertGreater(len([t for t in tops if t < 60]), 10, 'and a whole row of them')
        crowns = {b.style.get('crown') for b in tall}
        self.assertGreaterEqual(len(crowns & {'spire', 'mast', 'pyramid', 'dome', 'twin', 'lantern'}), 2, 'distinct crowns on the skyline')
        for name in ('codex', 'claude'):
            hero = self.heroes[name]
            for b in self.buildings:
                if b.kind == 'city':
                    fx, fy = city.proj(b.x1, b.y1)
                    if math.hypot(fx - hero.front[0], (fy - hero.front[1]) * 1.6) < 95:
                        self.assertLess(b.h, hero.top, 'a neighbour of a data tower is never as tall as it')

    def test_the_far_buildings_keep_their_colours_contrast_and_lights(self):
        def stats(phase, r0, r1):
            picture = Built.pictures['city-' + phase]
            lum, sat = [], []
            for y in range(r0, r1):
                for x in range(picture.width):
                    r, g, b, a = picture.getpixel((x, y))
                    if a > 200:
                        lum.append(.3 * r + .59 * g + .11 * b)
                        sat.append(max(r, g, b) - min(r, g, b))
            return sum(lum) / len(lum), sum(sat) / len(sat)
        for phase in ('day', 'gold'):
            far, near = stats(phase, 30, 70), stats(phase, 150, 230)
            self.assertLess(far[0], near[0] * 1.45, f'{phase}: the far rows are not washed to the colour of the sky')
            self.assertLess(far[1], near[1] * 1.9, f'{phase}: no orange-grey wash over the far rows')
        far_windows = sum(1 for k in range(city.BUCKETS) for v in pixels(Built.pictures[f'lights-{k}'].getchannel('A').crop((0, 30, 291, 80))) if v > 120)
        self.assertGreater(far_windows, 300, 'the lit windows of the far towers are still lit')

    def test_the_haze_table_is_thin_and_every_time_of_day_has_one(self):
        self.assertEqual(sorted(city.HAZE), sorted(city.PHASES))
        for phase, (tint, amount) in city.HAZE.items():
            self.assertLessEqual(amount, .4, phase)

    def test_the_far_skyline_is_the_same_at_every_time_of_day(self):
        # the towers come from one seed: only their colours and their lights change, so the cross-fade between two times of day never moves a tower
        from PIL import ImageDraw
        masks = []
        for phase in city.PHASES:
            image = Image.new('RGB', (city.WORLD[0] * city.S, city.SKY_ROWS * city.S), (0, 0, 0))
            city.far_skyline(ImageDraw.Draw(image), phase, __import__('random').Random(f'skyline:{phase}'))
            masks.append(image.convert('L').point(lambda v: 255 if v else 0).tobytes())
        self.assertTrue(all(m == masks[0] for m in masks), 'the same silhouette at every hour')
        covered = sum(1 for v in masks[0] if v) / len(masks[0])
        self.assertGreater(covered, .15, 'a skyline, not a thin line')

    # --------------------------------------------------------------------------------------------------------------------------- street life
    def test_a_fountain_beside_a_building_does_not_glow_on_its_wall(self):
        fountains = Built.data['fountains']
        self.assertTrue(all(len(f) == 3 and f[2] in (0, 1) for f in fountains))
        self.assertGreater(sum(f[2] for f in fountains), 2, 'fountains in the open glow at dusk')
        self.assertLess(sum(f[2] for f in fountains), len(fountains), 'the ones against a wall do not (the jet is clipped by the scene)')

    def test_the_streets_have_trees_shelters_parked_cars_and_planters(self):
        buildings = self.buildings
        props = {}
        city.street_props(buildings, [], props)
        kinds = {item[0] for items in props.values() for item in items}
        self.assertTrue({'tree', 'busstop', 'parked', 'planter'} <= kinds, kinds)
        self.assertGreater(sum(1 for items in props.values() for item in items if item[0] == 'parked'), 150)
        self.assertGreater(sum(1 for items in props.values() for item in items if item[0] == 'tree'), 200)


class Variety(unittest.TestCase):
    """Tony, 2026-11-10 (second round): "most of the buildings are too alike, in front of and behind the main ones". The city is now made of archetypes (an old tenement, an
    art-deco tower, a glass slab, a pastel block, a warehouse, a flat-iron, a courtyard block, a round or twisted tower, a church, a city hall, a stadium, a station ...)
    in schemes (palettes), by district. These tests measure that, not how it looks."""

    @classmethod
    def setUpClass(cls):
        cls.buildings, cls.heroes = city.make_plan(2026)
        cls.city = [b for b in cls.buildings if b.kind == 'city']

    @staticmethod
    def centre(b):
        return city.proj((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)

    def visible(self):
        """The buildings of the rows above the dock (rows 0-247 of the picture, which are world rows 12-259) and inside the picture."""
        return [b for b in self.city if 30 <= city.proj(b.x1, b.y1)[1] <= 270 and 0 <= self.centre(b)[0] <= 291]

    def shares(self, group, key):
        counts = {}
        for b in group:
            counts[b.style[key]] = counts.get(b.style[key], 0) + 1
        return counts

    def test_every_building_has_an_archetype_and_a_scheme_and_there_are_many_kinds(self):
        for b in self.city:
            self.assertIn(b.style.get('arch'), city.MATERIAL_OF.keys() | set(city.LANDMARKS), b.seed())
            self.assertIn(b.style.get('scheme'), city.SCHEMES)
        arch = self.shares(self.city, 'arch')
        self.assertGreaterEqual(len(arch), 22, sorted(arch))
        self.assertGreaterEqual(len(self.shares(self.visible(), 'arch')), 16, 'many kinds in the rows above the dock alone')
        self.assertGreaterEqual(len(self.shares(self.city, 'scheme')), 30)
        self.assertGreaterEqual(len(self.shares(self.visible(), 'scheme')), 20)
        self.assertGreaterEqual(len({b.style.get('roof_colour') for b in self.city}), 10, 'roofs of many colours')
        self.assertGreaterEqual(len({b.style.get('facade') for b in self.city}), 6, 'facades of many kinds')

    def test_visible_codex_neighbours_have_three_distinct_forms_in_the_same_lots(self):
        accents = [b for b in self.city if b.style.get('codex_accent')]
        self.assertEqual(len(accents), 4)
        self.assertEqual({b.style['arch'] for b in accents}, {'glass_slab', 'wedge', 'twin', 'tapered'})
        mirror = next(b for b in accents if b.style.get('facade') == 'mirror')
        self.assertEqual((mirror.x0, mirror.y0, mirror.x1, mirror.y1), (26, 41, 30, 45))
        self.assertEqual(mirror.material, 'glass')
        self.assertEqual(mirror.tiers, 1, 'the reflective facade stays continuous')
        self.assertLess(mirror.h, self.heroes['codex'].top)
        right = next(b for b in self.city if b.style.get('codex_flank'))
        self.assertEqual(right.style['arch'], 'round')
        self.assertTrue(right.style['round_ribbon'])
        self.assertLessEqual(right.lit, .10, 'ordinary lights stay subordinate to the quota tower')
        self.assertNotEqual(right.style['arch'], mirror.style['arch'], 'the two sides of Codex must have visibly different volumes')
        mirrors = [b for b in self.city if b.style.get('facade') == 'mirror']
        self.assertGreaterEqual(len(mirrors), 2, 'more than one building uses mirror glass')
        self.assertTrue(any(b.style.get('mirror_accent') for b in mirrors))

    def test_facade_details_are_varied_across_the_city_and_neighbours(self):
        ordinary = [b for b in self.city if not b.style.get('landmark')]
        self.assertGreaterEqual(len(ordinary), 150)
        self.assertTrue(all(b.style.get('detail') for b in ordinary))
        self.assertGreaterEqual(len({b.style['detail'] for b in ordinary}), 7)
        pairs = same = 0
        for i, p in enumerate(ordinary):
            for q in ordinary[i+1:]:
                distance = abs((p.x0+p.x1-q.x0-q.x1)/2) + abs((p.y0+p.y1-q.y0-q.y1)/2)
                if distance < 7:
                    pairs += 1
                    same += p.style['detail'] == q.style['detail']
        self.assertGreater(pairs, 100)
        self.assertLess(same / pairs, .10, 'neighbours should not repeat the same detail')

    def test_each_facade_detail_changes_the_rendered_material(self):
        import random
        b = city.Building(26, 41, 30, 45, 42, 'glass')
        b.id, b.lit = 5, .5
        base = city.faces_base(b.x0, b.y0, b.x1, b.y1)[0]
        def painted(detail):
            cv, rec = city.Cv(city.WORLD, 2), city.Rec()
            cv.bid = b.id
            style = city.base_style('glass_steel', random.Random(3))
            style.update(facade='classic', detail=detail, detail_phase=1)
            city.paint_face(cv, rec, b, base, 0, b.h, city.FLOOR, 0, style, random.Random(19), windows=True)
            return cv.albedo
        plain = painted(None)
        for detail in ('vertical_fins', 'horizontal_bands', 'framed_bays', 'recessed_edge', 'sunshades', 'stone_courses', 'glass_reflection'):
            with self.subTest(detail=detail):
                self.assertIsNotNone(ImageChops.difference(plain, painted(detail)).getbbox(), 'the detail must affect actual pixels')

    def test_mirror_is_a_glass_skin_and_keeps_a_few_real_light_panels(self):
        import random
        b = city.Building(26, 41, 30, 45, 49, 'glass'); b.id = 5; b.lit = .5
        base = city.faces_base(b.x0, b.y0, b.x1, b.y1)[0]
        cv, rec = city.Cv(city.WORLD, 2), city.Rec(); cv.bid = b.id
        style = city.base_style('glass_pearl', random.Random(2)); style['facade'] = 'mirror'
        city.paint_face(cv, rec, b, base, 0, b.h, city.FLOOR, 0, style, random.Random(2), windows=True)
        self.assertGreater(sum(v == city.GLASS_L for v in pixels(cv.cls)), 500)
        self.assertGreater(len(rec.wins), 0)
        self.assertLess(len(rec.wins), 10, 'a mirror has a few lit rooms, not the usual dense grid')
        self.assertTrue(all(win[3] == b.id for win in rec.wins))

    def test_mirror_near_codex_has_no_large_animated_billboard(self):
        b = next(b for b in self.city if b.style.get('codex_accent') and b.style.get('facade') == 'mirror')
        with mock.patch.object(city, 'led_wall') as billboard:
            city.paint_building(city.Cv(city.WORLD, 1), city.Rec(), b)
        billboard.assert_not_called()

    def test_ribbon_accent_changes_one_face_without_losing_windows(self):
        import random
        b = next(b for b in self.city if b.style.get('ribbon_accent'))
        base = city.faces_base(b.x0, b.y0, b.x1, b.y1)[1]
        def render(ribbon):
            cv, rec = city.Cv(city.WORLD, 2), city.Rec(); cv.bid = b.id
            style = dict(b.style)
            if not ribbon:
                style.pop('ribbon_side', None)
            city.paint_face(cv, rec, b, base, 0, b.h, city.FLOOR, 1, style, random.Random(9), windows=True)
            return cv.albedo, rec
        plain, a = render(False); striped, b_rec = render(True)
        self.assertIsNotNone(ImageChops.difference(plain, striped).getbbox())
        self.assertEqual(len(a.wins), len(b_rec.wins), 'decorative glazing does not remove night lighting')

    def test_no_kind_and_no_palette_takes_over_the_city(self):
        for label, group, arch_limit, scheme_limit in (('city', self.city, .18, .10), ('the rows above the dock', self.visible(), .20, .12)):
            for key, limit in (('arch', arch_limit), ('scheme', scheme_limit)):
                counts = self.shares(group, key)
                top, n = max(counts.items(), key=lambda it: it[1])
                self.assertLessEqual(n / len(group), limit, f'{label}: {top} is {n} of {len(group)} buildings ({key})')

    def test_neighbours_seldom_look_alike(self):
        for label, group in (('city', self.city), ('above the dock', self.visible())):
            pairs = same = same_arch = 0
            for i, p in enumerate(group):
                for q in group[i + 1:]:
                    if abs((p.x0 + p.x1) / 2 - (q.x0 + q.x1) / 2) + abs((p.y0 + p.y1) / 2 - (q.y0 + q.y1) / 2) < 8.5:
                        pairs += 1
                        same += p.style['arch'] == q.style['arch'] and p.style['scheme'] == q.style['scheme']
                        same_arch += p.style['arch'] == q.style['arch']
            self.assertGreater(pairs, 100)
            self.assertLessEqual(same / pairs, .03, f'{label}: neighbours with the same archetype AND palette')
            self.assertLessEqual(same_arch / pairs, .16, f'{label}: neighbours of the same archetype')

    def test_the_forms_of_the_footprints_and_roofs_differ(self):
        forms = [b for b in self.city if b.style['arch'] in ('wedge', 'round', 'twisted', 'tapered', 'ziggurat', 'twin', 'L_block', 'courtyard', 'pyramid_tower', 'terrace_block', 'offset_tower')]
        self.assertGreaterEqual(len(forms), 22, 'plenty of buildings that are not a plain box')
        self.assertGreaterEqual(len({b.style['arch'] for b in forms}), 7)
        crowns = {b.style.get('crown') for b in self.city}
        self.assertGreaterEqual(len(crowns), 8, sorted(crowns, key=str))
        heights = sorted(round(b.h) for b in self.city)
        self.assertGreater(len(set(heights)), 40, 'heights are not a few steps')

    def test_distinct_silhouettes_in_the_back_middle_and_front(self):
        forms = {'wedge', 'round', 'twisted', 'tapered', 'ziggurat', 'twin', 'L_block', 'courtyard',
                 'pyramid_tower', 'terrace_block', 'offset_tower'}
        for low, high in ((30, 150), (150, 270), (270, 440)):
            group = [b for b in self.city if low <= city.proj(b.x1, b.y1)[1] < high and 0 <= self.centre(b)[0] <= 291]
            distinctive = [b for b in group if b.style['arch'] in forms or b.style.get('landmark')]
            self.assertGreaterEqual(len(distinctive) / len(group), .30, f'{low}-{high}: silhouette variety')
            self.assertGreaterEqual(len({b.style['arch'] for b in distinctive}), 4)

    def test_new_terraced_and_offset_buildings_are_visible(self):
        counts = self.shares(self.visible(), 'arch')
        self.assertGreaterEqual(counts.get('terrace_block', 0), 2)
        self.assertGreaterEqual(counts.get('offset_tower', 0), 2)

    def test_landmarks_are_scattered_over_the_picture_so_the_eye_finds_them(self):
        landmarks = [b for b in self.city if b.style.get('landmark')]
        self.assertEqual(len({b.style['arch'] for b in landmarks}), 9, [b.style['arch'] for b in landmarks])
        for arch in ('church', 'city_hall', 'stadium', 'market_hall', 'station', 'hospital', 'garage', 'mall', 'silos'):
            self.assertTrue(any(b.style['arch'] == arch for b in landmarks), arch)
        special = [b for b in self.visible() if b.style.get('landmark') or b.style['arch'] in ('wedge', 'round', 'twisted', 'tapered', 'ziggurat', 'pyramid_tower', 'twin', 'terrace_block', 'offset_tower')]
        thirds = {0: 0, 1: 0, 2: 0}
        halves = {0: 0, 1: 0}
        for b in special:
            cx, cy = self.centre(b)
            thirds[0 if cx < 100 else 1 if cx < 190 else 2] += 1
            halves[0 if cy < 150 else 1] += 1
        self.assertTrue(all(v >= 3 for v in thirds.values()), f'a memorable building in the left, the middle and the right of the picture: {thirds}')
        self.assertTrue(all(v >= 3 for v in halves.values()), f'and in the front rows as well as the back rows: {halves}')
        for b in landmarks:
            self.assertLess(b.h, 70, 'a landmark never outgrows the data towers')

    def test_low_civic_landmarks_do_not_hide_the_data_towers(self):
        for block, arch, max_height in (((9, 8), 'stadium', 30), ((8, 8), 'market_hall', 14)):
            matches = [b for b in self.city if city.block_of(b.x0 + .01, b.y0 + .01) == block]
            self.assertEqual(len(matches), 1, block)
            b = matches[0]
            self.assertEqual(b.style['arch'], arch)
            self.assertLessEqual(b.h, max_height)
            x0, y0, x1, y1 = b.bbox()
            for name, hero in self.heroes.items():
                hx0, hy0, hx1, hy1 = hero.screen_box()
                self.assertTrue(x1 < hx0 or x0 > hx1 or y1 < hy0 or y0 > hy1,
                                f'{arch} hides {name}')

    def test_central_block_has_volume_and_neighbourhood_buildings_leave_heroes_clear(self):
        central = [b for b in self.city if (b.x0, b.y0, b.x1, b.y1) == (31, 36, 35, 40)]
        self.assertEqual(len(central), 1)
        self.assertEqual(central[0].style['arch'], 'round')
        self.assertEqual(central[0].style['scheme'], 'glass_titanium')
        self.assertTrue(central[0].style.get('codex_flank'))
        added = [b for b in self.city if b.style.get('neighbourhood')]
        self.assertGreaterEqual(len(added), 3)
        self.assertGreaterEqual(len({b.style['arch'] for b in added}), 3)
        for b in added:
            for hero in self.heroes.values():
                x0, y0, x1, y1 = b.bbox()
                hx0, hy0, hx1, hy1 = hero.screen_box()
                self.assertTrue(x1 < hx0 or x0 > hx1 or y1 < hy0 or y0 > hy1)

    def test_the_back_rows_are_varied_too(self):
        tall = [b for b in self.city if 78 <= city.proj(b.x1, b.y1)[1] < 150 and b.h >= 60]
        self.assertGreaterEqual(len(tall), 20)
        self.assertGreaterEqual(len({b.style['arch'] for b in tall}), 7, 'different shapes behind the data buildings')
        self.assertGreaterEqual(len({b.style['scheme'] for b in tall}), 12, 'different colours')
        self.assertGreaterEqual(len({b.style.get('crown') for b in tall}), 4, 'different crowns')
        self.assertGreaterEqual(len({round(b.h / 8) for b in tall}), 5, 'different heights')
        widths = {round(b.x1 - b.x0, 1) + 10 * round(b.y1 - b.y0, 1) for b in tall}
        self.assertGreaterEqual(len(widths), 4, 'different footprints')

    def test_each_district_is_a_place_with_several_kinds_of_building(self):
        districts = {}
        for b in self.city:
            districts.setdefault(b.style['district'], []).append(b)
        for name in ('old', 'glass', 'res', 'comm', 'ind'):
            group = districts[name]
            self.assertGreaterEqual(len(group), 15, name)
            self.assertGreaterEqual(len({b.style['arch'] for b in group}), 5, f'{name}: {sorted({b.style["arch"] for b in group})}')
            self.assertGreaterEqual(len({b.style['scheme'] for b in group}), 5, name)
        res = {b.style['scheme'] for b in districts['res']}
        neutral = {name for name in city.SCHEMES if name.startswith(('stone_', 'concrete_', 'brick_'))} | {'whitewash', 'limestone', 'sandstone'}
        self.assertGreaterEqual(len(res & neutral), 5, 'residential walls use several stone, brick and concrete finishes')
        glasses = {name for name in city.SCHEMES if name.startswith('glass_')}
        self.assertGreaterEqual(len({b.style['scheme'] for b in districts['glass']} & glasses), 5,
                                'the glass downtown has several distinct glass finishes')
        self.assertTrue({b.style['scheme'] for b in districts['old']} & {'brick_red', 'brick_orange', 'brick_brown'}, 'warm brick in the old town')
        warehouses = [b for b in districts['ind'] if b.style['arch'] == 'warehouse']
        self.assertGreaterEqual(len(warehouses), 6, 'warehouses by the canal')
        self.assertLessEqual(max(b.h for b in districts['ind']), 60, 'the industrial edge is low (silos and a chimney aside)')

    def test_structure_and_material_replace_loud_district_colours(self):
        schemes = {b.style['scheme'] for b in self.city}
        self.assertFalse(schemes & {'magenta', 'cyan', 'red', 'orange', 'yellow', 'mint', 'pink', 'lemon', 'lilac'})
        facades = {b.style.get('facade') for b in self.city}
        self.assertTrue({'braced', 'curtain', 'vertical', 'balcony'} <= facades)

    def test_data_buildings_are_not_archetypes_and_stay_the_stars(self):
        for name, hero in self.heroes.items():
            self.assertEqual(hero.kind, 'hero')
        codex, claude = self.heroes['codex'], self.heroes['claude']
        self.assertLess(codex.lower, claude.lower, 'a slender glass shaft and a stepped stone tower have different silhouettes')
        self.assertLess(codex.upper, codex.face)
        for name in ('codex', 'claude'):
            hero = self.heroes[name]
            for b in self.city:
                fx, fy = city.proj(b.x1, b.y1)
                if math.hypot(fx - hero.front[0], (fy - hero.front[1]) * 1.6) < 95:
                    self.assertLess(b.h, hero.top, 'a neighbour of a data tower is never as tall as it')

    def test_every_archetype_paints_and_every_window_of_it_is_inside_the_picture(self):
        # one of each, on a small canvas: nothing raises, something is painted, the lit windows are recorded for the scene
        for arch in sorted(city.MATERIAL_OF.keys() | set(city.LANDMARKS)):
            b = city.Building(41, 26, 45, 30, 40, city.MATERIAL_OF.get(arch, 'stone'))
            own = __import__('random').Random(arch)
            b.id, b.lit = 5, .5
            b.style = city.style_for_arch(b, arch, 'sandstone', own, 'old') if arch in city.MATERIAL_OF else dict(city.base_style('civic_white', own), arch=arch, landmark=True)
            b.style['arch'] = arch
            cv, rec = city.Cv(city.WORLD, 1), city.Rec()
            city.KEEP[:] = []
            city.paint_building(cv, rec, b)
            self.assertIsNotNone(cv.cls.getbbox(), arch)
            self.assertGreater(len(rec.wins) + len(rec.screens) + len(rec.poke) + len(rec.lamps), 0, f'{arch}: windows or lights to light')


class Files(unittest.TestCase):
    def test_the_files_are_private_complete_and_accepted_by_the_tablet_server(self):
        atlas, data, thumb = Built.atlas, Built.data, Built.thumb
        with tempfile.TemporaryDirectory() as directory:
            city.write_files(directory, atlas, data, thumb, manifest=True, log=lambda text: None)
            out = Path(directory)
            names = sorted(p.name for p in out.iterdir())
            self.assertEqual([n for n in names if not n.startswith('.')], ['scene-city-iso.json', 'scene-city-iso.png', 'scenes.json', 'thumb-city-iso.webp'])
            for name in ('scene-city-iso.json', 'scene-city-iso.png', 'scenes.json', 'thumb-city-iso.webp'):
                self.assertEqual((out / name).stat().st_mode & 0o777, 0o600, name)
            self.assertLessEqual((out / 'scene-city-iso.png').stat().st_size, media.MAX_IMAGE_BYTES)
            self.assertLessEqual((out / 'scene-city-iso.json').stat().st_size, 512 * 1024)
            with Image.open(out / 'scene-city-iso.png') as picture:
                self.assertEqual(picture.size, atlas.size)
                self.assertEqual(picture.mode, 'RGBA')
            self.assertEqual(json.loads((out / 'scene-city-iso.json').read_text())['frames'], data['frames'])
            catalog = tablet_server.scene_catalog(out)
            self.assertIn('city-iso', catalog['scenes'])
            info = catalog['info']['city-iso']
            self.assertEqual(info['look'], 'game')
            self.assertEqual(info['media']['kind'], 'image')
            self.assertEqual(info['media']['url'], '/assets/scene-city-iso.png')
            self.assertEqual(info['data'], '/assets/scene-city-iso.json')

    def test_without_manifest_it_writes_no_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            city.write_files(directory, Built.atlas, Built.data, Built.thumb, manifest=False, log=lambda text: None)
            self.assertFalse((Path(directory) / 'scenes.json').exists())

    def test_the_command_line_writes_only_where_it_is_told(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(city, 'build', return_value=(Built.atlas, Built.data, Built.thumb)) as build:
            self.assertEqual(city.main(['--out', directory, '--seed', '7', '--lat', '40.4', '--lon', '-3.7']), 0)
            build.assert_called_once()
            self.assertEqual(build.call_args[0][0], 7)
            self.assertEqual(build.call_args[0][2], (40.4, -3.7))
            self.assertTrue((Path(directory) / 'scene-city-iso.png').exists())
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            city.main([])

    def test_the_same_seed_draws_the_same_city_and_another_seed_another(self):
        atlas, data, _ = city.build(2026, quick=True)
        self.assertEqual(json.dumps(data, sort_keys=True), json.dumps(Built.data, sort_keys=True))
        self.assertEqual(atlas.tobytes(), Built.atlas.tobytes())
        other, other_data, _ = city.build(7, quick=True)
        self.assertNotEqual(other.tobytes(), Built.atlas.tobytes())
        self.assertEqual(other_data['towers']['codex']['cells'], Built.data['towers']['codex']['cells'], 'the data buildings never move with the seed')


class Layout(unittest.TestCase):
    def test_nothing_stands_in_front_of_a_data_building_and_hides_it(self):
        buildings, heroes = city.make_plan(2026)
        for name, hero in heroes.items():
            kx0, ky0, kx1, ky1 = hero.screen_box()
            for b in buildings:
                if b.kind != 'city' or b.order <= hero.order - 3:
                    continue
                x0, y0, x1, y1 = b.bbox()
                self.assertTrue(x1 < kx0 or x0 > kx1 or y1 < ky0 or y0 > ky1, f'a {b.material} building at {b.x0},{b.y0} hides the {name} building')

    def test_the_data_buildings_are_the_tallest_around_and_the_city_is_dense(self):
        buildings, heroes = city.make_plan(2026)
        city_buildings = [b for b in buildings if b.kind == 'city']
        self.assertGreater(len(city_buildings), 150)
        self.assertGreater(len([b for b in city_buildings if b.h > 80]), 6, 'skyscrapers')
        self.assertLess(max(b.h for b in city_buildings), 151)
        for name in ('codex', 'claude'):
            hero = heroes[name]
            for b in city_buildings:
                d = math.hypot(proj_x(b) - hero.front[0], (proj_y(b) - hero.front[1]) * 1.6)
                if d < 95:
                    self.assertLess(b.h, hero.top, f'{name}: a neighbour is taller than the tower')
        self.assertEqual(sorted(heroes), ['claude', 'codex', 'small'])

    def test_the_space_under_the_clock_is_calm(self):
        buildings, _ = city.make_plan(2026)
        clock = (12, 205, 160, 268)                       # world pixels of the date and the big clock over the picture, above the dock
        x0, y0, x1, y1 = clock
        for b in buildings:
            if b.kind == 'city':
                cx, cy = city.proj((b.x0 + b.x1) / 2, (b.y0 + b.y1) / 2)
                self.assertFalse(x0 < cx < x1 and y0 < cy < y1, f'a building under the clock at {cx:.0f},{cy:.0f}')

    def test_every_building_has_a_unique_id_in_painting_order(self):
        buildings, _ = city.make_plan(2026)
        ids = [b.id for b in buildings]
        self.assertEqual(ids, list(range(1, len(buildings) + 1)))
        orders = [b.order for b in buildings]
        self.assertEqual(orders, sorted(orders), 'back to front')

    def test_the_viaduct_runs_through_the_city_with_a_garden_beside_it(self):
        buildings, _ = city.make_plan(2026)
        rail = [b for b in buildings if b.kind == 'rail']
        self.assertGreater(len(rail), 8)
        for b in rail:
            self.assertTrue(abs((b.y0 + b.y1) / 2 - city.RAIL_Y) < 1e-6 and b.z0 < b.h)
        gardens = [b for b in buildings if b.kind == 'promenade']
        self.assertTrue(gardens and all(b.h == 0 for b in gardens), 'the street under the viaduct is kept open by a flat garden')
        in_front = [b for b in buildings if b.kind == 'city' and b.y0 > city.RAIL_Y]
        for b in in_front:
            self.assertLessEqual(b.h, 9 * (b.y0 - city.RAIL_Y) - 1 + 1e-6, 'buildings in front of the railway step up so it stays in view')

    def test_the_city_runs_to_the_top_of_the_picture_with_nothing_on_the_water(self):
        buildings, heroes = city.make_plan(2026)
        # land everywhere: buildings stand behind and beside the towers, up to the haze
        behind = [b for b in buildings if b.kind == 'city' and city.proj(b.x1, b.y1)[1] < min(h.front[1] for h in heroes.values()) - 20]
        self.assertGreater(len(behind), 25, 'a city behind the data buildings')
        self.assertTrue(any(city.proj(b.x1, b.y1)[1] - b.h < 70 for b in behind), 'tall buildings reach high up the picture')
        for b in buildings:
            if b.kind != 'rail':
                self.assertFalse(city.CANAL[0] <= b.y0 < city.CANAL[1] and b.kind in ('city', 'park'), 'the canal is water')
        for name, hero in heroes.items():
            for b in buildings:
                if b.kind == 'city' and name != 'small':
                    d = math.hypot(proj_x(b) - hero.front[0], (proj_y(b) - hero.front[1]) * 1.6)
                    if d < 100:
                        self.assertLess(b.h, hero.top - 8, f'a neighbour of the {name} tower is as tall as it')


def proj_x(b):
    return city.proj(b.x1, b.y1)[0]


def proj_y(b):
    return city.proj(b.x1, b.y1)[1]


class Helpers(unittest.TestCase):
    def test_projection_round_trips(self):
        for gx, gy in ((0, 0), (20, 25), (36.5, 45.5), (-3.25, 61)):
            x, y = city.proj(gx, gy)
            back = city.unproj(x, y)
            self.assertAlmostEqual(back[0], gx)
            self.assertAlmostEqual(back[1], gy)
        self.assertEqual(city.proj(1, 0)[0] - city.proj(0, 0)[0], city.HW)
        self.assertEqual(city.proj(1, 1)[1] - city.proj(0, 0)[1], 2 * city.HH)

    def test_spans_bridge_short_gaps_and_drop_short_runs(self):
        flags = [0, 1, 1, 1, 0, 1, 1, 0, 0, 0, 0, 0, 1, 0]
        self.assertEqual(city.runs(flags, 2, 1), [(1, 6)])
        self.assertEqual(city.runs(flags, 2, 6), [(1, 12)])
        self.assertEqual(city.runs([0, 0, 1, 0], 2, 1), [])
        self.assertEqual(city.runs([], 1, 1), [])

    def test_packing_never_overlaps_and_keeps_every_picture(self):
        items = [(f'p{i}', Image.new('RGBA', (30 + i * 7, 20 + i * 5), (i, 0, 0, 255))) for i in range(9)]
        atlas, frames = city.pack(items, width=200)
        self.assertEqual(sorted(frames), sorted(n for n, _ in items))
        for name, image in items:
            x, y, w, h = frames[name]
            self.assertEqual((w, h), image.size)
            self.assertEqual(atlas.getpixel((x + 1, y + 1))[0], int(name[1:]))
        rects = list(frames.values())
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertTrue(a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])

    def test_the_hull_of_a_cloud_of_points(self):
        square = [(0, 0), (4, 0), (4, 4), (0, 4), (2, 2), (1, 3)]
        self.assertEqual(sorted(city.hull(square)), [(0, 0), (0, 4), (4, 0), (4, 4)])

    def test_the_project_mascots_are_the_only_pictures_used(self):
        for name in ('codex', 'claude'):
            picture = city.mascot(name, 15)
            self.assertEqual(picture.height, 15)
            self.assertTrue(picture.getbbox())

    def test_the_sun_is_computed_for_barcelona_unless_told_otherwise(self):
        self.assertAlmostEqual(city.PLACE[0], 41.39, places=2)
        self.assertAlmostEqual(city.PLACE[1], 2.17, places=2)


if __name__ == '__main__':
    unittest.main()
