"""The real tablet page and server routes on fictional data, for checking layout and scenes. Never reads or writes anything private.

    .venv/bin/python -B scripts/sample_tablet.py --port 18861
    http://127.0.0.1:18861/            (no sign-in: the fictional server always lets you in)
    http://127.0.0.1:18861/sample/normal   switch the readings: normal, unknown, many-disks, critical, aged

With `--scenes DIR` the scene files are read (never written, never deleted) from an existing folder such as the real private one, to see
the real pictures in the real page: only the fixed scene names are served, and the readings stay fictional.

It runs the production Handler (same static routes, scene catalogue, byte ranges and headers) on plain HTTP in a temporary folder. The
fictional scenes are small procedural pictures and, where an encoder exists, short looping videos, so the stage and its renderers can be
exercised without any of Tony's private art.
"""
import argparse
import json
import math
import shutil
import sys
import tempfile
import threading
import time
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import tablet_media  # noqa: E402
from token_tv import tablet_server  # noqa: E402

GB, TB = 1024 ** 3, 1024 ** 4


def disk(name, total, free, **extra):
    return {'name': name, 'total': int(total), 'free': int(free), **extra}


def readings(scenario, now):
    week = lambda remaining, hours: {'remaining': remaining, 'resets_at': now + hours * 3600}
    codex = {'weekly': week(68, 122), 'session': None, 'aged': False, 'resets': {'count': 2, 'old': False}, 'credits': None}
    claude = {'weekly': week(38, 76), 'session': week(72, 2.2), 'aged': False, 'resets': {'count': 0, 'old': False}, 'credits': None}
    metrics = {'cpu_percent': 26, 'cpu_temp_c': 48, 'memory': {'total': 32 * GB, 'free': 22.2 * GB}, 'gpus': [{'temp_c': 55, 'percent': 18}],
               'disks': [disk('C:', 931 * GB, 130 * GB), disk('D:', 1.8 * TB, 1.1 * TB), disk('E:', 1.8 * TB, 190 * GB),
                         disk('F:', 3.6 * TB, 2.4 * TB)]}
    metrics.update(processes={'cpu': [{'name': 'browser', 'percent': 14.2, 'mem_mb': 2100}, {'name': 'compiler', 'percent': 9.1, 'mem_mb': 900}, {'name': 'python', 'percent': 6.3, 'mem_mb': 410},
                                      {'name': 'editor', 'percent': 3.2, 'mem_mb': 700}, {'name': 'explorer', 'percent': 1.1, 'mem_mb': 150}],
                              'memory': [{'name': 'browser', 'mem_mb': 2100}, {'name': 'compiler', 'mem_mb': 900}, {'name': 'editor', 'mem_mb': 700}, {'name': 'python', 'mem_mb': 410}, {'name': 'explorer', 'mem_mb': 150}],
                              'gpu': [{'name': 'browser', 'percent': 12.0}, {'name': 'compositor', 'percent': 4.0}]},
                   network={'down_bps': 2400000, 'up_bps': 180000}, battery={'percent': 87, 'charging': None, 'minutes': None, 'plugged': True}, uptime_s=3 * 86400 + 4 * 3600,
                   history={'step': 30, 'cpu': [20 + 15 * math.sin(i / 9) + (i % 7) for i in range(120)], 'gpu': [10 + 8 * math.sin(i / 7) for i in range(120)],
                            'cpu_temp': [44 + 6 * math.sin(i / 11) for i in range(120)], 'gpu_temp': [50 + 5 * math.sin(i / 13) for i in range(120)],
                            'memory': [28 + 4 * math.sin(i / 17) for i in range(120)], 'down': [1e6 + 1e6 * abs(math.sin(i / 5)) for i in range(120)], 'up': [1e5 + 8e4 * abs(math.cos(i / 6)) for i in range(120)]})
    connected = True
    if scenario == 'unknown':
        codex = claude = {'weekly': None, 'session': None, 'aged': False, 'resets': {'count': None, 'old': False}, 'credits': None}
        metrics = {'cpu_percent': None, 'cpu_temp_c': None, 'memory': None, 'disks': [], 'gpus': [], 'processes': None, 'network': None, 'battery': None, 'uptime_s': None}
        connected = False
    elif scenario == 'many-disks':
        metrics['disks'] += [disk('G:', 2 * TB, 1.5 * TB, kind='google_drive', quota_source='manual', quota_at=int(now - 4 * 86400)),
                             disk('H:', 500 * GB, 49 * GB), disk('I:', 4 * TB, 3.9 * TB), disk('J:', 1 * TB, 30 * GB)]
        metrics['disks'][-4]['total'], metrics['disks'][-4]['free'] = 2 * 10 ** 12, int(1.4 * 10 ** 12)
    elif scenario == 'critical':
        codex.update(weekly=week(4, 20), credits=None)
        claude.update(weekly=week(8.5, 9), session=week(0.6, .4))
        metrics['disks'] = [disk('C:', 931 * GB, 20 * GB), disk('D:', 1.8 * TB, 150 * GB), disk('E:', 1.8 * TB, 300 * GB),
                            disk('F:', 3.6 * TB, 0.2 * TB)]
        metrics.update(cpu_percent=93, cpu_temp_c=88, gpus=[{'temp_c': 79, 'percent': 97}])
    elif scenario == 'aged':
        codex['aged'] = claude['aged'] = True
        codex['resets'] = {'count': 1, 'old': True}
    return {'providers': {'codex': codex, 'claude': claude}, 'quota_connected': connected, 'metrics': metrics}


