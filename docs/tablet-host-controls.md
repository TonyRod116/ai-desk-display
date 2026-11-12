# Optional computer controls

The tablet's computer page reads CPU/GPU, memory and fixed disks through the local monitor. Availability depends on the host OS and sensors; the reference collector is Windows through WSL, with NVIDIA GPU readings. These controls do not make native Windows, macOS or every motherboard automatically supported.

## Touch to free memory

The Memory card offers a manually triggered Windows working-set trim. It targets only the current user's **Slack and OneDrive**, when they are in the background and sampled as idle. It validates the owner and expected executable location, requires CPU/I/O checks for the whole app group, trims at most one eligible process per app and waits two minutes between attempts. The fictional demo does not touch any host process.

It never closes applications, clears global caches, elevates itself or targets browsers, editors, WSL or other processes. If the checks fail, it skips the action. A timeout is an unknown outcome, never an automatic retry. The action requires tablet sign-in, the exact request body and same-origin checks; it is disabled in the UI while PC readings are unavailable.

Available RAM before and after is observed, not a promise of savings caused entirely by the trim. The gain can be small or temporary, and those apps may briefly slow when they need their pages again. Windows already counts reusable standby memory as available. See [Microsoft's working-set documentation](https://learn.microsoft.com/en-us/windows/win32/memory/working-set).

## CPU temperature on the validated MSI model

The ordinary Windows token can be denied access to `MSI_ACPI`. An optional, separately installed helper is provided in `scripts/windows_cpu_sensor.ps1`, restricted to the validated **MSI Stealth 17Studio A13VH**. Do not generalize firmware reads to untested machines or install the helper automatically.

After reviewing the script, an administrator can run it from an elevated Windows PowerShell session under their approved local script policy. It requires that Windows approval; it does not elevate the tablet or grant broad WMI access. It registers one protected task, using that signed-in user's interactive token with administrator privileges, no stored password, a one-minute interval and a 15-second time limit. Code runs inline from the protected task definition and loads only system modules, never a normal-user script file.

The output is temperature-only JSON at `C:\ProgramData\AI Desk Display CPU Sensor\reading.json`. Administrators/System own and can write the task and output directory; ordinary local users can read the temperature. The helper makes no network requests, reads no accounts and changes no fans or drivers. It **does** run with Windows administrator privileges: the fixed protected code limits its work, not a Windows permission granting only temperature access.

The unprivileged collector consumes samples up to 90 seconds old and stops making its own MSI query while this helper is installed. Missing, invalid or stale samples stay unknown. Other monitoring software may still use the same firmware interface; [the kernel documentation](https://docs.kernel.org/wmi/devices/msi-wmi-platform.html) notes an MSI concurrency issue. Keep hardware-specific limitations in mind. No independent calibration of this temperature is claimed.

To remove it, an administrator can remove only the task named **AI Desk Display CPU Sensor** and its exact protected directory. Removing the installation restores the direct-reader path. Preserve your other tasks and files.
