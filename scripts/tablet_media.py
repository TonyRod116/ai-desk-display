"""Helpers that prepare the tablet's scene files, offline and never by the running service.

Everything lands in the private folder (`~/.local/share/ai-desk-display/tablet/`), outside Git. The only video encoder on this
computer is the ffmpeg that Playwright ships: it writes VP8 WebM and reads only MJPEG on a pipe, so frames travel as 4:4:4 JPEG at
quality 100 (visually lossless; plain 4:2:0 would smear the colour edges of pixel art). Pixel scenes are encoded at 2x so VP8's
half-resolution colour still lands on whole source pixels.
"""
import fcntl
import json
import os
import shutil
import subprocess
from io import BytesIO
from pathlib import Path
from tempfile import NamedTemporaryFile

from PIL import Image

PRIVATE = Path.home() / '.local/share/ai-desk-display/tablet'
MANIFEST = 'scenes.json'
MAX_VIDEO_BYTES = 48 * 1024 * 1024     # the server refuses anything bigger
MAX_IMAGE_BYTES = 8 * 1024 * 1024
LOOKS = ('crt', 'lcd', 'photo', 'plain', 'game')


def find_ffmpeg():
    """The system ffmpeg, else the one Playwright downloaded; None when neither exists."""
    found = shutil.which('ffmpeg')
    if found:
        return Path(found)
    bundled = sorted(Path.home().glob('.cache/ms-playwright/ffmpeg-*/ffmpeg-linux'))
    return bundled[-1] if bundled else None


def _write_atomically(path, writer, limit):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, suffix=path.suffix, delete=False) as handle:
        temporary = Path(handle.name)
    try:
        writer(temporary)
        if not 0 < temporary.stat().st_size <= limit:
            raise ValueError(f'{path.name} is empty or larger than the tablet server allows')
        os.chmod(temporary, 0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return path


def encode_webm(frames, fps, destination, *, scale=1, crf=8, max_kbps=10000, speed=1, qmax=40, rate_cap_kbps=None):
    """Encode same-sized PIL frames into a looping-ready VP8 WebM. `scale` upscales with nearest neighbour first.

    Returns (width, height, frame_count). Raises RuntimeError without an encoder or when ffmpeg fails."""
    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        raise RuntimeError('No ffmpeg: install one or run `playwright install` for the one it bundles')
    count, size = 0, None

    def run(target):
        nonlocal count, size
        command = [str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'image2pipe', '-c:v', 'mjpeg',
                   '-framerate', str(fps), '-i', 'pipe:0', '-an', '-c:v', 'libvpx', '-b:v', f'{max_kbps}k', '-crf', str(crf),
                   '-qmin', '0', '-qmax', str(qmax), '-pix_fmt', 'yuv420p', '-auto-alt-ref', '0', '-deadline', 'good',
                   '-cpu-used', str(speed), '-g', '90']
        if rate_cap_kbps is not None:
            command.extend(['-maxrate', f'{rate_cap_kbps}k', '-bufsize', f'{2 * rate_cap_kbps}k'])
        command.extend(['-f', 'webm', str(target)])
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for frame in frames:
                image = frame.convert('RGB')
                if scale != 1:
                    image = image.resize((image.width * scale, image.height * scale), Image.Resampling.NEAREST)
                if size is None:
                    size = image.size
                elif image.size != size:
                    raise ValueError('All frames of a video must have the same size')
                buffer = BytesIO()
                image.save(buffer, format='JPEG', quality=100, subsampling=0)
                process.stdin.write(buffer.getvalue())
                count += 1
        except BrokenPipeError:
            pass
        finally:
            try:
                process.stdin.close()      # always: ffmpeg waits for the end of its input, and so would reading its errors
            except OSError:
                pass
            error = process.stderr.read().decode('utf-8', 'replace')[:400]
            code = process.wait()
            process.stderr.close()
        if code != 0 or count == 0:
            raise RuntimeError(f'ffmpeg failed ({code}): {error.strip()}')

    _write_atomically(destination, run, MAX_VIDEO_BYTES)
    return size[0], size[1], count


def save_image(image, destination, *, quality=90):
    """A still picture, by the destination's extension (.webp, .jpg or .png), written atomically with owner-only permissions."""
    destination = Path(destination)
    kind = destination.suffix.lower()
    options = {'.webp': dict(format='WEBP', quality=quality, method=4), '.jpg': dict(format='JPEG', quality=quality, optimize=True,
               subsampling=0), '.png': dict(format='PNG', optimize=True)}[kind]
    return _write_atomically(destination, lambda target: image.convert('RGB').save(target, **options), MAX_IMAGE_BYTES)


def save_thumbnail(image, destination, size=(240, 160)):
    thumb = image.convert('RGB').copy()
    thumb.thumbnail(size, Image.Resampling.LANCZOS)
    return save_image(thumb, destination, quality=78)


def scene_entry(look, media_file, kind, width, height, *, fps=None, loop_seconds=None, still=None, focus=(.5, .5), rate=1, data=None):
    """One scene's manifest entry. The server checks every field again before it tells the page about it."""
    if look not in LOOKS:
        raise ValueError('Unknown look')
    media = {'kind': kind, 'file': media_file, 'width': int(width), 'height': int(height)}
    if fps is not None:
        media['fps'] = fps
    if loop_seconds is not None:
        media['loop_seconds'] = round(loop_seconds, 3)
    entry = {'look': look, 'media': media, 'focus': [float(focus[0]), float(focus[1])], 'rate': float(rate)}
    if still:
        entry['still'] = still
    if data:
        entry['data'] = data
    return entry


def update_manifest(name, entry, directory=PRIVATE):
    """Add or replace one scene in `scenes.json` (several preparations may run at once, so under a lock)."""
    directory = Path(directory)
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    with open(directory / '.scenes.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = directory / MANIFEST
        try:
            manifest = json.loads(path.read_text(encoding='utf-8'))
            scenes = manifest['scenes'] if manifest.get('version') == 2 else {}
        except (OSError, ValueError, KeyError, AttributeError):
            scenes = {}
        scenes[name] = entry
        _write_atomically(path, lambda target: target.write_text(json.dumps({'version': 2, 'scenes': scenes}, indent=1, sort_keys=True),
                                                                encoding='utf-8'), 64 * 1024)
    return scenes
