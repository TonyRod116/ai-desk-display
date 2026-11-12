#!/usr/bin/env python3
"""Build the AI Desk tablet app with its local UI, without Gradle or Android Studio.

    python -B scripts/build_tablet_app.py                 # asks the tablet service on this computer for its address and certificate
    python -B scripts/build_tablet_app.py --url https://192.0.2.10:8667 --fingerprint AB:CD:...   # (a documentation address)
    python -B scripts/build_tablet_app.py --out DIR --debug

The pipeline is the manual one: aapt2 compile + link (manifest, resources, R.java), javac --release 11 against the platform's
android.jar, d8, classes.dex into the APK, zipalign, apksigner. The server's address and the SHA-256 fingerprint of its certificate are
written into a generated `Config` class, so the app trusts exactly that certificate and loads exactly that address. Nothing is
installed on any device and no certificate or key file of the service is ever read: the fingerprint comes from the service's
loopback setup endpoint (or the command line).

Output (default `~/.local/share/ai-desk-display/tablet/app/`): `ai-desk-tablet.apk` and `ai-desk-tablet.apk.json` (version, sha256,
built_at, host). A `--debug` build (WebView debugging on, its own signing key) writes `ai-desk-tablet-debug.apk` instead, so a
debuggable file can never replace the one the tablet service offers for download.

The signing key is created once with keytool in `~/.local/share/ai-desk-display/tablet/app-signing/` (owner-only files, never in Git,
never printed). Keep it: Android only installs an update over an app signed with the same key.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import functools
import hashlib
import ipaddress
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / 'android'
PRIVATE = Path.home() / '.local/share/ai-desk-display/tablet'
APP_DIR = PRIVATE / 'app'
SIGNING_DIR = PRIVATE / 'app-signing'
SETUP_URL = 'http://127.0.0.1:8666/api/setup'
PACKAGE = 'app.aidesk.tablet'
APK_NAME = 'ai-desk-tablet.apk'
DEBUG_APK_NAME = 'ai-desk-tablet-debug.apk'
COUNTER_NAME = 'build-counter.txt'
BRIDGE_CONTRACT = 1             # first part of the version name; goes up only when `window.AiDeskApp` changes incompatibly
MIN_SDK, TARGET_SDK = 26, 35    # as in AndroidManifest.xml (the build checks the finished APK against them)
KEY_ALIAS = 'aidesk'
BRIDGE_METHODS = ('battery', 'fingerprint', 'installUpdate', 'keepAwake', 'light', 'offlineStatus', 'reload', 'setBrightness', 'syncOffline', 'version', 'vibrate')   # window.AiDeskApp, nothing else
PERMISSIONS = ('android.permission.ACCESS_NETWORK_STATE', 'android.permission.INTERNET', 'android.permission.REQUEST_INSTALL_PACKAGES', 'android.permission.VIBRATE')
SETUP_LIMIT = 64 * 1024


class BuildError(RuntimeError):
    """A failure with a message meant to be read: a missing tool, a bad argument, a step that did not work."""


# ---------------------------------------------------------------------------------------------------------------------------------
# What the app is built for: the server's address and the certificate it must present
# ---------------------------------------------------------------------------------------------------------------------------------

def parse_origin(url) -> tuple[str, str, int]:
    """`https://host[:port]` -> (origin, host, port). Only the origin: no user, path, query or fragment."""
    text = str(url or '').strip()
    try:
        parts = urllib.parse.urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise BuildError(f'Not a usable server address: {text!r}') from exc
    if parts.scheme != 'https':
        raise BuildError('The server address must start with https:// (the tablet service only speaks HTTPS)')
    if parts.username is not None or parts.password is not None or parts.query or parts.fragment or parts.path not in ('', '/'):
        raise BuildError('Give the server address as https://host:port only (no user name, path or query)')
    host = (parts.hostname or '').lower()
    if not host:
        raise BuildError('The server address has no host')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
        if not re.fullmatch(r'[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*', host) or len(host) > 253:
            raise BuildError(f'Not a usable host name: {host!r}')
    if ip is not None:
        if ip.is_loopback or ip.is_unspecified or ip.is_multicast:
            raise BuildError(f'{host} is this computer itself: the tablet cannot reach it. Use the PC\'s address on the Wi-Fi network')
        if not ip.is_private:
            raise BuildError(f'{host} is not a private network address: the app is for the local network only')
        host = str(ip)   # the form WebView reports URLs in (an IPv6 address is compressed and lower case)
    port = 443 if port is None else port
    if not 1 <= port <= 65535:
        raise BuildError(f'Not a usable port: {port}')
    shown = f'[{host}]' if ip is not None and ip.version == 6 else host
    origin = f'https://{shown}' + ('' if port == 443 else f':{port}')
    return origin, host, port


def parse_fingerprint(text) -> str:
    """SHA-256 of the certificate as the setup page shows it (`AB:CD:...`) or as plain hex -> 64 lower-case hex digits."""
    cleaned = re.sub(r'[\s:]', '', str(text or '')).lower()
    if not re.fullmatch(r'[0-9a-f]{64}', cleaned):
        raise BuildError('The certificate fingerprint must be a SHA-256: 64 hex digits, with or without colons')
    return cleaned


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_setup(setup_url: str = SETUP_URL, timeout: float = 5) -> tuple[str, str]:
    """Ask the tablet service's loopback setup endpoint for `url` and `fingerprint` (it also reports sensors; those are ignored)."""
    parts = urllib.parse.urlsplit(setup_url)
    if parts.scheme != 'http' or parts.hostname not in ('127.0.0.1', 'localhost'):
        raise BuildError('The setup endpoint must be on this computer (http://127.0.0.1:PORT/api/setup)')
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(urllib.request.Request(setup_url, headers={'Accept': 'application/json'}), timeout=timeout) as response:
            body = response.read(SETUP_LIMIT + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise BuildError(f'The tablet service does not answer on {setup_url} (is ai-desk-tablet.service running?). '
                         'Pass --url and --fingerprint to build without it') from exc
    try:
        if len(body) > SETUP_LIMIT:
            raise ValueError('too long')
        data = json.loads(body)
        url, fingerprint = data['url'], data['fingerprint']
    except (ValueError, KeyError, TypeError) as exc:
        raise BuildError(f'{setup_url} did not return the address and fingerprint the build needs') from exc
    return url, fingerprint


# ---------------------------------------------------------------------------------------------------------------------------------
# The tools. On this PC they are the Windows ones, reached through WSL interop (paths must be translated for them)
# ---------------------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Tool:
    path: Path

    @property
    def windows(self) -> bool:
        return self.path.suffix.lower() == '.exe'


@dataclass(frozen=True)
class Toolchain:
    sdk: Path
    build_tools: Path
    platform_jar: Path
    aapt2: Tool
    zipalign: Tool
    java: Tool
    javac: Tool
    keytool: Tool
    d8_jar: Path
    apksigner_jar: Path
    dexdump: Tool | None = None


@functools.lru_cache(maxsize=None)
def _wslpath(path: str) -> str:
    try:
        done = subprocess.run(['wslpath', '-w', path], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError('A Windows tool needs wslpath to translate paths, and it is not available') from exc
    if done.returncode != 0 or not done.stdout.strip():
        raise BuildError(f'wslpath could not translate {path}')
    return done.stdout.strip()


def native(path, windows: bool) -> str:
    """The text a tool expects for a path: Windows tools get C:\\... or \\\\wsl.localhost\\..., Linux tools the path as it is."""
    return _wslpath(str(path)) if windows else str(path)


def _executable(directory: Path, name: str):
    for candidate in (directory / f'{name}.exe', directory / name):
        if candidate.is_file():
            return candidate
    return None


def _version_key(name: str):
    return tuple(int(part) for part in re.findall(r'\d+', name)) or (0,)


def _sdk_candidates(explicit):
    if explicit:
        yield Path(explicit).expanduser()
        return
    for variable in ('ANDROID_HOME', 'ANDROID_SDK_ROOT'):
        if os.environ.get(variable):
            yield Path(os.environ[variable])
    yield Path.home() / 'Android/Sdk'
    yield from sorted(Path('/mnt/c/Users').glob('*/AppData/Local/Android/Sdk'))


def _jdk_candidates(explicit):
    if explicit:
        yield Path(explicit).expanduser()
        return
    if os.environ.get('JAVA_HOME'):
        yield Path(os.environ['JAVA_HOME'])
    for pattern in ('/mnt/c/Program Files/Eclipse Adoptium/jdk-*', '/mnt/c/Program Files/Java/jdk*',
                    '/mnt/c/Program Files/Microsoft/jdk-*', '/usr/lib/jvm/*'):
        yield from sorted(Path('/').glob(pattern.lstrip('/')), key=lambda p: _version_key(p.name), reverse=True)


def find_toolchain(sdk=None, jdk=None) -> Toolchain:
    """Locate the Android SDK pieces and the JDK, or say exactly which one is missing and how to point at it."""
    sdk_root = next((c for c in _sdk_candidates(sdk) if (c / 'build-tools').is_dir() and (c / 'platforms').is_dir()), None)
    if sdk_root is None:
        raise BuildError('No Android SDK with build-tools and platforms found. Install the SDK, or pass --sdk DIR '
                         '(or set ANDROID_HOME). Looked in ANDROID_HOME, ~/Android/Sdk and /mnt/c/Users/*/AppData/Local/Android/Sdk')
    sdk_root = sdk_root.resolve()   # absolute: the tools run in another folder, a relative path would point nowhere
    build_tools = None
    for candidate in sorted((p for p in (sdk_root / 'build-tools').iterdir() if p.is_dir()), key=lambda p: _version_key(p.name), reverse=True):
        if (_executable(candidate, 'aapt2') and _executable(candidate, 'zipalign')
                and (candidate / 'lib/d8.jar').is_file() and (candidate / 'lib/apksigner.jar').is_file()):
            build_tools = candidate
            break
    if build_tools is None:
        raise BuildError(f'{sdk_root / "build-tools"} has no complete build-tools folder (aapt2, zipalign, lib/d8.jar, lib/apksigner.jar)')
    platforms = [p for p in (sdk_root / 'platforms').iterdir() if (p / 'android.jar').is_file() and _version_key(p.name)[0] >= TARGET_SDK]
    platforms.sort(key=lambda p: (_version_key(p.name) != (TARGET_SDK,), _version_key(p.name)))   # android-35 first, else the nearest newer
    if not platforms:
        raise BuildError(f'{sdk_root / "platforms"} has no android-{TARGET_SDK} (or newer) platform with an android.jar')
    jdk_root = None
    for candidate in _jdk_candidates(jdk):
        if all(_executable(candidate / 'bin', name) for name in ('java', 'javac', 'keytool')):
            jdk_root = candidate
            break
    if jdk_root is None:
        raise BuildError('No JDK (java, javac, keytool) found. Install JDK 17 or newer, or pass --jdk DIR (or set JAVA_HOME)')
    bin_dir = jdk_root.resolve() / 'bin'
    return Toolchain(sdk=sdk_root, build_tools=build_tools, platform_jar=platforms[0] / 'android.jar',
                     aapt2=Tool(_executable(build_tools, 'aapt2')), zipalign=Tool(_executable(build_tools, 'zipalign')),
                     java=Tool(_executable(bin_dir, 'java')), javac=Tool(_executable(bin_dir, 'javac')),
                     keytool=Tool(_executable(bin_dir, 'keytool')),
                     d8_jar=build_tools / 'lib/d8.jar', apksigner_jar=build_tools / 'lib/apksigner.jar',
                     dexdump=Tool(_executable(build_tools, 'dexdump')) if _executable(build_tools, 'dexdump') else None)


def _decode(data: bytes) -> str:
    return data.decode('utf-8', errors='replace')


def call(tool: Tool, *args, label: str | None = None, cwd=None, timeout: float = 600) -> str:
    """Run one tool. Path arguments are translated for Windows tools; strings are passed as they are. Returns stdout + stderr."""
    argv = [str(tool.path)] + [native(a, tool.windows) if isinstance(a, Path) else str(a) for a in args]
    try:
        done = subprocess.run(argv, capture_output=True, timeout=timeout, cwd=str(cwd) if cwd else None, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError(f'Could not run {tool.path.name}: {exc}') from exc
    text = (_decode(done.stdout) + _decode(done.stderr)).strip()
    if done.returncode != 0:
        tail = '\n'.join(text.splitlines()[-25:])
        raise BuildError(f'{label or tool.path.name} failed (exit {done.returncode}):\n{tail}')
    return text


def java_jar(tools: Toolchain, jar: Path, *args, label: str, cwd=None) -> str:
    return call(tools.java, '-jar', jar, *args, label=label, cwd=cwd)


def scratch_parent(tools: Toolchain):
    """Where build folders go: for Windows tools the Windows user's Temp (plain C:\\ paths, no \\\\wsl.localhost); else the default."""
    if tools.aapt2.windows:
        for ancestor in tools.sdk.parents:
            if ancestor.name == 'Local' and ancestor.parent.name == 'AppData' and (ancestor / 'Temp').is_dir():
                return ancestor / 'Temp'
    return Path(tempfile.gettempdir())


@contextlib.contextmanager
def workspace(tools: Toolchain):
    """A scratch folder that is always removed."""
    work = Path(tempfile.mkdtemp(prefix='ai-desk-app-build-', dir=str(scratch_parent(tools))))
    try:
        yield work
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---------------------------------------------------------------------------------------------------------------------------------
# Signing key (created once, private) and version counter
# ---------------------------------------------------------------------------------------------------------------------------------

def ensure_signing_key(tools: Toolchain, directory: Path, kind: str) -> tuple[Path, Path]:
    """The keystore and password file for 'release' or 'debug', created with keytool the first time. Never printed."""
    directory = Path(directory).expanduser().resolve()   # absolute: keytool and apksigner run in another folder
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    store, password = directory / f'{kind}.p12', directory / f'{kind}.pass'
    if store.is_file() and password.is_file():
        return store, password
    if store.exists() or password.exists():
        raise BuildError(f'{directory} holds only half of the {kind} signing key; restore the missing file (a key cannot be recreated '
                         'under the same identity) or remove both files and accept that the app must then be uninstalled before the next install')
    descriptor = os.open(password, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        handle.write(secrets.token_hex(24))
    try:
        call(tools.keytool, '-genkeypair', '-alias', KEY_ALIAS, '-keyalg', 'RSA', '-keysize', '2048', '-sigalg', 'SHA256withRSA',
             '-validity', '10000', '-dname', f'CN=AI Desk tablet app ({kind})', '-keystore', store, '-storetype', 'PKCS12',
             '-storepass:file', password, '-keypass:file', password, label='keytool')
        os.chmod(store, 0o600)
    except BaseException:
        store.unlink(missing_ok=True)
        password.unlink(missing_ok=True)
        raise
    return store, password


def _read_int(path: Path) -> int:
    try:
        return max(0, int(path.read_text().strip()))
    except (OSError, ValueError):
        return 0


def next_version_code(out_dir: Path, apk_name: str = APK_NAME) -> int:
    """One more than the last successful build in `out_dir` (the counter file, or the JSON of the last APK if the counter is lost)."""
    last = _read_int(Path(out_dir) / COUNTER_NAME)
    try:
        last = max(last, int(json.loads((Path(out_dir) / (apk_name + '.json')).read_text())['version_code']))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return last + 1


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + '.', suffix='.tmp')
    try:
        with os.fdopen(descriptor, 'wb') as handle:
            handle.write(data)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(temporary)


# ---------------------------------------------------------------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------------------------------------------------------------

CONFIG_JAVA = '''package app.aidesk.tablet;

/** Generated by scripts/build_tablet_app.py for this one build. Never edited by hand, never committed. */
final class Config {{
    static final String ORIGIN = "{origin}";
    static final String START_URL = "{origin}/";
    static final String FINGERPRINT = "{fingerprint}";
    static final String VERSION_NAME = "{version_name}";
    static final int VERSION_CODE = {version_code};
    static final boolean DEBUG = {debug};

    private Config() {{
    }}
}}
'''


def build_apk(tools: Toolchain, work: Path, *, origin: str, fingerprint: str, version_code: int, version_name: str, debug: bool,
              keystore: Path, password: Path, source: Path = ANDROID) -> Path:
    """Run the pipeline in `work` and return the signed, aligned APK inside it."""
    project = work / 'android'
    shutil.copytree(source, project)
    gen, classes, dex = work / 'gen', work / 'classes', work / 'dex'
    for folder in (gen, classes, dex):
        folder.mkdir()
    (gen / 'Config.java').write_text(CONFIG_JAVA.format(origin=origin, fingerprint=fingerprint, version_name=version_name,
                                                        version_code=version_code, debug='true' if debug else 'false'), encoding='utf-8')
    compiled, base = work / 'compiled.zip', work / 'base.apk'
    call(tools.aapt2, 'compile', '--dir', project / 'res', '-o', compiled, label='aapt2 compile', cwd=work)
    link = ['link', '-o', base, '-I', tools.platform_jar, '--manifest', project / 'AndroidManifest.xml', '--java', gen,
            '--version-code', str(version_code), '--version-name', version_name, '--auto-add-overlay']
    if debug:
        link.append('--debug-mode')
    call(tools.aapt2, *link, compiled, label='aapt2 link', cwd=work)
    sources = sorted((project / 'src').rglob('*.java')) + sorted(gen.rglob('*.java'))
    call(tools.javac, '--release', '11', '-encoding', 'UTF-8', '-XDstringConcat=inline', '-classpath', tools.platform_jar,
         '-d', classes, *sources, label='javac', cwd=work)
    class_files = sorted(classes.rglob('*.class'))
    call(tools.java, '-cp', tools.d8_jar, 'com.android.tools.r8.D8', '--debug' if debug else '--release', '--min-api', str(MIN_SDK),
         '--lib', tools.platform_jar, '--output', dex, *class_files, label='d8', cwd=work)
    if not (dex / 'classes.dex').is_file():
        raise BuildError('d8 produced no classes.dex')
    with zipfile.ZipFile(base, 'a') as archive:
        archive.write(dex / 'classes.dex', 'classes.dex', compress_type=zipfile.ZIP_DEFLATED)
        # Executable UI ships in the signed APK. Private photos, films and atlases
        # are transferred separately to this app's own storage, never embedded here.
        web = ROOT / 'token_tv/tablet_web'
        for asset in sorted(web.iterdir()):
            if asset.is_symlink() or not asset.is_file():
                continue
            if asset.name == 'index.html' or (re.fullmatch(r'[a-z0-9-]{1,40}\.(js|css)', asset.name)
                                            and asset.name not in ('setup.js', 'login.js', 'access.css')):
                archive.write(asset, 'assets/web/' + asset.name, compress_type=zipfile.ZIP_DEFLATED)
    aligned, signed = work / 'aligned.apk', work / 'signed.apk'
    call(tools.zipalign, '-f', '-p', '4', base, aligned, label='zipalign', cwd=work)
    java_jar(tools, tools.apksigner_jar, 'sign', '--ks', keystore, '--ks-key-alias', KEY_ALIAS,
             '--ks-pass', 'file:' + native(password, tools.java.windows), '--v1-signing-enabled', 'false',
             '--v2-signing-enabled', 'true', '--v3-signing-enabled', 'true', '--v4-signing-enabled', 'false',
             '--out', signed, aligned, label='apksigner sign', cwd=work)
    return signed


def bridge_methods_in_dex(tools: Toolchain, apk: Path):
    """Sorted names of the methods the code marks @JavascriptInterface at runtime visibility (the only ones Android's WebView hands to
    the page), read back from the finished classes.dex; None when this SDK has no dexdump."""
    if tools.dexdump is None:
        return None
    with workspace(tools) as scratch:
        with zipfile.ZipFile(apk) as archive:
            (scratch / 'classes.dex').write_bytes(archive.read('classes.dex'))
        listing = call(tools.dexdump, '-a', scratch / 'classes.dex', label='dexdump', cwd=scratch)
    return sorted(re.findall(r"Annotations on method #\d+ '([^']+)'\s+VISIBILITY_RUNTIME Landroid/webkit/JavascriptInterface;", listing))


def verify_apk(tools: Toolchain, apk: Path, *, version_code: int, version_name: str, debug: bool) -> dict:
    """apksigner verify + aapt2 dump badging/xmltree. Raises BuildError on anything unexpected; returns facts about the APK."""
    report = java_jar(tools, tools.apksigner_jar, 'verify', '--verbose', '--print-certs', apk, label='apksigner verify')
    if not report.startswith('Verifies') or not re.search(r'v2 scheme[^\n]*: true', report):
        raise BuildError('apksigner does not verify the APK with the v2 scheme:\n' + report)
    signer = re.search(r'Signer #1 certificate SHA-256 digest: ([0-9a-f]{64})', report)
    badging = call(tools.aapt2, 'dump', 'badging', apk, label='aapt2 dump badging')
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", badging)
    permissions = tuple(sorted(re.findall(r"uses-permission: name='([^']+)'", badging)))
    problems = []
    if not package or package.groups() != (PACKAGE, str(version_code), version_name):
        problems.append(f'package/version is {package.groups() if package else None}')
    if f"minSdkVersion:'{MIN_SDK}'" not in badging or f"targetSdkVersion:'{TARGET_SDK}'" not in badging:
        problems.append(f'SDK levels are not {MIN_SDK}/{TARGET_SDK}')
    if permissions != PERMISSIONS:
        problems.append(f'permissions are {permissions}')
    if f"launchable-activity: name='{PACKAGE}.MainActivity'" not in badging:
        problems.append('MainActivity is not the launchable activity')
    manifest = call(tools.aapt2, 'dump', 'xmltree', '--file', 'AndroidManifest.xml', apk, label='aapt2 dump xmltree')
    exported = re.findall(r'exported\(0x[0-9a-f]+\)=true', manifest)
    components = re.findall(r'E: (activity|activity-alias|service|receiver|provider)\b', manifest)
    if components != ['activity'] or len(exported) != 1:
        problems.append(f'components {components}, exported {len(exported)}')
    debuggable = bool(re.search(r'debuggable\(0x[0-9a-f]+\)=true', manifest))
    if debuggable != debug:
        problems.append(f'debuggable is {debuggable}, expected {debug}')
    with zipfile.ZipFile(apk) as archive:
        if archive.testzip() is not None or 'classes.dex' not in archive.namelist():
            problems.append('the archive is damaged or has no classes.dex')
    try:
        call(tools.zipalign, '-c', '-p', '4', apk, label='zipalign -c')   # resources.arsc must stay 4-byte aligned after signing too
    except BuildError as exc:
        problems.append(f'the archive is not aligned ({exc})')
    exposed = bridge_methods_in_dex(tools, apk)
    if exposed is not None and exposed != sorted(BRIDGE_METHODS):
        problems.append(f'the bridge exposes {exposed}')
    if problems:
        raise BuildError('The finished APK does not match what was asked for: ' + '; '.join(problems))
    return {'signer_sha256': signer.group(1) if signer else None, 'permissions': list(permissions), 'bridge': exposed}


def build(url, fingerprint, *, out_dir: Path = APP_DIR, debug: bool = False, keystore_dir: Path = SIGNING_DIR,
          sdk=None, jdk=None, tools: Toolchain | None = None, source: Path = ANDROID) -> dict:
    """Build, sign and verify the APK for this server and certificate; write it (and its JSON) into `out_dir`. Returns the JSON.

    Nothing is written to `out_dir` (and the version counter does not move) unless the finished APK passed every check."""
    origin, host, port = parse_origin(url)
    pin = parse_fingerprint(fingerprint)
    tools = tools or find_toolchain(sdk, jdk)
    out_dir = Path(out_dir)
    apk_name = DEBUG_APK_NAME if debug else APK_NAME
    version_code = next_version_code(out_dir, apk_name)
    version_name = f'{BRIDGE_CONTRACT}.{version_code}'
    keystore, password = ensure_signing_key(tools, Path(keystore_dir), 'debug' if debug else 'release')
    with workspace(tools) as work:
        signed = build_apk(tools, work, origin=origin, fingerprint=pin, version_code=version_code, version_name=version_name,
                           debug=debug, keystore=keystore, password=password, source=source)
        facts = verify_apk(tools, signed, version_code=version_code, version_name=version_name, debug=debug)
        data = signed.read_bytes()
    info = {'package': PACKAGE, 'file': apk_name, 'version_name': version_name, 'version_code': version_code,
            'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'built_at': datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'host': host, 'port': port, 'origin': origin, 'pin_sha256': pin, 'debug': debug,
            'min_sdk': MIN_SDK, 'target_sdk': TARGET_SDK, 'signer_sha256': facts['signer_sha256']}
    _atomic_write(out_dir / apk_name, data)
    _atomic_write(out_dir / (apk_name + '.json'), (json.dumps(info, indent=2) + '\n').encode())
    _atomic_write(out_dir / COUNTER_NAME, f'{version_code}\n'.encode())
    return info


def _lower_priority() -> None:
    """Sierra and the trading bots share this PC: build at the lowest priority."""
    with contextlib.suppress(OSError, AttributeError):
        os.nice(15)
    ionice = shutil.which('ionice')
    if ionice:
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            subprocess.run([ionice, '-c', '3', '-p', str(os.getpid())], capture_output=True, timeout=5)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Build the AI Desk tablet app (a WebView shell around the tablet page).')
    parser.add_argument('--url', help='the tablet service\'s address, https://HOST:PORT (default: ask the loopback setup endpoint)')
    parser.add_argument('--fingerprint', help='SHA-256 of the service\'s certificate, as the setup page shows it (default: ask the setup endpoint)')
    parser.add_argument('--out', type=Path, default=APP_DIR, help=f'output folder (default {APP_DIR})')
    parser.add_argument('--debug', action='store_true', help='WebView remote debugging on, own signing key, writes ai-desk-tablet-debug.apk')
    parser.add_argument('--keystore-dir', type=Path, default=SIGNING_DIR, help=f'where the private signing key lives (default {SIGNING_DIR})')
    parser.add_argument('--setup-url', default=SETUP_URL, help=argparse.SUPPRESS)
    parser.add_argument('--sdk', help='Android SDK folder (default: ANDROID_HOME, ~/Android/Sdk or the Windows user\'s SDK)')
    parser.add_argument('--jdk', help='JDK folder (default: JAVA_HOME or a JDK found next to the SDK)')
    args = parser.parse_args(argv)
    if bool(args.url) != bool(args.fingerprint):
        parser.error('give --url and --fingerprint together, or neither to ask the tablet service')
    key_file = Path(args.keystore_dir).expanduser() / ('debug.p12' if args.debug else 'release.p12')
    first_key = not key_file.exists()
    try:
        tools = find_toolchain(args.sdk, args.jdk)
        url, fingerprint = (args.url, args.fingerprint) if args.url else fetch_setup(args.setup_url)
        info = build(url, fingerprint, out_dir=args.out, debug=args.debug, keystore_dir=args.keystore_dir, tools=tools)
    except BuildError as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 1
    print(f'built {Path(args.out) / info["file"]}  ({info["size"] / 1024:.0f} KiB, version {info["version_name"]}, code {info["version_code"]}'
          f'{", DEBUG" if info["debug"] else ""})')
    print(f'sha256 {info["sha256"]}')
    print(f'trusts {info["origin"]} with certificate {info["pin_sha256"][:16]}...; signed by {str(info["signer_sha256"])[:16]}...')
    if first_key and key_file.exists():
        print(f'created the private signing key in {args.keystore_dir}: keep it, an update only installs over an app signed with the same key')
    return 0


if __name__ == '__main__':
    _lower_priority()   # only when run as a command: a test that calls main() must not slow down the whole test process
    sys.exit(main())
