import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts import tablet_media as media


def frame(i, size=(64, 48)):
    image = Image.new('RGB', size, (20, 30, 60))
    ImageDraw.Draw(image).rectangle((i * 3, 10, i * 3 + 9, 30), fill=(255, 255, 255))
    return image


class TabletMediaTests(unittest.TestCase):
    def test_a_scene_entry_names_only_what_the_server_accepts(self):
        entry = media.scene_entry('crt', 'scene-surf.webm', 'video', 640, 480, fps=15, loop_seconds=19.2)
        self.assertEqual(entry, {'look': 'crt', 'focus': [.5, .5], 'rate': 1.0,
                                 'media': {'kind': 'video', 'file': 'scene-surf.webm', 'width': 640, 'height': 480, 'fps': 15,
                                           'loop_seconds': 19.2}})
        with self.assertRaises(ValueError):
            media.scene_entry('neon', 'x', 'video', 1, 1)

    def test_manifest_updates_keep_the_other_scenes_and_stay_private(self):
        with tempfile.TemporaryDirectory() as directory:
            media.update_manifest('surf', media.scene_entry('crt', 'scene-surf.webm', 'video', 640, 480), directory)
            scenes = media.update_manifest('paradise', media.scene_entry('photo', 'scene-paradise.webm', 'video', 768, 960), directory)
            self.assertEqual(sorted(scenes), ['paradise', 'surf'])
            path = Path(directory) / 'scenes.json'
            self.assertEqual(json.loads(path.read_text())['version'], 2)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_images_are_written_atomically_by_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ('a.webp', 'a.jpg', 'a.png'):
                path = media.save_image(frame(3), Path(directory) / name)
                self.assertTrue(path.stat().st_size > 0 and path.stat().st_mode & 0o777 == 0o600, name)
                with Image.open(path) as picture:
                    self.assertEqual(picture.size, (64, 48))
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['a.jpg', 'a.png', 'a.webp'])
            self.assertEqual(media.save_thumbnail(Image.new('RGB', (480, 320)), Path(directory) / 't.webp').exists(), True)

    @unittest.skipUnless(media.find_ffmpeg(), 'no ffmpeg on this computer')
    def test_frames_become_a_vp8_webm_at_the_chosen_scale(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'scene-surf.webm'
            width, height, count = media.encode_webm((frame(i) for i in range(20)), 15, target, scale=2)
            self.assertEqual((width, height, count), (128, 96, 20))
            data = target.read_bytes()
            self.assertEqual(data[:4], bytes.fromhex('1a45dfa3'))       # EBML header of Matroska/WebM
            self.assertIn(b'V_VP8', data[:400])
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            self.assertEqual(sorted(p.name for p in Path(directory).iterdir()), ['scene-surf.webm'])   # no temporary file left

    @unittest.skipUnless(media.find_ffmpeg(), 'no ffmpeg on this computer')
    def test_mixed_frame_sizes_and_empty_input_fail_without_leaving_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'x.webm'
            with self.assertRaises(ValueError):
                media.encode_webm([frame(0), frame(1, (32, 24))], 15, target)
            with self.assertRaises(RuntimeError):
                media.encode_webm([], 15, target)
            self.assertEqual(list(Path(directory).iterdir()), [])


if __name__ == '__main__':
    unittest.main()
