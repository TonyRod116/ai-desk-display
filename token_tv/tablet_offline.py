"""An authenticated inventory of prepared artwork, never readings or credentials.

The APK carries executable UI code. This inventory lets it save only fixed,
already-served scene files and the scene/photo catalogues on its own device.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import threading

MAX_FILES = 256
MAX_TOTAL = 2 * 1024 ** 3
MAX_FILE = 48 * 1024 ** 2


class OfflineUnavailable(Exception):
    pass


def _json(value):
    return json.dumps(value, separators=(',', ':'), allow_nan=False).encode()


class OfflineBundle:
    def __init__(self, directory, routes):
        self.directory, self.routes = Path(directory), dict(routes)
        self._lock = threading.Lock()
        self._hashes = {}

    @staticmethod
    def _signature(info):
        return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns

    def _file(self, route):
        mapped = self.routes.get(route)
        if not mapped or not mapped[0].startswith('@') or '/' in mapped[0][1:]:
            raise OfflineUnavailable()
        path = self.directory / mapped[0][1:]
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                mime = mapped[1].split(';', 1)[0]
                limit = min(MAX_FILE, 48 * 1024 ** 2 if mime == 'video/webm' else 512 * 1024 if mime == 'application/json' else 8 * 1024 ** 2)
                if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                    raise OfflineUnavailable()
                signature = self._signature(info)
                cached = self._hashes.get(route)
                if cached and cached[0] == signature:
                    digest = cached[1]
                else:
                    digest = hashlib.sha256()
                    while chunk := stream.read(65536):
                        digest.update(chunk)
                    digest = digest.hexdigest()
                    if self._signature(os.fstat(stream.fileno())) != signature or self._signature(path.stat()) != signature:
                        raise OfflineUnavailable()
                    self._hashes[route] = (signature, digest)
                return {'path': route, 'size': info.st_size, 'sha256': digest, 'mime': mime}
        except OSError as exc:
            raise OfflineUnavailable() from exc

    def manifest(self, scenes, photos):
        if not self._lock.acquire(blocking=False):
            raise OfflineUnavailable()
        try:
            needed = set()

            def visit(value):
                if isinstance(value, str) and value.startswith('/assets/'):
                    needed.add(value)
                elif isinstance(value, dict):
                    for item in value.values():
                        visit(item)
                elif isinstance(value, list):
                    for item in value:
                        visit(item)

            visit(scenes)
            visit(photos)
            optional = {'/assets/city.png', '/assets/paradise.png'}
            for name in scenes.get('scenes', []):
                optional.add(f'/assets/thumb-{name}.webp')
                optional.add(f'/assets/scene-{name}.webp')
            for route in optional:
                mapped = self.routes.get(route)
                if mapped and mapped[0].startswith('@') and (self.directory / mapped[0][1:]).is_file():
                    needed.add(route)
            if len(needed) + 2 > MAX_FILES:
                raise OfflineUnavailable()
            files = [self._file(route) for route in sorted(needed)]
            for route, data in (('/api/scenes', scenes), ('/api/photos', {'photos': photos})):
                raw = _json(data)
                files.append({'path': route, 'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'mime': 'application/json'})
            total = sum(entry['size'] for entry in files)
            if total > MAX_TOTAL:
                raise OfflineUnavailable()
            revision = hashlib.sha256(_json(files)).hexdigest()
            return {'schema': 1, 'revision': revision, 'total': total, 'files': files}
        finally:
            self._lock.release()
