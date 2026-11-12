"""Read a small, non-identifying set of local PC metrics for the tablet view.

The Windows host owns the drives and CPU; WSL's virtual disk is not a substitute.
Failed or unavailable sensors stay unknown. Call the collector from a background
worker, not from an HTTP request or the display's time-sensitive board loop.

collect() returns, besides the original cpu_percent, cpu_temp_c, memory, disks and gpus:
  processes  {'cpu': [{'name', 'percent', 'mem_mb'}] (top 6, percent of the WHOLE machine, averaged
              since the previous call) or None while unknown, 'memory': [{'name', 'mem_mb'}] (top 6
              by working set), 'gpu': [{'name', 'percent'}] (top 4) or None} or None. Names only,
              merged by name: no process id, command line, path or user ever leaves this module.
  network    {'down_bps', 'up_bps'} in BITS per second over physical adapters that are up, from the
              byte counters since the previous call; None values on the first call; None if unread.
  battery    {'percent', 'charging', 'minutes', 'plugged'} or None (no battery).
  uptime_s   whole seconds since Windows booted (the number Task Manager shows), or None.
One PowerShell process per call reads all of it; an MSI-only temperature rides on the same process.
"""
import base64
import csv
import io
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from token_tv.tablet_history import MetricsHistory  # noqa: F401  (the tablet service imports it from here)
from token_tv.tablet_rates import RateTracker


