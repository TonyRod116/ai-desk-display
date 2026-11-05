"""The display's eight user-selected slots and locally retained screen versions."""
import json
import os
from pathlib import Path
import threading

from token_tv.board_pages import PAGE_NAMES, PAGE_SIZE


SCENES = {
    # New additions first; earlier versions stay together at the end.
    'zelda': 'Hyrule Quest',
    'violet-horizon': 'Violet Horizon',
    'neon-district': 'Neon District',
    'game-boy': 'Game Boy',
    'paradise': 'Paradise',
    'code-forge': 'Neon City',
    'surf': 'Tidal Rush',
    'dials': 'Token Run',
    'arcade': 'Versus',
    'cockpit': 'Platform',
    'countdown': 'City',
    # Approximate order of the original designs, newest to oldest.
    'versus-train': 'Versus · Night Train',
    'neon-towers': 'Neon City · Towers',
    'neon-smooth': 'Neon City · Smooth',
    'deep-space': 'Deep Space · UFO',
    'paradise-photo': 'Paradise · Original Beach',
    'neon-pixel': 'Neon City · Pixel',
    'code-editor': 'Code Forge · Editor',
    'prism': 'Prism',
    'code-workshop': 'Code Forge · Workshop',
    'cockpit-classic': 'Token Cockpit · Classic',
    'orbit': 'Orbit',
    'game-boy-pocket': 'Game Boy Pocket',
    'amber-terminal': 'Amber Terminal',
    'pixel-retro': 'Pixel Retro',
}
ARCHIVED_SCENES = tuple(name for name in SCENES if name not in PAGE_NAMES)
PRIVATE_CITIES = ('violet-horizon', 'neon-district')
NEW_SCENES = ('zelda', *PRIVATE_CITIES)


def image_version(scene):
    """Detect a changed, removed or invalid optional local image."""
    if scene not in NEW_SCENES:
        return None
    if scene == 'zelda':
        from token_tv.board_zelda import art_version
        return art_version()
    from token_tv.board_cyber_scenes import ART, FILES
    try:
        path = ART / FILES[scene]
        stat = path.stat()
        return (stat.st_mtime_ns, stat.st_size) if path.is_file() else None
    except OSError:
        return None


def available(scene):
    """Offer screens with private artwork only where the local artwork exists."""
    return scene == 'zelda' or scene not in NEW_SCENES or image_version(scene) is not None


class BoardScenes:
    """Persist only scene IDs. A queued choice is not a delivery confirmation."""
    def __init__(self, path, changed):
        self.path = Path(path)
        self.changed = changed
        self.lock = threading.Lock()
        self.ids = list(PAGE_NAMES)
        self.delivered = [None] * len(PAGE_NAMES)
        self.load_error = False
        try:
            data = json.loads(self.path.read_text())
            if (not isinstance(data, list) or len(data) != len(PAGE_NAMES)
                    or any(not isinstance(v, str) or v not in SCENES for v in data)):
                raise ValueError('Invalid screen settings')
            self.ids = data
        except FileNotFoundError:
            pass
        except (OSError, ValueError, UnicodeError):
            self.load_error = True

    def snapshot(self):
        with self.lock:
            if self.load_error:
                raise ValueError('Screen settings need attention')
            return tuple(self.ids)

    def status(self):
        with self.lock:
            return {'scene_ids': list(self.ids),
                    'scene_delivered_ids': list(self.delivered),
                    'scene_pending': [a != b for a, b in zip(self.ids, self.delivered)],
                    'scene_catalog': [{'id': k, 'name': v, 'archived': k in ARCHIVED_SCENES and k not in NEW_SCENES}
                                      for k, v in SCENES.items() if available(k) or k in self.ids],
                    'scene_settings_error': self.load_error}

    def select(self, value):
        if (not isinstance(value, dict) or set(value) != {'slot', 'scene'}
                or type(value['slot']) is not int or not 0 <= value['slot'] < len(PAGE_NAMES)
                or not isinstance(value['scene'], str) or value['scene'] not in SCENES):
            raise ValueError('Invalid screen selection')
        with self.lock:
            if self.load_error:
                raise OSError('Screen settings need attention')
            if not available(value['scene']) and value['scene'] not in self.ids:
                raise ValueError('Screen image is not installed')
            updated = list(self.ids)
            updated[value['slot']] = value['scene']
            if not self._save(updated):
                return
        self.changed.set()

    def reorder(self, value):
        if (not isinstance(value, dict) or set(value) != {'expected', 'order'}
                or not isinstance(value['expected'], list)
                or not isinstance(value['order'], list)
                or len(value['expected']) != len(PAGE_NAMES)
                or len(value['order']) != len(PAGE_NAMES)
                or any(not isinstance(scene, str) for scene in value['expected'])
                or any(type(i) is not int for i in value['order'])
                or sorted(value['order']) != list(range(len(PAGE_NAMES)))):
            raise ValueError('Invalid screen order')
        with self.lock:
            if self.load_error:
                raise OSError('Screen settings need attention')
            if value['expected'] != self.ids:
                raise ValueError('Screen selection has changed')
            updated = [self.ids[i] for i in value['order']]
            if not self._save(updated):
                return
        self.changed.set()

    def _save(self, updated):
        # Called with the lock held so validation and the atomic write agree.
        if updated == self.ids:
            return False
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        try:
            with temporary.open('w', encoding='utf-8') as f:
                os.chmod(temporary, 0o600)
                json.dump(updated, f, separators=(',', ':'))
            temporary.replace(self.path)
        finally:
            temporary.unlink(missing_ok=True)
        self.ids = updated
        return True

    def confirm(self, ids):
        with self.lock:
            for i, scene in enumerate(ids):
                if i < len(self.ids):
                    self.delivered[i] = scene

    def confirm_slot(self, slot, scene):
        with self.lock:
            self.delivered[slot] = scene


