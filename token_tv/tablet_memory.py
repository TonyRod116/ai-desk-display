"""A narrow, opt-in memory action for the tablet's computer page.

Only the current Windows user's idle Slack and OneDrive processes may be
trimmed. No process is stopped, no global cache is purged, and no privilege is
elevated. An ambiguous outcome is never retried automatically.
"""
import base64
import json
import math
import os
import subprocess
import threading
import time

from token_tv import tablet_metrics

APP_NAMES = ('Slack', 'OneDrive')
COOLDOWN = 120
MAX_OUTPUT = 32768
WINDOWS_POWERSHELL = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'

# The only mutating Win32 call is EmptyWorkingSet on a validated handle.
# All candidates must belong to the current user, have a trusted app path,
# remain idle during sampling, and not own the foreground window. The request
# never supplies an executable, PID, path, command or script.
WINDOWS_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch { }
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Text;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Security.Principal;

public static class DeskMemoryNative {
    const uint QUERY_LIMITED = 0x1000, SET_QUOTA = 0x0100, TOKEN_QUERY = 0x0008;
    const uint STILL_ACTIVE = 259;
    [StructLayout(LayoutKind.Sequential)] struct FT { public uint low, high; }
    [StructLayout(LayoutKind.Sequential)] struct IO { public ulong ro, wo, oo, rb, wb, ob; }
    [StructLayout(LayoutKind.Sequential)] struct PMC {
        public uint cb, faults;
        public UIntPtr peak, working, qpp, qp, qnp, qn, page, peakPage;
    }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Auto)] class MemoryStatus {
        public uint length = (uint)Marshal.SizeOf(typeof(MemoryStatus)), load;
        public ulong total, available, totalPage, availablePage, totalVirtual, availableVirtual, extended;
    }
    public sealed class Reading { public long Cpu; public ulong Io; public ulong Resident; }
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr h);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool QueryFullProcessImageName(IntPtr h, uint flags, StringBuilder path, ref int size);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessTimes(IntPtr h, out FT created, out FT exited, out FT kernel, out FT user);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetProcessIoCounters(IntPtr h, out IO data);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr h, out uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GlobalMemoryStatusEx([In, Out] MemoryStatus data);
    [DllImport("psapi.dll", SetLastError=true)] static extern bool GetProcessMemoryInfo(IntPtr h, ref PMC data, uint size);
    [DllImport("psapi.dll", SetLastError=true)] static extern bool EmptyWorkingSet(IntPtr h);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool OpenProcessToken(IntPtr h, uint access, out IntPtr token);
    [DllImport("advapi32.dll", SetLastError=true)] static extern bool GetTokenInformation(IntPtr token, int cls, IntPtr buffer, int length, out int needed);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    static ulong Ticks(FT f) { return ((ulong)f.high << 32) | f.low; }
    static bool Under(string file, string root) {
        return !String.IsNullOrEmpty(root) && file.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
    }
    static bool KnownPath(string file, string name) {
        if (!String.Equals(Path.GetFileNameWithoutExtension(file), name, StringComparison.OrdinalIgnoreCase) ||
            !String.Equals(Path.GetExtension(file), ".exe", StringComparison.OrdinalIgnoreCase)) return false;
        string local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
        if (String.Equals(name, "Slack", StringComparison.OrdinalIgnoreCase)) return Under(file, Path.Combine(local, "slack"));
        if (!String.Equals(name, "OneDrive", StringComparison.OrdinalIgnoreCase)) return false;
        return Under(file, Path.Combine(local, "Microsoft", "OneDrive")) ||
               Under(file, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "Microsoft OneDrive")) ||
               Under(file, Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFilesX86), "Microsoft OneDrive"));
    }
    static bool SameUser(IntPtr process, string user) {
        IntPtr token = IntPtr.Zero, buffer = IntPtr.Zero;
        try {
            if (!OpenProcessToken(process, TOKEN_QUERY, out token)) return false;
            int needed; GetTokenInformation(token, 1, IntPtr.Zero, 0, out needed);
            if (needed <= 0 || needed > 65536) return false;
            buffer = Marshal.AllocHGlobal(needed);
            if (!GetTokenInformation(token, 1, buffer, needed, out needed)) return false;
            IntPtr sid = Marshal.ReadIntPtr(buffer);
            return sid != IntPtr.Zero && String.Equals(new SecurityIdentifier(sid).Value, user, StringComparison.Ordinal);
        } catch { return false; }
        finally { if (buffer != IntPtr.Zero) Marshal.FreeHGlobal(buffer); if (token != IntPtr.Zero) CloseHandle(token); }
    }
    static bool Valid(IntPtr process, string name, string user) {
        uint code; if (!GetExitCodeProcess(process, out code) || code != STILL_ACTIVE) return false;
        var path = new StringBuilder(32768); int size = path.Capacity;
        return QueryFullProcessImageName(process, 0, path, ref size) && KnownPath(path.ToString(), name) && SameUser(process, user);
    }
    public static IntPtr Open(int pid, string name, string user) {
        if (pid <= 0 || !(name == "Slack" || name == "OneDrive")) return IntPtr.Zero;
        IntPtr h = OpenProcess(QUERY_LIMITED | SET_QUOTA, false, pid);
        if (h != IntPtr.Zero && !Valid(h, name, user)) { CloseHandle(h); return IntPtr.Zero; }
        return h;
    }
    public static void Close(IntPtr h) { if (h != IntPtr.Zero) CloseHandle(h); }
    public static int Foreground() {
        IntPtr window = GetForegroundWindow(); uint pid;
        return window != IntPtr.Zero && GetWindowThreadProcessId(window, out pid) != 0 ? (int)pid : 0;
    }
    public static Reading Read(IntPtr h) {
        FT c,e,k,u; IO io; PMC m = new PMC(); m.cb = (uint)Marshal.SizeOf(typeof(PMC)); uint code;
        if (!GetExitCodeProcess(h, out code) || code != STILL_ACTIVE || !GetProcessTimes(h, out c, out e, out k, out u) ||
            !GetProcessIoCounters(h, out io) || !GetProcessMemoryInfo(h, ref m, m.cb)) return null;
        return new Reading { Cpu = (long)(Ticks(k) + Ticks(u)), Io = io.rb + io.wb + io.ob, Resident = m.working.ToUInt64() };
    }
    public static bool SameGroup(int foreground, int[] before, int[] after) {
        if (foreground <= 0 || before == null || after == null || before.Length == 0 || before.Length > 24 || before.Length != after.Length) return false;
        for (int i = 0; i < before.Length; i++) {
            if (before[i] <= 0 || before[i] == foreground) return false;
            bool found = false;
            for (int j = 0; j < after.Length; j++) {
                if (j != i && before[i] == before[j]) return false;
                if (before[i] == after[j]) found = true;
            }
            if (!found) return false;
        }
        return true;
    }
    public static bool Idle(Reading first, Reading next) {
        return first != null && next != null && next.Cpu >= first.Cpu && next.Io >= first.Io &&
               next.Cpu - first.Cpu <= 300000 && next.Io - first.Io <= 65536;
    }
    public static bool Trim(IntPtr h, string name, string user) { return Valid(h, name, user) && EmptyWorkingSet(h); }
    public static bool EnoughCommit(ulong limit, ulong remaining) { return limit >= 10 && remaining <= limit && remaining >= limit / 10; }
    public static bool CanTry() { var m = new MemoryStatus(); return GlobalMemoryStatusEx(m) && EnoughCommit(m.totalPage, m.availablePage); }
    public static long Available() { var m = new MemoryStatus(); return GlobalMemoryStatusEx(m) && m.available <= Int64.MaxValue ? (long)m.available : -1; }
}
'@
$handles = New-Object 'System.Collections.Generic.List[System.IntPtr]'
$attempted = $false
try {
    $owner = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    $foreground = [DeskMemoryNative]::Foreground()
    if ($foreground -le 0 -or -not [DeskMemoryNative]::CanTry()) { @{state='unavailable'} | ConvertTo-Json -Compress; exit 0 }
    $before = [DeskMemoryNative]::Available()
    $groups = @{}
    foreach ($name in @('Slack','OneDrive')) {
        $processes = @([System.Diagnostics.Process]::GetProcessesByName($name))
        $list = New-Object 'System.Collections.Generic.List[object]'
        $safe = $processes.Count -le 24
        foreach ($p in $processes) {
            if (-not $safe) { break }
            $handle = [DeskMemoryNative]::Open($p.Id, $name, $owner)
            if ($handle -eq [IntPtr]::Zero) { $safe = $false; break }
            $handles.Add($handle)
            $reading = [DeskMemoryNative]::Read($handle)
            if ($null -eq $reading) { $safe = $false; break }
            $list.Add([pscustomobject]@{id=$p.Id; handle=$handle; reading=$reading})
            if ($p.Id -eq $foreground) { $safe = $false }
        }
        $groups[$name] = @{safe=$safe; items=$list; count=$processes.Count}
    }
    Start-Sleep -Milliseconds 1200
    $done = New-Object 'System.Collections.Generic.List[string]'
    foreach ($name in @('Slack','OneDrive')) {
        $group = $groups[$name]
        if (-not $group.safe -or $group.count -eq 0) { continue }
        $now = @([System.Diagnostics.Process]::GetProcessesByName($name))
        if ($now.Count -ne $group.count) { continue }
        $ids = @($now | ForEach-Object { $_.Id })
        $original = @($group.items | ForEach-Object { $_.id })
        $foreground = [DeskMemoryNative]::Foreground()
        if (-not [DeskMemoryNative]::SameGroup($foreground, [int[]]$original, [int[]]$ids)) { continue }
        $safe = $true; $best = $null
        foreach ($item in $group.items) {
            $next = [DeskMemoryNative]::Read($item.handle)
            if (-not [DeskMemoryNative]::Idle($item.reading, $next)) { $safe = $false; break }
            if ($next.Resident -ge 33554432 -and $next.Resident -le 536870912 -and ($null -eq $best -or $next.Resident -gt $best.resident)) {
                $best = [pscustomobject]@{handle=$item.handle; resident=$next.Resident}
            }
        }
        if (-not $safe -or $null -eq $best) { continue }
        $foreground = [DeskMemoryNative]::Foreground()
        if ($foreground -le 0 -or -not [DeskMemoryNative]::CanTry()) { break }
        try { $activeName = [System.Diagnostics.Process]::GetProcessById($foreground).ProcessName } catch { break }
        if ($activeName -ieq $name) { continue }
        $attempted = $true
        if ([DeskMemoryNative]::Trim($best.handle, $name, $owner)) { $done.Add($name) }
    }
    $after = [DeskMemoryNative]::Available()
    if ($done.Count -eq 0 -and $attempted) {
        @{state='unavailable'} | ConvertTo-Json -Compress
    } else {
        $state = if ($done.Count -gt 0) { 'done' } else { 'nothing' }
        @{state=$state; apps=@($done.ToArray()); before=$(if ($before -ge 0) {$before} else {$null}); after=$(if ($after -ge 0) {$after} else {$null})} | ConvertTo-Json -Compress -Depth 4
    }
} catch {
    @{state=$(if ($attempted) {'unknown'} else {'unavailable'})} | ConvertTo-Json -Compress
} finally {
    foreach ($handle in $handles) { [DeskMemoryNative]::Close($handle) }
}
'''


def _valid_bytes(value):
    return value is None or (type(value) is int and 0 <= value <= 2 ** 53 - 1)


def _clean_result(value):
    if not isinstance(value, dict):
        return {'state': 'unknown'}
    state = value.get('state')
    if state in ('unknown', 'unavailable') and set(value) == {'state'}:
        return {'state': state}
    if state not in ('done', 'nothing') or set(value) != {'state', 'apps', 'before', 'after'}:
        return {'state': 'unknown'}
    apps = value.get('apps')
    if (not isinstance(apps, list) or any(type(app) is not str or app not in APP_NAMES for app in apps)
            or len(apps) != len(set(apps)) or (state == 'done') != bool(apps)
            or not _valid_bytes(value['before']) or not _valid_bytes(value['after'])):
        return {'state': 'unknown'}
    return {'state': state, 'apps': apps, 'before': value['before'], 'after': value['after']}


def _relay(env):
    """Probe only trusted local WSL relays, before starting the one-shot action."""
    if not os.path.isfile(tablet_metrics._WINDOWS_CMD):
        return None
    candidates = tablet_metrics._interop_candidates(None)
    cached = tablet_metrics._interop_override
    if cached in candidates:
        candidates.remove(cached)
        candidates.insert(0, cached)
    for path in candidates:
        try:
            subprocess.run([tablet_metrics._WINDOWS_CMD, '/d', '/c', 'exit', '0'], capture_output=True, timeout=1.5,
                           check=True, env=dict(env, WSL_INTEROP=path))
            return path
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _execute():
    """Execute at most once: a timeout or invalid answer is unknown, not retried."""
    if not os.path.isfile(WINDOWS_POWERSHELL):
        return {'state': 'unavailable'}
    env = {key: os.environ[key] for key in tablet_metrics._SAFE_ENV if key in os.environ}
    relay = _relay(env)
    if relay is None:
        return {'state': 'unavailable'}
    env['WSL_INTEROP'] = relay
    encoded = base64.b64encode(WINDOWS_SCRIPT.encode('utf-16le')).decode('ascii')
    args = [WINDOWS_POWERSHELL, '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded]
    try:
        result = subprocess.run(args, capture_output=True, timeout=25, check=True, env=env)
        if len(result.stdout) > MAX_OUTPUT:
            return {'state': 'unknown'}
        return _clean_result(json.loads(result.stdout.decode('utf-8-sig')))
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError, TypeError):
        return {'state': 'unknown'}


class MemoryRelief:
    """One action at a time and a cooldown, including ambiguous outcomes."""
    def __init__(self, runner=None, clock=time.monotonic, cooldown=COOLDOWN):
        self._runner = runner if runner is not None else _execute
        self._clock, self._cooldown = clock, cooldown
        self._lock, self._last = threading.Lock(), None

    def release(self):
        if not self._lock.acquire(blocking=False):
            return {'state': 'busy'}
        try:
            now = self._clock()
            if self._last is not None and now - self._last < self._cooldown:
                return {'state': 'cooldown', 'seconds': max(1, math.ceil(self._cooldown - (now - self._last)))}
            self._last = now  # set before launch: an ambiguous request must not be repeated
            try:
                return _clean_result(self._runner())
            except Exception:
                return {'state': 'unknown'}
        finally:
            self._lock.release()
