"""A Windows toast when a provider's readings have been missing for half an hour, and one when they are back.

Tony, 2026-11-03: Claude had no data for 7 days 14 h and nothing warned. The toast goes through `powershell.exe` (WSL interop) and
is quiet: silent, default priority, hidden window, so it never steals focus. It says only fixed words (the provider's name and one
of `reader_status.REASONS`), never account data. It is sent by the two reader services, not the monitor: the monitor runs under
`LocalPolicy`, which forbids child processes by design, and that must not be loosened.

WSL calls to Windows are flaky here, so a toast counts as delivered only when powershell.exe ran, exited 0 and printed MARKER.
A lost one is tried again no sooner than every five minutes (then ever less often), and it is never forgotten: it stays owed
until delivered. Everything that can fail is swallowed; a reader's loop never notices. The state is a private file, so a
restart neither repeats a toast nor loses one.

    python -B -m token_tv.alerts test claude     # sends ONE real toast (a test message); prints delivered or not delivered
"""
import base64
import os
import subprocess
import sys
import time
from pathlib import Path
from xml.sax.saxutils import escape

from token_tv.local_usage import atomic_json, read_record
from token_tv.reader_status import short_reason

ALERT_AFTER_SECONDS = 1800    # this long without a usable reading raises the alert
RETRY_SECONDS = 300           # a toast that did not go through waits this long before the next try, doubling...
RETRY_MAX_SECONDS = 3600      # ...up to this
GAP_SECONDS = 900             # not watching for this long: an old outage clock proves nothing about the time since
GIVE_UP_SECONDS = 3600        # a "back" toast still undelivered this long after the recovery is no longer news
TOAST_TIMEOUT = 12            # seconds for powershell.exe; the reader services stop within 15
POWERSHELL = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'   # a service's PATH has no Windows directories
MARKER = 'tokentv-toast-ok'
NAMES = {'claude': 'Claude', 'codex': 'Codex'}
# Windows PowerShell's own app id: toasts from an unregistered id are dropped.
APP_ID = r'{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe'


def message(kind, provider, reason=None):
    """(title, body) in fixed words: the provider's name and `reader_status` words only."""
    name = NAMES[provider]
    if kind == 'missing':
        gap = f'No reading for over {ALERT_AFTER_SECONDS // 60} minutes.'
        return f'{name} readings are missing', gap if short_reason(reason) == 'No reading' else f'{short_reason(reason)}. {gap}'
    if kind == 'back':
        return f'{name} readings are back', 'TokenTV has a current reading again.'
    return 'TokenTV test', 'If you can read this, desk alerts work.'


def toast_script(title, body, tag):
    """The one fixed PowerShell script: a silent, short toast replacing its predecessor with the same tag."""
    fix = lambda text: escape(text).replace("'", "''")
    xml = ('<toast><visual><binding template="ToastGeneric">'
           f'<text>{fix(title)}</text><text>{fix(body)}</text></binding></visual><audio silent="true"/></toast>')
    return '; '.join([
        "$ErrorActionPreference = 'Stop'",
        "[void][Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime]",
        "[void][Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime]",
        "$xml = New-Object Windows.Data.Xml.Dom.XmlDocument",
        f"$xml.LoadXml('{xml}')",
        "$toast = New-Object Windows.UI.Notifications.ToastNotification $xml",
        f"$toast.Tag = '{tag}'; $toast.Group = 'tokentv'",
        f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{APP_ID}').Show($toast)",
        f"Write-Output '{MARKER}'"])


def powershell_command(script):
    exe = POWERSHELL if os.path.exists(POWERSHELL) else 'powershell.exe'
    encoded = base64.b64encode(script.encode('utf-16-le')).decode('ascii')
    return [exe, '-NoProfile', '-NonInteractive', '-NoLogo', '-WindowStyle', 'Hidden', '-EncodedCommand', encoded]


def run_powershell(command, timeout):
    """(exit code, stdout) of the real thing. A reader service has no interop session of its own, so point at PID 1's."""
    env = dict(os.environ)
    if 'WSL_INTEROP' not in env and os.path.exists('/run/WSL/1_interop'):
        env['WSL_INTEROP'] = '/run/WSL/1_interop'
    # Windows writes in its own code page, not UTF-8 (a real toast test failed on this): only the ASCII marker matters here.
    result = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True, encoding='utf-8', errors='replace',
                            timeout=timeout, env=env)
    return result.returncode, result.stdout