# ONE PowerShell process per call. It prints a single line of JSON and flushes it, and only then reads
# the model-specific temperature (a line 'T=<celsius>'), so a sensor that hangs cannot hide what was
# already printed. Counters (CPU and GPU time, bytes) are cumulative: tablet_rates turns two calls into
# rates. Programs are read as name, id, CPU time and working set: never a path, command line or user.
_WINDOWS_QUERY = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch { }
$frequency = [System.Diagnostics.Stopwatch]::Frequency
$processes = $null
try {
    $rows = New-Object System.Collections.Generic.List[object]
    $first = [System.Diagnostics.Stopwatch]::GetTimestamp()
    foreach ($item in [System.Diagnostics.Process]::GetProcesses()) {
        try {
            if ($item.Id -eq $PID) { continue }
            $ticks = $null
            try { $ticks = $item.TotalProcessorTime.Ticks } catch { }
            $rows.Add(@($item.ProcessName, $item.Id, $ticks, $item.WorkingSet64))
        } catch { }
    }
    $last = [System.Diagnostics.Stopwatch]::GetTimestamp()
    $processes = @{t = [int64](($first + $last) / 2); f = $frequency; n = [Environment]::ProcessorCount; p = $rows}
} catch { }
$network = $null
try {
    $adapters = New-Object System.Collections.Generic.List[object]
    $first = [System.Diagnostics.Stopwatch]::GetTimestamp()
    foreach ($card in [System.Net.NetworkInformation.NetworkInterface]::GetAllNetworkInterfaces()) {
        try {
            if ($card.OperationalStatus -ne 'Up' -or $card.NetworkInterfaceType -eq 'Loopback' -or
                $card.NetworkInterfaceType -eq 'Tunnel') { continue }
            # Physical means a PCI or USB device: WSL and Hyper-V switches, VPNs and Bluetooth sit on other buses.
            $key = [Microsoft.Win32.Registry]::LocalMachine.OpenSubKey(
                'SYSTEM\CurrentControlSet\Control\Network\{4D36E972-E325-11CE-BFC1-08002BE10318}\' + $card.Id + '\Connection')
            if ($null -eq $key) { continue }
            $bus = ([string]$key.GetValue('PnpInstanceID')).Split('\')[0]
            $key.Close()
            if ($bus -ne 'PCI' -and $bus -ne 'USB') { continue }
            $bytes = $card.GetIPStatistics()
            $adapters.Add(@($card.Id, $bytes.BytesReceived, $bytes.BytesSent))
        } catch { }
    }
    $last = [System.Diagnostics.Stopwatch]::GetTimestamp()
    $network = @{t = [int64](($first + $last) / 2); f = $frequency; a = $adapters}
} catch { }
$disks = $null
try {
    $disks = @(Get-CimInstance Win32_LogicalDisk -Filter 'DriveType = 3' -Property DeviceID,VolumeName,Size,FreeSpace |
        Select-Object DeviceID,VolumeName,Size,FreeSpace)
} catch { }
$os = $null
$uptime = $null
try {
    $computer = Get-CimInstance Win32_OperatingSystem -Property TotalVisibleMemorySize,FreePhysicalMemory,LastBootUpTime
    $os = $computer | Select-Object TotalVisibleMemorySize,FreePhysicalMemory
    $uptime = [int64]([DateTime]::UtcNow - $computer.LastBootUpTime.ToUniversalTime()).TotalSeconds
} catch { }
$battery = $null
try {
    $cell = Get-CimInstance Win32_Battery -Property BatteryStatus,EstimatedChargeRemaining,EstimatedRunTime |
        Select-Object -First 1
    if ($cell) { $battery = @{s = $cell.BatteryStatus; p = $cell.EstimatedChargeRemaining; m = $cell.EstimatedRunTime} }
} catch { }
$gpu = $null
try {
    $engines = @(Get-CimInstance -Query ("SELECT Name,UtilizationPercentage,Timestamp_Sys100NS " +
        "FROM Win32_PerfRawData_GPUPerformanceCounters_GPUEngine WHERE Name LIKE '%engtype_3D' " +
        "OR Name LIKE '%engtype_Compute%' OR Name LIKE '%engtype_Cuda%'"))
    if ($engines.Count -gt 0) {
        $rows = New-Object System.Collections.Generic.List[object]
        foreach ($engine in $engines) { $rows.Add(@($engine.Name, $engine.UtilizationPercentage)) }
        $gpu = @{t = $engines[0].Timestamp_Sys100NS; p = $rows}
    }
} catch { }
$cpu = $null
try {
    $cpu = @(Get-CimInstance Win32_Processor -Property LoadPercentage,NumberOfLogicalProcessors |
        Select-Object LoadPercentage,NumberOfLogicalProcessors)
} catch { }
$json = @{disks=$disks; os=$os; cpu=$cpu; up=$uptime; bat=$battery; net=$network; pr=$processes; gp=$gpu} |
    ConvertTo-Json -Compress -Depth 5
[Console]::Out.WriteLine($json)
[Console]::Out.Flush()
"""
# The MSI firmware reports CPU and GPU temperatures in the first two data bytes
# of Get_Temperature(0). Restrict this to the exact machine validated locally.
_MSI_CPU_TEMP_QUERY = r"""
try {
    $machine = Get-CimInstance Win32_ComputerSystem -Property Manufacturer,Model
    if ($machine.Manufacturer -eq 'Micro-Star International Co., Ltd.' -and
        $machine.Model -eq 'Stealth 17Studio A13VH') {
        $package = ([wmiclass]'root\wmi:Package_32').CreateInstance()
        $package['Bytes'] = [byte[]]::new(32)
        $device = Get-WmiObject -Namespace root\wmi -Class MSI_ACPI | Select-Object -First 1
        $parameters = $device.psbase.GetMethodParameters('Get_Temperature')
        $parameters['Data'] = $package
        [byte[]]$result = $device.psbase.InvokeMethod('Get_Temperature', $parameters, $null)['Data']['Bytes']
        if ($result.Length -ge 3 -and $result[0] -eq 1 -and $result[1] -ge 10 -and $result[1] -le 110) {
            [Console]::Out.WriteLine('T=' + [int]$result[1])
        }
    }
} catch { }
"""
# PowerShell exits with 1 when the last statement swallowed an error (a sensor that is not there), which
# would discard everything already printed: end explicitly with success.
_QUERY = _WINDOWS_QUERY + _MSI_CPU_TEMP_QUERY + 'exit 0\n'
_SAFE_ENV = ('PATH', 'HOME', 'USER', 'LANG', 'LC_ALL', 'WSL_INTEROP',
             'WSL_DISTRO_NAME', 'SYSTEMROOT', 'SystemRoot', 'WINDIR', 'TMP', 'TEMP')
GOOGLE_QUOTA_FILE = Path.home() / '.local/share/ai-desk-display/tablet/google-drive-quota.json'


def _number(value, minimum=0, maximum=None):
    if type(value) not in (int, float) or not math.isfinite(value) or value < minimum:
        return None
    return value if maximum is None or value <= maximum else None


def _space(total, free, multiplier=1):
    total, free = _number(total, 1), _number(free)
    if total is None or free is None or free > total:
        return None
    return {'total': int(total * multiplier), 'free': int(free * multiplier)}


def normalize_windows(data):
    data = data if isinstance(data, dict) else {}
    cpus = data.get('cpu') if isinstance(data.get('cpu'), list) else []
    weighted = []
    for cpu in cpus:
        if not isinstance(cpu, dict):
            continue
        value = _number(cpu.get('LoadPercentage'), maximum=100)
        weight = _number(cpu.get('NumberOfLogicalProcessors'), 1, 1024) or 1
        if value is not None:
            weighted.append((value, weight))
    percent = (sum(value * weight for value, weight in weighted) /
               sum(weight for _, weight in weighted)) if weighted else None
    os_info = data.get('os') if isinstance(data.get('os'), dict) else {}
    memory = _space(os_info.get('TotalVisibleMemorySize'), os_info.get('FreePhysicalMemory'), 1024)
    disks = []
    for disk in data.get('disks') if isinstance(data.get('disks'), list) else []:
        if not isinstance(disk, dict):
            continue
        name = disk.get('DeviceID')
        space = _space(disk.get('Size'), disk.get('FreeSpace'))
        label = disk.get('VolumeName')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z]:', name):
            continue
        if isinstance(label, str) and label.strip().casefold() == 'google drive':
            # Drive for desktop reports its local cache volume, not the cloud
            # account's quota. Do not turn that into a fictitious cloud value.
            disks.append({'name': name.upper(), 'kind': 'google_drive', 'total': None, 'free': None})
        elif space:
            disks.append({'name': name.upper(), **space})
    disks.sort(key=lambda disk: disk['name'])
    # The optional model-specific temperature arrives as its own line of the same script output.
    return {'cpu_percent': percent, 'cpu_temp_c': None, 'memory': memory, 'disks': disks}


def apply_manual_google_quota(system, reading, now=None):
    """Attach a dated, user-confirmed cloud figure only to the named Drive."""
    if not isinstance(reading, dict):
        return
    drive = reading.get('drive')
    total, used = _number(reading.get('total'), 1), _number(reading.get('used'))
    recorded = _number(reading.get('recorded_at'), 1)
    now = time.time() if now is None else now
    if (not isinstance(drive, str) or not re.fullmatch(r'[A-Za-z]:', drive) or
            total is None or used is None or used > total or recorded is None or recorded > now + 300):
        return
    for disk in system.get('disks', []):
        if disk.get('kind') == 'google_drive' and disk.get('name') == drive.upper():
            disk.update(total=int(total), free=int(total - used), quota_source='manual', quota_at=int(recorded))


def _read_manual_google_quota():
    try:
        with GOOGLE_QUOTA_FILE.open('r', encoding='utf-8') as source:
            return json.loads(source.read(4097))
    except (OSError, ValueError, UnicodeError):
        return None


def _csv_number(value, maximum=None):
    try:
        number = float(value.strip())
    except (ValueError, AttributeError):
        return None
    number = _number(number, maximum=maximum)
    return int(number) if number is not None and number.is_integer() else number


def normalize_cpu_temperature(text):
    if not isinstance(text, str):
        return None
    try:
        value = _number(float(text.strip()), 10, 110)
    except ValueError:
        return None
    return int(value) if value is not None and value.is_integer() else value


def normalize_nvidia(text):
    gpus = []
    try:
        rows = csv.reader(io.StringIO(text))
        for row in rows:
            if len(row) != 5 or not row[0].strip():
                continue
            name = ''.join(c for c in row[0].strip() if c.isprintable())[:100]
            temp, percent = _csv_number(row[1], 150), _csv_number(row[2], 100)
            used, total = _csv_number(row[3]), _csv_number(row[4])
            if total is None or total <= 0 or used is None or used > total:
                used, total = None, None
            gpus.append({'name': name, 'temp_c': temp, 'percent': percent,
                         'memory_used_mb': used, 'memory_total_mb': total})
    except (csv.Error, TypeError):
        return []
    return gpus


# Win32_Battery.BatteryStatus: 1 discharging, 2 on AC (not necessarily charging), 3 full, 4 low,
# 5 critical, 6-9 charging (also high, low, critical), 11 partly charged, 10 and the rest unknown.
_CHARGING = frozenset((6, 7, 8, 9))
_NOT_CHARGING = frozenset((1, 3, 4, 5))
_DISCHARGING = frozenset((1, 4, 5))
_ON_AC = frozenset((2, 3, 6, 7, 8, 9, 11))


def normalize_battery(data):
    """{'percent', 'charging', 'minutes', 'plugged'} from the script's battery block; None without one.

    `minutes` is Windows' estimate of the time left and exists only on the battery: on AC Windows
    reports the sentinel 71582788, which is out of range here and so unknown. Status 2 says the PC
    has AC but not whether it is charging, so `charging` stays None for it.
    """
    if not isinstance(data, dict):
        return None
    status = data.get('s') if type(data.get('s')) is int else None
    percent = _number(data.get('p'), 0, 100)
    if status is None and percent is None:
        return None
    minutes = None if status in _ON_AC else _number(data.get('m'), 1, 7 * 24 * 60)
    return {'percent': None if percent is None else int(percent),
            'charging': True if status in _CHARGING else (False if status in _NOT_CHARGING else None),
            'minutes': None if minutes is None else int(minutes),
            'plugged': True if status in _ON_AC else (False if status in _DISCHARGING else None)}


def normalize_uptime(value):
    seconds = _number(value, 0, 10 * 365 * 86400)
    return None if seconds is None else int(seconds)


def _printed(raw):
    """What a program printed before it stopped (bytes or nothing), decoded leniently; None if nothing."""
    return raw.decode('utf-8-sig', 'replace') if isinstance(raw, bytes) and raw else None


# A WSL session's inherited interop socket can outlive its Windows relay.
# Cache a proven alternate only for this collector; never change global settings.
_interop_override = None
_WINDOWS_CMD = '/mnt/c/Windows/System32/cmd.exe'


def _interop_candidates(current):
    """Only root-owned sockets in the root-owned WSL runtime directory."""
    root = Path('/run/WSL')
    try:
        st = root.lstat()
        if not stat.S_ISDIR(st.st_mode) or st.st_uid != 0 or st.st_mode & 0o022:
            return []
        candidates = []
        for path in root.iterdir():
            if not re.fullmatch(r'[0-9]+_interop', path.name) or str(path) == current:
                continue
            try:
                info = path.lstat()
            except OSError:     # a WSL session may close while we scan
                continue
            if stat.S_ISSOCK(info.st_mode) and info.st_uid == 0:
                candidates.append(path)
        return [str(path) for path in sorted(candidates, key=lambda p: int(p.name.split('_', 1)[0]))[:8]]
    except OSError:
        return []


def _working_interop(env):
    """Find a responsive relay with a harmless, bounded Windows command."""
    if not os.path.isfile(_WINDOWS_CMD):
        return None
    for candidate in _interop_candidates(env.get('WSL_INTEROP')):
        probe_env = dict(env, WSL_INTEROP=candidate)
        try:
            # /d disables cmd.exe AutoRun; the probe runs no user commands.
            subprocess.run([_WINDOWS_CMD, '/d', '/c', 'exit', '0'], capture_output=True,
                           timeout=1.5, check=True, env=probe_env)
            return candidate
        except (OSError, subprocess.SubprocessError):
            continue
    return None


def _run(args, timeout, partial=False):
    """Run a sensor, retaining partial readings and recovering a dead WSL relay once."""
    global _interop_override
    env = {key: os.environ[key] for key in _SAFE_ENV if key in os.environ}
    if _interop_override:
        env['WSL_INTEROP'] = _interop_override

    def invoke(selected_env):
        try:
            result = subprocess.run(args, capture_output=True, timeout=timeout, check=True, env=selected_env)
            return result.stdout.decode('utf-8-sig'), False
        except subprocess.TimeoutExpired as exc:
            output = _printed(exc.stdout) if partial else None
            return output, output is None
        except subprocess.CalledProcessError as exc:
            output = _printed(exc.stdout) if partial else None
            error = exc.stderr.lower() if isinstance(exc.stderr, bytes) else b''
            # WSL sometimes reports the dead relay immediately instead of
            # timing out; a normal sensor/driver error must not trigger a scan.
            broken_relay = not output and b'wsl (' in error and (b'vsock' in error or b'interop' in error)
            return output, broken_relay
        except (OSError, subprocess.SubprocessError, UnicodeError):
            return None, False

    output, timed_out = invoke(env)
    if not timed_out or not args or not args[0].lower().endswith('.exe'):
        return output
    alternate = _working_interop(env)
    if not alternate:
        return None
    _interop_override = alternate
    env['WSL_INTEROP'] = alternate
    return invoke(env)[0]


def _split_output(output):
    """The script prints one JSON line and, on the MSI laptop only, 'T=<celsius>': (data, temperature)."""
    lines = [line.strip() for line in output.splitlines()] if output is not None else []
    first = next((line for line in lines if line.startswith('{')), None)
    try:
        data = json.loads(first) if first is not None else None
    except (ValueError, TypeError):
        data = None
    temperature = next((line[2:] for line in lines if line.startswith('T=')), None)
    return data, temperature


_rates = RateTracker()


def reset_state():
    """Forget the previous readings; the next call has no rates. For tests and after a long pause."""
    global _interop_override
    _rates.reset()
    _interop_override = None


def collect():
    command = base64.b64encode(_QUERY.encode('utf-16le')).decode('ascii')
    # User services often have a minimal PATH without Windows executables.
    windows_powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
    powershell = windows_powershell if os.path.isfile(windows_powershell) else 'powershell.exe'
    windows = _run([powershell, '-NoProfile', '-NonInteractive', '-EncodedCommand', command], 20, partial=True)
    data, temperature = _split_output(windows)
    system = normalize_windows(data)
    if any(disk.get('kind') == 'google_drive' for disk in system['disks']):
        apply_manual_google_quota(system, _read_manual_google_quota())
    extra = data if isinstance(data, dict) else {}
    processes, network = _rates.update(extra)
    system.update(processes=processes, network=network, battery=normalize_battery(extra.get('bat')),
                  uptime_s=normalize_uptime(extra.get('up')))
    # WSL's NVML shim can crash even while the Windows driver is healthy.
    # Prefer the Windows executable on this machine; keep native Linux working.
    windows_smi = '/mnt/c/Windows/System32/nvidia-smi.exe'
    smi = windows_smi if os.path.isfile(windows_smi) else 'nvidia-smi'
    output = _run([smi, '--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total',
                   '--format=csv,noheader,nounits'], 8)
    system['gpus'] = normalize_nvidia(output) if output is not None else []
    # The sensor rides on the same process; a missing line leaves the temperature unknown.
    system['cpu_temp_c'] = normalize_cpu_temperature(temperature)
    return system
