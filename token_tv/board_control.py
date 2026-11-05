"""Local dashboard controls for the paired display, without exposing its token."""
from datetime import datetime
from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import threading
import time

from PIL import Image

from token_tv.board import PAGES


# Night mode (Tony, 2026-11-03): the PC decides from the schedule and tells the board only when the level changes.
NIGHT_DEFAULT = {'enabled': True, 'start': '23:00', 'end': '07:30', 'level': 25}
NIGHT_LEVEL_RANGE = (5, 100)  # percent; the control room offers 10 to 75. Never zero: a dark board looks dead.
_CLOCK_TEXT = re.compile(r'(?:[01]\d|2[0-3]):[0-5]\d')


def night_settings(value):
    """A validated night-mode setting (exactly four keys), or ValueError. Nothing is guessed or coerced."""
    if not isinstance(value, dict) or set(value) != {'enabled', 'start', 'end', 'level'}:
        raise ValueError('Invalid night mode')
    if type(value['enabled']) is not bool or type(value['level']) is not int or \
            not NIGHT_LEVEL_RANGE[0] <= value['level'] <= NIGHT_LEVEL_RANGE[1]:
        raise ValueError('Invalid night mode')
    for key in ('start', 'end'):
        if not isinstance(value[key], str) or not _CLOCK_TEXT.fullmatch(value[key]):
            raise ValueError('Invalid night mode')
    return {key: value[key] for key in ('enabled', 'start', 'end', 'level')}


class NightMode:
    """The night schedule, kept with the other board settings under the state folder (private, atomic, local)."""
    def __init__(self, path, changed=None, clock=datetime.now):
        self.path = Path(path)
        self.changed = changed
        self.clock = clock
        self.lock = threading.Lock()
        try:
            if self.path.stat().st_size > 4096:
                raise ValueError('Too large')
            self.value = night_settings(json.loads(self.path.read_text()))
        except (OSError, ValueError, UnicodeError):
            self.value = dict(NIGHT_DEFAULT)  # missing or damaged: the defaults, never an error in the way of the display

    def settings(self):
        with self.lock:
            return dict(self.value)

    def update(self, value):
        updated = night_settings(value)
        with self.lock:
            if updated != self.value:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                temporary = self.path.with_suffix('.tmp')
                try:
                    with temporary.open('w', encoding='utf-8') as handle:
                        os.chmod(temporary, 0o600)
                        json.dump(updated, handle, separators=(',', ':'))
                    temporary.replace(self.path)
                finally:
                    temporary.unlink(missing_ok=True)
                self.value = updated
                changed = True
            else:
                changed = False
        if changed and self.changed is not None:
            self.changed.set()  # the monitor applies it on its next pass, within seconds
        return self.settings()

    def level_at(self, moment=None):
        """The level the schedule wants now (100 outside the night window or when it is off). Local civil time."""
        value = self.settings()
        if not value['enabled']:
            return 100
        moment = moment or self.clock()
        now = moment.hour * 60 + moment.minute
        start, end = (int(value[key][:2]) * 60 + int(value[key][3:]) for key in ('start', 'end'))
        if start == end:
            inside = False  # an empty window
        elif start < end:
            inside = start <= now < end
        else:
            inside = now >= start or now < end  # across midnight
        return value['level'] if inside else 100


def apply_night(board, night, moment=None):
    """Tell the board the scheduled level, only when it differs from what it reports. Returns the level sent, or None.

    The board keeps the level in its own memory and writes flash only when it changes, so this is called on every
    pass and sends nothing in the usual case. Boards that do not advertise the capability are never sent anything."""
    if night is None or not getattr(board, 'brightness', False):
        return None
    want = night.level_at(moment)
    have = (board.last_info or {}).get('bright')
    if type(have) is int and have == want:
        return None
    board.configure(bright=want)
    if board.last_info is not None:
        board.last_info['bright'] = want
    return want


def preview_image(frame):
    """Compose the board's first sprite poses over its in-memory background."""
    from token_tv.board_anim import KEY, decode
    from token_tv.board_pages import frame_size
    if frame_size(frame) != (320, 240):
        return None
    base = 8 + 320 * 240 * 2
    image = Image.frombytes('RGB', (320, 240), frame[8:base], 'raw', 'BGR;16')
    if frame[base:base + 4] != b'ANIM':
        return image
    try:
        animation = decode(frame[base + 8:])
        for sprite in animation['sprites']:
            index, dx, dy = sprite['script'][0]
            words = sprite['frames'][index]
            size = (sprite['w'], sprite['h'])
            pixels = struct.pack(f'<{len(words)}H', *words)
            pose = Image.frombytes('RGB', size, pixels, 'raw', 'BGR;16')
            mask = Image.frombytes('L', size, bytes(0 if word == KEY else 255 for word in words))
            size = (size[0] * 2, size[1] * 2)
            pose = pose.resize(size, Image.Resampling.NEAREST)
            mask = mask.resize(size, Image.Resampling.NEAREST)
            image.paste(pose, (sprite['x'] + dx, sprite['y'] + dy), mask)
    except (ValueError, IndexError, struct.error):
        # A bad optional trailer must never prevent the rest of the UI loading.
        pass
    return image


