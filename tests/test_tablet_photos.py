import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts import prepare_tablet_photos as photos
from token_tv.tablet_server import photo_catalog


def picture(path, size=(900, 600), blob=None, exif_orientation=None, gps=False):
    image = Image.new('RGB', size, (40, 60, 90))
    if blob:
        ImageDraw.Draw(image).ellipse(blob, fill=(250, 240, 120))
    exif = Image.Exif()
    if exif_orientation:
        exif[0x0112] = exif_orientation
    if gps:
        exif[0x010F] = 'Fictional Camera Co'
        exif.get_ifd(0x8825)[1] = 'N'                           # a GPS block
    image.save(path, **({'exif': exif} if (exif_orientation or gps) else {}))


class PhotoPreparationTests(unittest.TestCase):
    def setUp(self):
        self.source_dir = tempfile.TemporaryDirectory()
        self.target_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.source_dir.cleanup)
        self.addCleanup(self.target_dir.cleanup)
        self.source, self.target = Path(self.source_dir.name), Path(self.target_dir.name)

    def test_photos_are_turned_upright_stripped_of_metadata_and_cut_to_size(self):
        picture(self.source / 'a.jpg', size=(3600, 2400), gps=True)
        picture(self.source / 'b.jpg', size=(600, 900), exif_orientation=6)              # the camera was held sideways
        (self.source / 'notes.txt').write_text('not a picture')
        (self.source / '.hidden.jpg').write_bytes(b'x')
        entries = photos.prepare(self.source, self.target)
        self.assertEqual([e['file'] for e in entries], ['photo-01.jpg', 'photo-02.jpg'])
        self.assertEqual((entries[0]['width'], entries[0]['height']), (2400, 1600))      # the long edge, never larger
        self.assertEqual((entries[1]['width'], entries[1]['height']), (900, 600))        # turned upright: width and height swapped
        for entry in entries:
            with Image.open(self.target / entry['file']) as saved:
                self.assertEqual(saved.size, (entry['width'], entry['height']))
                self.assertEqual(len(saved.getexif()), 0, 'no camera data, no position')
                self.assertNotIn('exif', saved.info)
            self.assertEqual((self.target / entry['file']).stat().st_mode & 0o777, 0o600)

    def test_the_manifest_is_what_the_server_lists_and_the_originals_are_untouched(self):
        picture(self.source / 'a.jpg')
        before = (self.source / 'a.jpg').read_bytes()
        photos.prepare(self.source, self.target)
        self.assertEqual((self.source / 'a.jpg').read_bytes(), before)
        self.assertEqual(sorted(p.name for p in self.source.iterdir()), ['a.jpg'])
        listed = photo_catalog(self.target)
        self.assertEqual([p['url'] for p in listed], ['/assets/photo-01.jpg'])
        self.assertTrue(all(0 <= v <= 1 for v in listed[0]['focus']))
        self.assertEqual((self.target / 'photos.json').stat().st_mode & 0o777, 0o600)

    def test_the_focus_follows_the_detail_and_a_plain_picture_stays_centred(self):
        picture(self.source / 'left.jpg', size=(900, 600), blob=(60, 200, 260, 400))
        picture(self.source / 'plain.jpg', size=(900, 600))
        by_name = {e['file']: e for e in photos.prepare(self.source, self.target)}
        left, plain = by_name['photo-01.jpg']['focus'], by_name['photo-02.jpg']['focus']
        self.assertLess(left[0], .35)
        self.assertEqual(plain, [.5, .5])

    def test_a_second_run_needs_replace_or_append_and_replace_removes_only_the_frames_old_photos(self):
        for name in ('a', 'b', 'c'):
            picture(self.source / f'{name}.jpg')
        photos.prepare(self.source, self.target)
        with self.assertRaises(ValueError):
            photos.prepare(self.source, self.target)
        extra = Path(self.source_dir.name, 'extra')
        extra.mkdir()
        picture(extra / 'z.jpg')
        self.assertEqual(len(photos.prepare(extra, self.target, append=True)), 4)
        self.assertEqual(len(photo_catalog(self.target)), 4)
        (self.target / 'unrelated.txt').write_text('keep me')
        replaced = photos.prepare(extra, self.target, replace=True)
        self.assertEqual([e['file'] for e in replaced], ['photo-01.jpg'])
        self.assertEqual(sorted(p.name for p in self.target.glob('photo-*.jpg')), ['photo-01.jpg'])
        self.assertTrue((self.target / 'unrelated.txt').exists())

    def test_at_most_forty_photos_and_clear_errors_for_a_bad_folder(self):
        for number in range(45):
            picture(self.source / f'{number:02d}.png', size=(64, 48))
        self.assertEqual(len(photos.prepare(self.source, self.target)), 40)
        with self.assertRaises(ValueError):
            photos.prepare(self.source / 'nowhere', self.target)
        empty = Path(self.source_dir.name, 'empty')
        empty.mkdir()
        with self.assertRaises(ValueError):
            photos.prepare(empty, Path(self.target_dir.name, 'other'))
        broken = Path(self.source_dir.name, 'broken')
        broken.mkdir()
        (broken / 'x.jpg').write_bytes(b'not really a jpeg')
        with self.assertRaises(ValueError):
            photos.prepare(broken, Path(self.target_dir.name, 'another'))


if __name__ == '__main__':
    unittest.main()