def render_archive(scene, snapshot, animated=False, extended_anim=False, anim_frames=8):
    """Render only an explicitly retained, allowlisted version."""
    from token_tv.board_credits import apply_credit_badges
    from token_tv.board_low_quota import apply_one
    credits = True          # the versions that draw their own balance (the clock faces, Deep Space, the new cities) say so below
    if scene == 'zelda':
        from token_tv.board_zelda import render_quest
        result = render_quest(snapshot, animated=animated, anim_frames=anim_frames)
        image, payload = result if animated else (result, None)
        credits = False
    elif scene in PRIVATE_CITIES:
        from token_tv.board_cyber_scenes import render_city
        result = render_city(scene, snapshot, animated=animated, extended_anim=extended_anim)
        image, payload = result if animated else (result, None)
        credits = False
    elif scene == 'deep-space':
        from token_tv.board_space import render_cockpit
        result = render_cockpit(snapshot, animated=animated)
        image, payload = result if animated else (result, None)
        credits = False
    elif scene == 'game-boy-pocket':
        from token_tv.board_pages import LCD_GRID
        from token_tv.personal_faces import render_pocket
        image, payload = render_pocket(snapshot, screen=PAGE_SIZE, grid=LCD_GRID[scene], show_credits=True), None
        credits = False
    elif scene in ('pixel-retro', 'amber-terminal', 'orbit'):
        from token_tv.personal_faces import RENDERERS
        from token_tv.themes import render_retro
        renderer = render_retro if scene == 'pixel-retro' else RENDERERS[scene]
        image, payload = renderer(snapshot, screen=PAGE_SIZE, show_credits=True), None
        credits = False
    else:
        # Explicitly named historical renderers, never arbitrary module paths.
        from token_tv.board_code_workshop import render_forge as workshop
        from token_tv.board_code_editor import render_forge as editor
        from token_tv.board_forge import render_forge as neon_pixel
        from token_tv.board_neon_smooth import render_neon_smooth
        from token_tv.board_neon_realistic import render_neon_realistic
        from token_tv.board_prism import render_prism
        from token_tv.board_arcade_train import render_arcade as versus_train
        from token_tv.board_paradise_photo import render_paradise as paradise_photo
        from token_tv.board_cockpit_classic import render_dials as cockpit_classic
        renderers = {'code-workshop': workshop, 'code-editor': editor,
                     'neon-pixel': neon_pixel, 'neon-smooth': render_neon_smooth,
                     'neon-towers': render_neon_realistic, 'prism': render_prism,
                     'versus-train': versus_train, 'paradise-photo': paradise_photo,
                     'cockpit-classic': cockpit_classic}
        if scene not in renderers:
            raise ValueError('Unknown archived screen')
        result = renderers[scene](snapshot, animated=animated)
        image, payload = result if animated else (result, None)
    if credits:
        apply_credit_badges([image], [scene], snapshot)
    apply_one(image, scene, snapshot)         # the low-quota line, the last thing drawn (board_low_quota)
    return image, payload