class BoardControl:
    def __init__(self, board, scenes=None, night=None):
        self.board = board
        self.scenes = scenes
        self.night = night
        self.preview_lock = threading.Lock()
        self.library_lock = threading.RLock()
        self.frames = ()
        self.previews = {}
        self.archive_previews = {}
        self.archive_frames = {}
        self.archive_versions = {}
        from token_tv.board_preview import AnimatedPreviews
        self.animated_previews = AnimatedPreviews()

    def archive_preview(self, scene, snapshot=None):
        from token_tv.board_scenes import SCENES, image_version, render_archive
        from token_tv.board_pages import PAGE_NAMES, render_board_pages, rgb565_frame
        if scene not in SCENES:
            raise ValueError('Unknown screen')
        # No fabricated quota: an unavailable reading stays unknown. Hashing the
        # snapshot keeps the cache current without retaining an extra account copy.
        snapshot = snapshot if snapshot is not None else {'accounts': {}}
        readings = hashlib.sha256(json.dumps(snapshot, sort_keys=True, separators=(',', ':')).encode()).digest()
        # Rendering the art can take time. Do not block the publisher's
        # preview lock while it sends or confirms the real display pages.
        with self.library_lock:
            version = (image_version(scene), readings)
            if scene not in self.archive_previews or self.archive_versions.get(scene) != version:
                if scene in PAGE_NAMES:
                    frames = render_board_pages(snapshot, anim=True, waves=3, scroll=4)
                    previews = zip(PAGE_NAMES, frames)
                else:
                    image, payload = render_archive(scene, snapshot, animated=True, extended_anim=True)
                    previews = [(scene, rgb565_frame(image, anim=payload))]
                for name, frame in previews:
                    self.archive_frames[name] = frame
                    image = preview_image(frame)
                    out = BytesIO()
                    image.save(out, format='PNG', optimize=False)
                    self.archive_previews[name] = out.getvalue()
                    self.archive_versions[name] = (image_version(name), readings)
            return self.archive_previews[scene]

    def archive_animation(self, scene, snapshot=None):
        with self.library_lock:
            self.archive_preview(scene, snapshot)  # Keep the frame and its snapshot together.
            frame = self.archive_frames[scene]
        return self.animated_previews.get(frame)

    def update_frames(self, frames):
        # The publisher already rendered these bytes; no additional board traffic.
        with self.preview_lock:
            frames = tuple(frames[:PAGES])
            for i, frame in enumerate(frames):
                if i >= len(self.frames) or frame != self.frames[i]:
                    self.previews.pop(i, None)
            self.frames = frames

    def preview(self, number):
        if type(number) is not int or not 0 <= number < PAGES:
            raise ValueError('Unknown screen')
        with self.preview_lock:
            if number >= len(self.frames):
                return None
            if number not in self.previews:
                frame = self.frames[number]
                image = preview_image(frame)
                if image is None:
                    return None
                out = BytesIO()
                image.save(out, format='PNG', optimize=False)
                self.previews[number] = out.getvalue()
            return self.previews[number]

    def preview_animation(self, number):
        if type(number) is not int or not 0 <= number < PAGES:
            raise ValueError('Unknown screen')
        with self.preview_lock:
            frame = self.frames[number] if number < len(self.frames) else None
        return self.animated_previews.get(frame)

    def status(self, refresh=True):
        result = self._status(refresh)
        if self.scenes:
            result.update(self.scenes.status())
        result.update(self.night_status())
        return result

    def night_status(self):
        """The schedule (kept here) and what the board last said about its light. Unknown stays unknown."""
        if self.night is None:
            return {}
        info = (self.board.last_info if self.board is not None else None) or {}
        supported = info.get('brightness') in (1, True)
        wanted = self.night.level_at()
        return {'night': self.night.settings(), 'night_supported': supported,
                'night_applied': supported and type(info.get('bright')) is int and info['bright'] == wanted}

    def _status(self, refresh=True):
        if self.board is None:
            return {'state': 'not_configured', 'page': None, 'controls': False}
        board = self.board
        busy = not board.lock.acquire(blocking=False)
        failed = False
        if not busy:
            try:
                if refresh and time.monotonic() - board.last_seen > 15:
                    try:
                        board.info()
                    except (OSError, ValueError):
                        failed = True
            finally:
                board.lock.release()
        info = board.last_info or {}
        age = time.monotonic() - board.last_seen
        state = 'busy' if busy else 'offline' if failed or age > 90 else 'connected'
        if state == 'offline':
            # A remembered page is not evidence of what a disconnected display shows.
            return {'state': state, 'page': None, 'rotation_minutes': None,
                    'speed_percent': None, 'controls': False, 'clock_synced': False}
        page = info.get('page')
        return {'state': state, 'page': page - 1 if type(page) is int and 1 <= page <= PAGES else None,
                'showing_connection': info.get('info') == 1,
                'rotation_minutes': info.get('rotation_minutes'),
                'speed_percent': info.get('animation_speed'),
                'per_screen_speed': info.get('per_screen_speed') is True,
                'touch_controls': info.get('touch_controls') == 1,
                'card_supported': info.get('card') in (1, True),
                'mode_hold_seconds': info.get('mode_hold_seconds'),
                'connect_hold_seconds': info.get('connect_hold_seconds'),
                'controls': info.get('board_controls') == 1,
                'clock_synced': info.get('clock_synced') is True}

    def execute(self, command, value):
        if command == 'night':
            if self.night is None:
                raise ValueError('Night mode is unavailable')
            self.night.update(value)  # kept on this computer; the monitor tells the board within a pass
            return self.status(refresh=False)
        if command in ('scene', 'order'):
            if self.scenes is None:
                raise ValueError('Screen library is unavailable')
            if command == 'scene':
                self.scenes.select(value)
            else:
                self.scenes.reorder(value)
            return self.status(refresh=False)
        if self.board is None:
            raise OSError('Display is not configured')
        if command == 'page':
            if type(value) is not int or not 0 <= value < PAGES:
                raise ValueError('Unknown screen')
        elif command == 'rotation':
            if type(value) is not int or value not in (0, 30, 60):
                raise ValueError('Unsupported rotation')
        elif command == 'speed':
            if isinstance(value, dict) and set(value) == {'percent', 'page'}:
                target_page, rate = value['page'], value['percent']
                if type(target_page) is not int or not 0 <= target_page < PAGES:
                    raise ValueError('Unknown screen')
            else:
                target_page, rate = None, value
            if type(rate) is not int or rate not in (75, 100, 125):
                raise ValueError('Unsupported speed')
        elif command == 'touch':
            if (not isinstance(value, dict) or set(value) != {'mode', 'connect'}
                    or type(value['mode']) is not int or type(value['connect']) is not int
                    or not 1 <= value['mode'] <= 4 or not 5 <= value['connect'] <= 10):
                raise ValueError('Unsupported touch timing')
        else:
            raise ValueError('Unknown control')
        board = self.board
        if not board.lock.acquire(timeout=120):
            raise OSError('Display is busy')
        try:
            before = board.info()
            if command == 'page':
                board.show(value)
            elif before.get('board_controls') != 1:
                raise ValueError('Display update needed for this setting')
            elif command == 'rotation':
                board.configure(cycle=value)
            elif command == 'speed':
                selected_page = before.get('page')
                if before.get('per_screen_speed') is True:
                    if target_page is None and (type(selected_page) is not int or not 1 <= selected_page <= PAGES):
                        raise OSError('Selected screen is unknown')
                    target_page = selected_page - 1 if target_page is None else target_page
                    board.configure(speed=rate, speed_page=target_page)
                else:
                    if target_page is not None:
                        raise ValueError('Display update needed for per-screen speed')
                    board.configure(speed=rate)
            elif before.get('touch_controls') == 1:
                board.configure(mode_hold=value['mode'], connect_hold=value['connect'])
            else:
                raise ValueError('Display update needed for touch settings')
            after = board.info()
            if command == 'speed' and before.get('per_screen_speed') is True:
                speeds = after.get('animation_speeds')
                confirmed = (isinstance(speeds, list) and len(speeds) == PAGES
                             and speeds[target_page] == rate)
            elif command == 'touch':
                confirmed = (after.get('mode_hold_seconds') == value['mode']
                             and after.get('connect_hold_seconds') == value['connect'])
            else:
                key = {'page': 'page', 'rotation': 'rotation_minutes', 'speed': 'animation_speed'}[command]
                expected = value + 1 if command == 'page' else rate if command == 'speed' else value
                confirmed = after.get(key) == expected
            if not confirmed:
                raise OSError('Display did not confirm this setting')
        finally:
            board.lock.release()
        return self.status(refresh=False)