class FictionalFeeds:
    def __init__(self, scenario):
        self.scenario = scenario

    def status(self):
        return readings(self.scenario, time.time())


class FictionalBoard:
    """Stands in for the small screen's remote: the same shape as tablet_board.BoardRemote, nothing is ever sent anywhere."""
    NAMES = ('Game Boy', 'Paradise', 'Neon City', 'Tidal Rush', 'Token Run', 'Versus', 'Platform', 'City')

    def __init__(self):
        self.state = {'state': 'ok', 'page': 1, 'controls': True, 'rotation': 30, 'speed': 100, 'firmware': '44',
                      'night': {'enabled': True, 'start': '23:00', 'end': '07:30', 'level': 25}}
        self.sent = []

    def status(self):
        return {**self.state, 'slots': [{'index': i, 'name': name} for i, name in enumerate(self.NAMES)]}

    def command(self, name, value):
        if name not in ('page', 'rotation', 'speed', 'night'):
            return {'ok': False, 'status': None, 'error': 'refused'}
        self.sent.append((name, value))
        self.state[name] = value
        return {'ok': True, 'status': self.status(), 'error': None}


class OpenAuth:
    def configured(self):
        return True

    def allowed(self, header):
        return True


class FictionalWeather:
    """A made-up outside reading for the page (no network): `?code=61&temp=7&day=0` on /sample/weather changes it."""

    def __init__(self):
        self.value = {'temp': 14, 'code': 3, 'day': True, 'age': 0}

    def status(self):
        return dict(self.value)


class SampleHandler(tablet_server.Handler):
    def _origin_ok(self):                      # this stand-in speaks plain HTTP, the real server HTTPS
        return self.headers.get('Origin', '') == 'http://' + self.headers.get('Host', '')

    def do_GET(self):
        if self.path.startswith('/sample/weather'):
            query = dict(part.split('=', 1) for part in self.path.partition('?')[2].split('&') if '=' in part)
            try:
                self.server.weather.value = {'temp': int(query.get('temp', 14)), 'code': int(query.get('code', 3)), 'day': query.get('day', '1') == '1', 'age': 0}
            except ValueError:
                return self._respond(400)
            return self._respond(303, extra=(('Location', '/'),))
        if self.path.startswith('/sample/'):
            name = self.path.split('/', 2)[2].split('?', 1)[0]
            if name not in ('normal', 'unknown', 'many-disks', 'critical', 'aged'):
                return self._respond(404)
            self.server.feeds.scenario = name
            return self._respond(303, extra=(('Location', '/'),))
        return super().do_GET()


