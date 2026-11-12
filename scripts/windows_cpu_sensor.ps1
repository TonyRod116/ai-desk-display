# Explicitly approved, optional Windows sensor task. Run elevated ONCE to install.
# No network, credentials, drivers, fan controls or changes to WMI permissions.
$ErrorActionPreference = 'Stop'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($ExpectedCpuSensorSid -and $ExpectedCpuSensorSid -ne $identity.User.Value) {
    throw 'Approve installation with the same Windows account that runs the tablet.'
}
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator confirmation is required to install the CPU-only reader.'
}
$directory = 'C:\ProgramData\AI Desk Display CPU Sensor'
$taskName = 'AI Desk Display CPU Sensor'
$scheduler = New-Object -ComObject Schedule.Service
$scheduler.Connect()
$folder = $scheduler.GetFolder('\')
$existing = $null
try { $existing = $folder.GetTask($taskName) } catch { }
if ($existing -or [IO.File]::Exists($directory)) {
    throw 'An existing CPU sensor installation must be reviewed before replacing it.'
}
$machine = Get-CimInstance Win32_ComputerSystem -Property Manufacturer,Model
if ($machine.Manufacturer -ne 'Micro-Star International Co., Ltd.' -or $machine.Model -ne 'Stealth 17Studio A13VH') {
    throw 'This CPU reader is restricted to the locally validated MSI model.'
}

# Protect the directory at creation. Standard users can read the temperature,
# but cannot replace code/data, change its ACL, or modify the elevated task.
$acl = New-Object Security.AccessControl.DirectorySecurity
# Use concrete ReadAndExecute|Synchronize rights: Windows maps generic GRGX to
# this mask on creation, so compare the actual permissions rather than spelling.
$acl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)')
if ([IO.Directory]::Exists($directory) -and ((Get-Item -LiteralPath $directory -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
    throw 'A reparse point cannot be used as the CPU sensor directory.'
}
$created = [IO.Directory]::CreateDirectory($directory, $acl)
$actual = $created.GetAccessControl()
if (($created.Attributes -band [IO.FileAttributes]::ReparsePoint) -or
    $actual.GetOwner([Security.Principal.SecurityIdentifier]).Value -ne 'S-1-5-32-544' -or
    -not $actual.AreAccessRulesProtected -or
    $actual.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access) -ne
        $acl.GetSecurityDescriptorSddlForm([Security.AccessControl.AccessControlSections]::Access)) {
    throw 'The sensor directory is not protected; no elevated task was installed.'
}
if ([IO.Directory]::GetFileSystemEntries($directory).Length -ne 0) {
    throw 'The existing CPU sensor directory is not empty; review it before installing.'
}

# The task executes this fixed inline script. It never executes a file editable
# by a normal user and accepts no parameters, filenames or commands from clients.
$reader = @'
$ErrorActionPreference = 'Stop'
$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')
$ProgressPreference = 'SilentlyContinue'
try { (Get-Process -Id $PID).PriorityClass = 'BelowNormal' } catch { }
$directory = 'C:\ProgramData\AI Desk Display CPU Sensor'
$root = Get-Item -LiteralPath $directory -Force
if ($root.Attributes -band [IO.FileAttributes]::ReparsePoint) { exit 1 }
$temperature = $null
try {
    $machine = Get-CimInstance Win32_ComputerSystem -Property Manufacturer,Model
    if ($machine.Manufacturer -eq 'Micro-Star International Co., Ltd.' -and $machine.Model -eq 'Stealth 17Studio A13VH') {
        $package = ([wmiclass]'root\wmi:Package_32').CreateInstance()
        $package['Bytes'] = [byte[]]::new(32)
        $device = Get-WmiObject -Namespace root\wmi -Class MSI_ACPI | Select-Object -First 1
        $parameters = $device.psbase.GetMethodParameters('Get_Temperature')
        $parameters['Data'] = $package
        [byte[]]$result = $device.psbase.InvokeMethod('Get_Temperature', $parameters, $null)['Data']['Bytes']
        if ($result.Length -ge 3 -and $result[0] -eq 1 -and $result[1] -ge 10 -and $result[1] -le 110) {
            $temperature = [int]$result[1]
        }
    }
} catch { }
$data = @{version=1; source='msi-acpi-cpu'; sampledAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds(); celsius=$temperature} | ConvertTo-Json -Compress
$pending = Join-Path $directory 'reading.pending'
$output = Join-Path $directory 'reading.json'
foreach ($path in @($pending, $output)) {
    if ([IO.File]::Exists($path) -and ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) { exit 1 }
}
if ([IO.File]::Exists($pending)) { [IO.File]::Delete($pending) }
$fileAcl = New-Object Security.AccessControl.FileSecurity
$fileAcl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)')
$stream = New-Object IO.FileStream($pending, [IO.FileMode]::CreateNew, [Security.AccessControl.FileSystemRights]::Write,
    [IO.FileShare]::None, 4096, [IO.FileOptions]::None, $fileAcl)
try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($data)
    $stream.Write($bytes, 0, $bytes.Length)
    $stream.Flush()
} finally { $stream.Dispose() }
# Windows PowerShell/.NET Framework rejects the null backup path of File.Replace.
# MoveFileEx atomically replaces the old export and retains the protected source ACL.
Add-Type -TypeDefinition 'using System.Runtime.InteropServices; public static class DeskCpuExport { [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] public static extern bool MoveFileEx(string source, string destination, uint flags); }'
if (-not [DeskCpuExport]::MoveFileEx($pending, $output, 9)) { throw 'CPU sensor export could not be replaced.' }
'@

$definition = $scheduler.NewTask(0)
$definition.RegistrationInfo.Description = 'Reads only the MSI CPU temperature for the local tablet. No account access or hardware configuration.'
$definition.Principal.UserId = $identity.User.Value
$definition.Principal.LogonType = 3                 # interactive token; no stored password
$definition.Principal.RunLevel = 1                  # this task only, never the tablet
$definition.Settings.ExecutionTimeLimit = 'PT15S'
$definition.Settings.Priority = 7                   # below normal
$definition.Settings.MultipleInstances = 2          # ignore a new run if still running
$definition.Settings.DisallowStartIfOnBatteries = $false
$definition.Settings.StopIfGoingOnBatteries = $false
$definition.Settings.StartWhenAvailable = $true
$trigger = $definition.Triggers.Create(1)            # time trigger, once per minute
$trigger.StartBoundary = (Get-Date).AddMinutes(1).ToString('s')
$trigger.Repetition.Interval = 'PT1M'
$logon = $definition.Triggers.Create(9)
$logon.UserId = $identity.User.Value
$action = $definition.Actions.Create(0)
$action.Path = Join-Path ([Environment]::GetFolderPath('Windows')) 'System32\WindowsPowerShell\v1.0\powershell.exe'
$action.Arguments = '-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand ' + [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($reader))
$taskAcl = 'O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GR;;;BU)'
try {
    # TASK_CREATE | TASK_DONT_ADD_PRINCIPAL_ACE: protection applies atomically.
    $registered = $folder.RegisterTaskDefinition($taskName, $definition, 18, $identity.User.Value, $null, 3, $taskAcl)
    $registered.Run($null) | Out-Null
    Write-Output 'CPU-only sensor task installed.'
} catch {
    # Keep the protected directory: never recursively delete an uncertain path.
    throw 'CPU task installation failed. Review the protected directory before retrying.'
}
