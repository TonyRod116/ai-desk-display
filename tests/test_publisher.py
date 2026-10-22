import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from token_tv import live


class PublisherTests(unittest.TestCase):
    def run_cycles(self, device, directory, frames, album=False):
        cycles = len(frames)
        current_frame = None
        remaining = iter(frames)
        def snapshot():
            nonlocal current_frame
            current_frame = next(remaining)
            return {'accounts': {}, 'updated_at': 0}
        class Event:
            def __init__(self):
                self.checks = 0
            def is_set(self):
                self.checks += 1
                return self.checks > cycles
            def set(self): pass
            def clear(self): pass
            def wait(self, timeout=None): pass
        class Thread:
            def __init__(self, target, **kwargs): self.target = target
            def start(self): self.target()
            def join(self, **kwargs): pass
        config = {'accounts': [], 'device_url': 'http://127.0.0.1', 'display_style': 'game-boy',
                  'display_album_faces': album}
        with patch('sys.argv', ['live', '--config', '/unused', '--state-dir', directory]), \
             patch.object(live, 'load_config', return_value=config), \
             patch.object(live, 'PhotoDisplay', return_value=device), \
             patch.object(live, 'UsageStore', return_value=MagicMock(snapshot=snapshot)), \
             patch.object(live, 'render_page', side_effect=lambda *args: current_frame if not album else current_frame + args[2].encode()), \
             patch.object(live, 'ThreadingHTTPServer'), \
             patch.object(live.threading, 'Event', Event), \
             patch.object(live.threading, 'Thread', Thread):
            live.main()

    def test_same_frame_retries_activation_after_failed_update(self):
        device = MagicMock(profile='ultra')
        device.capture.return_value = {'profile': 'ultra'}
        device.upload.return_value = {'status': 200}
        device.activate.side_effect = [None, ValueError('display selection failed'), None]
        with tempfile.TemporaryDirectory() as directory:
            self.run_cycles(device, directory, [b'first', b'changed', b'changed'])
        self.assertEqual(device.activate.call_count, 3)
        self.assertEqual(device.upload.call_count, 2)

    def test_foreign_backup_never_allows_upload_on_later_cycles(self):
        device = MagicMock(profile='sd_pro')
        device.resume.side_effect = ValueError('Backup belongs to another clock')
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / 'display-original.json').write_text(json.dumps({'profile': 'ultra'}))
            self.run_cycles(device, directory, [b'first', b'first'])
        device.upload.assert_not_called()

    def test_album_refresh_preserves_manual_selection_and_skips_identical_files(self):
        device = MagicMock(profile='ultra')
        device.capture.return_value = {'profile': 'ultra'}
        device.upload.return_value = {'status': 200}
        with tempfile.TemporaryDirectory() as directory:
            self.run_cycles(device, directory, [b'first', b'changed', b'changed'], album=True)
        names = {call.args[0] for call in device.upload.call_args_list}
        self.assertEqual(names, {'Game Boy verde.jpg', 'Game Boy gris.jpg',
                                 'Pixel Retro.jpg', 'Terminal Ambar.jpg', 'Orbit.jpg'})
        self.assertEqual(device.upload.call_count, 10)
        # Only initial selection: subsequent quota refreshes must not override
        # a different image selected directly in the clock's own album.
        self.assertEqual(device.activate.call_count, 1)
        self.assertEqual(device.activate.call_args.args[1], 'Game Boy verde.jpg')