def procedural(name, size, phase=0.0):
    """A fictional picture: sky, a sun, hills and moving water; no private art and nothing from the board."""
    width, height = size
    image = Image.new('RGB', size)
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / height
        draw.line((0, y, width, y), fill=(int(20 + 120 * t), int(40 + 100 * t), int(90 + 80 * (1 - t))))
    draw.ellipse((width * .65, height * .12, width * .65 + height * .16, height * .12 + height * .16), fill=(255, 226, 150))
    draw.polygon([(0, height * .6), (width * .3, height * .42), (width * .55, height * .6)], fill=(30, 60, 70))
    draw.rectangle((0, height * .6, width, height), fill=(20, 90, 120))
    for i in range(7):
        y = height * (.64 + .05 * i)
        x = (i * 37 + phase * width) % width
        draw.line((x, y, x + width * .18, y), fill=(190, 230, 240), width=max(1, height // 120))
    return image


def prepare_photos(directory, count=6):
    """Fictional photos for the photo frame (procedural pictures; never anything of Tony's)."""
    entries = []
    for number in range(1, count + 1):
        image = procedural('photo', (1200, 800), number / count)
        name = f'photo-{number:02d}.jpg'
        tablet_media.save_image(image, directory / name)
        entries.append({'file': name, 'width': 1200, 'height': 800, 'focus': [.5, .5]})
    (directory / 'photos.json').write_text(json.dumps({'version': 1, 'photos': entries}), encoding='utf-8')


def prepare_scenes(directory):
    manifest = {}
    for index, scene in enumerate(tablet_server.SCENES):
        pixel = scene in ('surf', 'token-run', 'city-iso', 'fighting')
        size = (320, 240) if pixel else (768, 960) if scene == 'paradise' else (960, 720)
        still = procedural(scene, size, index / 12)
        tablet_media.save_thumbnail(still, directory / f'thumb-{scene}.webp')
        look = 'crt' if pixel else 'photo'
        if tablet_media.find_ffmpeg():
            try:
                frames = [procedural(scene, size, index / 12 + i / 40) for i in range(40)]
                width, height, _ = tablet_media.encode_webm(frames, 20, directory / f'scene-{scene}.webm', scale=2 if pixel else 1, crf=20,
                                                            max_kbps=2500, speed=4)
                tablet_media.save_image(still, directory / f'scene-{scene}.jpg')
                manifest[scene] = tablet_media.scene_entry(look, f'scene-{scene}.webm', 'video', width, height, fps=20, loop_seconds=2,
                                                           still=f'scene-{scene}.jpg', focus=(.5, .55))
                continue
            except (RuntimeError, ValueError):
                pass
        tablet_media.save_image(still, directory / f'scene-{scene}.jpg')
        manifest[scene] = tablet_media.scene_entry(look, f'scene-{scene}.jpg', 'image', *size)
    for scene, entry in manifest.items():
        tablet_media.update_manifest(scene, entry, directory)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--port', type=int, default=18861)
    parser.add_argument('--scenario', default='normal', choices=('normal', 'unknown', 'many-disks', 'critical', 'aged'))
    parser.add_argument('--scenes', type=Path, help='use the scene files of this existing folder, read-only, instead of fictional ones')
    args = parser.parse_args()
    borrowed = args.scenes is not None
    if borrowed:
        directory = args.scenes.expanduser().resolve()
        if not directory.is_dir():
            parser.error('--scenes needs an existing folder')
    else:
        directory = Path(tempfile.mkdtemp(prefix='fictional-tablet-'))
        prepare_scenes(directory)
        prepare_photos(directory)
    server = tablet_server.TabletServer(('127.0.0.1', args.port), SampleHandler, mode='lan', auth=OpenAuth(),
                                        feeds=FictionalFeeds(args.scenario), private=directory, lan='127.0.0.1',
                                        lan_port=args.port, fingerprint='FICTIONAL',
                                        reports=tablet_server.Reports(),      # in memory: a lent real folder is never written to
                                        settings=tablet_server.Settings(None, tablet_server.SCENES), board=FictionalBoard(),
                                        weather=FictionalWeather())
    print(f'Fictional tablet at http://127.0.0.1:{args.port}/  (scenes in {directory})', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if not borrowed:                      # only the temporary folder this run created; a folder lent with --scenes is never touched
            shutil.rmtree(directory, ignore_errors=True)


if __name__ == '__main__':
    main()