def delay(failures):
    return 0 if failures <= 0 else min(RETRY_MAX_SECONDS, RETRY_SECONDS * 2 ** (failures - 1))


class Alerts:
    """One toast per outage after ALERT_AFTER_SECONDS without a usable reading, and one when readings return (only if the first
    was delivered). `runner(command, timeout) -> (exit code, stdout)` is injectable so tests never start powershell."""

    def __init__(self, path, provider, runner=None, clock=time.time):
        if provider not in NAMES:
            raise ValueError('Unknown provider')
        self.path, self.provider, self.run, self.clock = Path(path), provider, runner or run_powershell, clock

    def observe(self, usable, reason=None, now=None):
        """Call after every poll: `usable` is whether it produced a reading, `reason` the `reader_status` id when it did not."""
        try:
            self._observe(bool(usable), reason, int(self.clock() if now is None else now))
        except Exception:
            pass   # an alert must never disturb the reader

    def load(self):
        data = read_record(self.path) or {}
        number = lambda key, default: int(data[key]) if type(data.get(key)) in (int, float) and data[key] >= 0 else default
        return {'seen': number('seen', None), 'down_since': number('down_since', None), 'told': data.get('told') is True,
                'owed': data['owed'] if data.get('owed') in ('missing', 'back') else None, 'owed_at': number('owed_at', 0),
                'tried': number('tried', 0), 'failures': number('failures', 0)}

    def _observe(self, usable, reason, now):
        s = self.load()
        if s['seen'] is None or not 0 <= now - s['seen'] <= GAP_SECONDS:
            s['down_since'] = None   # nobody was watching, so the old clock says nothing
        s['seen'] = now

        def owe(kind):
            s.update(owed=kind, owed_at=now, failures=0)

        if usable:
            if s['down_since'] is not None or s['owed'] == 'missing':
                s['down_since'] = None
                if s['owed'] == 'missing':
                    s['owed'] = None   # never told him it was down: nothing to take back
                if s['told']:
                    owe('back')
        else:
            if s['down_since'] is None:
                s['down_since'] = now
            if s['owed'] == 'back':
                s['owed'] = None   # down again before he heard it was back: for him it is one long outage
            if not s['told'] and s['owed'] is None and now - s['down_since'] >= ALERT_AFTER_SECONDS:
                owe('missing')
        if s['owed'] == 'back' and now - s['owed_at'] > GIVE_UP_SECONDS:
            s.update(owed=None, told=False)
        if s['owed'] and now - s['tried'] >= delay(s['failures']):
            s['tried'] = now
            self.save(s)   # before the attempt: a crash during it still keeps the gap between tries
            if self.send(s['owed'], reason):
                s.update(told=s['owed'] == 'missing', owed=None, failures=0)
            else:
                s['failures'] += 1
        self.save(s)

    def save(self, state):
        atomic_json(self.path, state)

    def send(self, kind, reason=None):
        """True only if the toast really went out. Never raises."""
        try:
            title, body = message(kind, self.provider, reason)
            code, output = self.run(powershell_command(toast_script(title, body, 'tokentv-' + self.provider)), TOAST_TIMEOUT)
            return code == 0 and MARKER in (output or '')
        except Exception:
            return False


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != 'test' or argv[1] not in NAMES:
        print('usage: python -m token_tv.alerts test claude|codex   (sends one real test toast)', file=sys.stderr)
        return 2
    title, body = message('test', argv[1])
    try:
        code, output = run_powershell(powershell_command(toast_script(title, body, 'tokentv-test')), TOAST_TIMEOUT)
    except Exception as error:
        print(f'not delivered ({type(error).__name__})')
        return 1
    delivered = code == 0 and MARKER in (output or '')
    print('delivered' if delivered else f'not delivered (exit code {code})')
    return 0 if delivered else 1


if __name__ == '__main__':
    raise SystemExit(main())
