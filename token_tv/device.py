"""Confirmed SD_PRO photo API. Never flash or delete existing photographs."""
import json
import gzip
import uuid
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request
from token_tv.http import open_direct


FILES = ("tokentv.jpg", "tokentv.gif")
ALBUM_FACES = {
    'game-boy': 'Game Boy verde.jpg',
    'game-boy-pocket': 'Game Boy gris.jpg',
    'retro': 'Pixel Retro.jpg',
    'amber-terminal': 'Terminal Ambar.jpg',
    'orbit': 'Orbit.jpg',
}
# The album page accepts GIFs up to 240×240; keep both well under the free space.
LIMITS = {"tokentv.jpg": (60000, "image/jpeg"), "tokentv.gif": (400000, "image/gif")}
LIMITS.update({name: (60000, 'image/jpeg') for name in ALBUM_FACES.values()})
LEGACY_FILES = ("tokentv-c.jpg", "tokentv-m.jpg")


def rotation_interval(value):
    if type(value) is not int or (value != 0 and not 10 <= value <= 3600):
        raise ValueError('Display rotation must be 0 or 10–3600 seconds')
    return value


class PhotoDisplay:
    def __init__(self, base_url):
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.path not in ("", "/"):
            raise ValueError("A plain local display URL is required")
        self.base_url = base_url.rstrip("/")
        self.profile = 'sd_pro'

    def request(self, path, data=None, headers=None):
        with open_direct(Request(self.base_url + path, data=data, headers=headers or {}), timeout=20, no_proxy=True) as response:
            body = response.read()
            if body[:2] == b'\x1f\x8b':
                body = gzip.decompress(body)
            return response.status, body

    def capture(self):
        try:
            _, raw = self.request("/theme/list")
        except HTTPError as error:
            if error.code != 404:
                raise
            return self.capture_ultra()
        themes = json.loads(raw)
        _, raw = self.request("/photo/list")
        photos = json.loads(raw)
        if not any(t["id"] == 2 for t in themes["themes"]):
            raise ValueError("The confirmed photo theme is missing")
        return {"themes": themes["themes"], "theme_interval": themes["interval"],
                "files": [{"name": f["name"], "enabled": f["enabled"]} for f in photos["files"]],
                "photo_interval": photos["interval"]}

    def capture_ultra(self):
        version = json.loads(self.request('/v.json')[1])
        if version.get('m') != 'SmallTV-Ultra':
            raise ValueError('Unsupported clock model')
        app = json.loads(self.request('/app.json')[1])
        album = json.loads(self.request('/album.json')[1])
        rotation = json.loads(self.request('/theme_list.json')[1])
        if int(app['theme']) == 3:
            raise ValueError('Select a clock theme first: Ultra does not report the active photo for backup')
        original = {'profile': 'ultra', 'device_url': self.base_url,
                    'theme': int(app['theme']), 'autoplay': int(album['autoplay']),
                    'image_interval': int(album['i_i']), 'rotation': rotation}
        self.resume(original)
        return original

    def resume(self, original):
        if original.get('device_url', self.base_url) != self.base_url:
            raise ValueError('Display backup belongs to another clock')
        self.profile = original.get('profile', 'sd_pro')

    def ultra_set(self, **values):
        _, body = self.request('/set?' + urlencode(values, quote_via=quote))
        if body.strip() != b'OK':
            raise ValueError('Clock did not acknowledge display settings')

    def upload(self, name, image):
        if name in ALBUM_FACES.values() and self.profile != 'ultra':
            raise ValueError('Named album faces require the SmallTV Ultra')
        limit, mime = LIMITS.get(name, (0, ""))
        if not image or len(image) > limit:
            raise ValueError("Unexpected display image")
        if self.profile == 'ultra':
            free = int(json.loads(self.request('/space.json')[1])['free'])
            if free < len(image) + 32768:
                raise ValueError('Insufficient free space; existing photographs are never deleted')
        boundary = "TokenTV" + uuid.uuid4().hex
        body = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{name}"\r\n'
                f'Content-Type: {mime}\r\n\r\n').encode() + image + f"\r\n--{boundary}--\r\n".encode()
        endpoint = '/doUpload?dir=/image/' if self.profile == 'ultra' else '/photo/upload'
        status, _ = self.request(endpoint, body,
                                 {"Content-Type": "multipart/form-data; boundary=" + boundary})
        if self.profile == 'ultra':
            _, stored = self.request('/image/' + quote(name, safe=''))
            if stored != image:
                raise ValueError('Clock image verification failed')
        return {"file": name, "status": status, "bytes": len(image)}

    def own_files(self):
        """Names of the files TokenTV itself creates on the clock. Nothing else is ever deleted."""
        return set(FILES) | set(ALBUM_FACES.values()) | set(LEGACY_FILES)

    def listing(self, directory='/image/'):
        """File names in a clock folder, from the same page the clock's own web UI shows."""
        import re
        _, body = self.request('/filelist?dir=' + quote(directory, safe='/'))
        return re.findall(r"<a href='" + re.escape(directory) + r"([^']+)'>", body.decode('utf-8', 'replace'))

    def delete_own(self, name):
        """Remove one of our own files from the clock's image folder (never anyone else's)."""
        if name not in self.own_files():
            raise ValueError('Refusing to delete a file TokenTV did not create')
        self.request('/delete?file=' + quote('/image/' + name, safe=''))

    def toggle(self, category, key, value, enabled):
        self.request("/" + category + "/toggle?" + urlencode({key: value, "state": int(enabled)}, quote_via=quote))

    def activate(self, original, name=FILES[0], rotation_seconds=0):
        if name not in FILES and not (original.get('profile') == 'ultra' and name in ALBUM_FACES.values()):
            raise ValueError('Unexpected display filename')
        rotation_seconds = rotation_interval(rotation_seconds)
        self.resume(original)
        if self.profile == 'ultra':
            rotation = original['rotation']
            if rotation_seconds:
                flags = rotation['list'].split(',')
                theme = original['theme']
                if (len(flags) < 3 or any(flag not in ('0', '1') for flag in flags)
                        or type(theme) is not int or not 1 <= theme <= len(flags) or theme == 3):
                    raise ValueError('Original clock theme is required for rotation')
                selected = ['0'] * len(flags)
                selected[theme - 1] = selected[2] = '1'
            self.ultra_set(theme_list=rotation['list'], sw_en=0, theme_interval=rotation['sw_i'])
            self.ultra_set(autoplay=0, i_i=original['image_interval'])
            self.ultra_set(theme=3)
            self.ultra_set(img='/image/' + name)
            if rotation_seconds:
                self.ultra_set(theme_list=','.join(selected), sw_en=1, theme_interval=rotation_seconds)
            return
        if rotation_seconds:
            raise ValueError('Clock rotation is only supported on the SmallTV Ultra')
        # Show only our current file, then select the photo theme; retain old files.
        current = self.capture()
        enabled = {f['name']: f['enabled'] for f in current['files']}
        if not enabled.get(name):
            self.toggle("photo", "name", name, True)
        for f in current['files']:
            if f["name"] != name and f['enabled']:
                self.toggle("photo", "name", f["name"], False)
        if current['photo_interval'] != 10:
            self.request("/photo/interval?val=10")
        if not any(t['id'] == 2 and t['enabled'] for t in current['themes']):
            self.toggle("theme", "id", 2, True)
        for t in current["themes"]:
            if t["id"] != 2 and t['enabled']:
                self.toggle("theme", "id", t["id"], False)

    def restore(self, original):
        self.resume(original)
        if self.profile == 'ultra':
            self.ultra_set(autoplay=original['autoplay'], i_i=original['image_interval'])
            self.ultra_set(theme=original['theme'])
            rotation = original['rotation']
            self.ultra_set(theme_list=rotation['list'], sw_en=rotation['sw_en'], theme_interval=rotation['sw_i'])
            return
        for f in original["files"]:
            self.toggle("photo", "name", f["name"], f["enabled"])
        _, raw = self.request("/photo/list")
        present = {f["name"] for f in json.loads(raw)["files"]}
        for name in FILES + LEGACY_FILES:
            if name in present and not any(f["name"] == name for f in original["files"]):
                self.toggle("photo", "name", name, False)
        self.request("/photo/interval?val=" + str(original["photo_interval"]))
        self.request("/theme/interval?val=" + str(original["theme_interval"]))
        for enabled in (True, False):
            for t in original["themes"]:
                if t["enabled"] == enabled:
                    self.toggle("theme", "id", t["id"], enabled)
