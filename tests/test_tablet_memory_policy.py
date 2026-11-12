"""Exercise the pure Windows safety policy without accessing real processes."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from token_tv.tablet_memory import WINDOWS_SCRIPT


class NativePolicyTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell Core is optional for offline policy checks')
    def test_foreground_changed_and_busy_processes_are_rejected(self):
        source=WINDOWS_SCRIPT.split("Add-Type -TypeDefinition @'\n",1)[1].split("\n'@",1)[0]
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'policy.cs').write_text(source)
            test=r'''
Add-Type -Path (Join-Path $PSScriptRoot 'policy.cs') -ErrorAction Stop
if (-not [DeskMemoryNative]::SameGroup(3, [int[]](1,2), [int[]](2,1))) { exit 1 }
if ([DeskMemoryNative]::SameGroup(1, [int[]](1,2), [int[]](1,2))) { exit 2 }
if ([DeskMemoryNative]::SameGroup(0, [int[]](1,2), [int[]](1,2))) { exit 3 }
if ([DeskMemoryNative]::SameGroup(3, [int[]](1,2), [int[]](1,4))) { exit 4 }
if ([DeskMemoryNative]::SameGroup(3, [int[]](1,1), [int[]](1,1))) { exit 5 }
$a=[DeskMemoryNative+Reading]::new();$b=[DeskMemoryNative+Reading]::new()
$b.Cpu=300000;$b.Io=65536;if(-not [DeskMemoryNative]::Idle($a,$b)){exit 6}
$b.Cpu=300001;if([DeskMemoryNative]::Idle($a,$b)){exit 7}
$b.Cpu=0;$b.Io=65537;if([DeskMemoryNative]::Idle($a,$b)){exit 8}
if([DeskMemoryNative]::Idle($a,$null)){exit 9}
if([DeskMemoryNative]::EnoughCommit(100,9)){exit 10}
if(-not [DeskMemoryNative]::EnoughCommit(100,10)){exit 11}
if([DeskMemoryNative]::EnoughCommit(0,0)){exit 12}
if([DeskMemoryNative]::EnoughCommit(1,0)){exit 13}
'''
            (root/'policy.ps1').write_text(test)
            env={key:os.environ[key] for key in ('PATH','HOME','LANG','LC_ALL','TMPDIR') if key in os.environ}
            result=subprocess.run([shutil.which('pwsh'),'-NoLogo','-NoProfile','-NonInteractive','-File',str(root/'policy.ps1')],
                                  capture_output=True,timeout=20,env=env)
            self.assertEqual(result.returncode,0,'offline safety policy rejected an expected case')


if __name__ == '__main__':unittest.main()
