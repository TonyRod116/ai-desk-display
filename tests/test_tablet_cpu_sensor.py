import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch

from token_tv import tablet_cpu_sensor as sensor, tablet_metrics


class CpuSensorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / 'sensor'
        self.override = patch.object(sensor, 'DIRECTORY', self.directory)
        self.override.start()
        self.addCleanup(self.override.stop)

    def save(self, **changes):
        self.directory.mkdir(exist_ok=True)
        data = dict(version=1, source='msi-acpi-cpu', sampledAt=1000, celsius=67)
        data.update(changes)
        (self.directory / 'reading.json').write_text(json.dumps(data))

    def test_only_fresh_validated_cpu_readings_are_accepted(self):
        self.assertFalse(sensor.installed())
        self.assertIsNone(sensor.read(now=1000))
        self.save()
        self.assertTrue(sensor.installed())
        self.assertEqual(sensor.read(now=1089), 67)
        for changes in ({'sampledAt': 900}, {'sampledAt': 1100}, {'sampledAt': float('nan')},
                        {'sampledAt': True}, {'celsius': 111}, {'celsius': 0}, {'celsius': True},
                        {'celsius': None}, {'version': True}, {'source': 'gpu'}, {'unexpected': 1}):
            with self.subTest(changes=changes):
                self.save(**changes)
                self.assertIsNone(sensor.read(now=1000))

    def test_partial_oversized_and_symlink_exports_remain_unknown(self):
        self.save()
        export = self.directory / 'reading.json'
        for raw in ('{', '[]', 'x' * 513):
            export.write_text(raw)
            self.assertIsNone(sensor.read(now=1000))
        export.unlink()
        outside = Path(self.tmp.name) / 'other.json'
        outside.write_text('{}')
        export.symlink_to(outside)
        self.assertIsNone(sensor.read(now=1000))
        export.unlink()
        os.mkfifo(export)
        self.assertIsNone(sensor.read(now=1000))

    def test_installed_export_never_causes_a_second_firmware_query_or_stale_fallback(self):
        self.directory.mkdir()
        windows = '{"cpu": [], "os": {"TotalVisibleMemorySize":8000,"FreePhysicalMemory":2000}, "disks": []}\nT=80\n'
        with patch.object(tablet_metrics, '_run', side_effect=[windows, None]) as run:
            result = tablet_metrics.collect()
        decoded = base64.b64decode(run.call_args_list[0].args[0][-1]).decode('utf-16le')
        self.assertNotIn('Get_Temperature', decoded)
        self.assertIsNone(result['cpu_temp_c'])
        self.assertIsNotNone(result['memory'])

    def test_valid_export_reaches_existing_metrics_contract(self):
        self.save(sampledAt=time.time())
        with patch.object(tablet_metrics, '_run', side_effect=['{"cpu":[],"os":null,"disks":[]}', None]):
            self.assertEqual(tablet_metrics.collect()['cpu_temp_c'], 67)

    @unittest.skipUnless(shutil.which('pwsh'), 'PowerShell parser is optional')
    def test_installer_is_valid_powershell_without_executing_it(self):
        path = Path(__file__).resolve().parents[1] / 'scripts/windows_cpu_sensor.ps1'
        # Parse the installer AND its embedded reader; invoke neither.
        script = r'''
$tokens=$null; $errors=$null
$ast=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
if ($errors.Count) { exit 1 }
$value=$ast.Find({param($node) $node -is [Management.Automation.Language.StringConstantExpressionAst] -and $node.Value.StartsWith('$ErrorActionPreference')}, $true).Value
if (-not $value) { exit 2 }
$null=[Management.Automation.Language.Parser]::ParseInput($value,[ref]$tokens,[ref]$errors)
if ($errors.Count) { exit 3 }
'''
        parser = Path(self.tmp.name) / 'parse.ps1'
        parser.write_text(script)
        result = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(parser), str(path)], capture_output=True, timeout=12)
        self.assertEqual(result.returncode, 0, result.stderr.decode(errors='replace'))

    def test_elevated_task_has_fixed_read_only_payload_and_protected_registration(self):
        text = (Path(__file__).resolve().parents[1] / 'scripts/windows_cpu_sensor.ps1').read_text()
        reader = text.split("$reader = @'\n", 1)[1].split("\n'@", 1)[0]
        self.assertIn("GetMethodParameters('Get_Temperature')", reader)
        self.assertIn("InvokeMethod('Get_Temperature'", reader)
        for forbidden in ('Set_Temperature', 'Set_EC', 'Set_Fan', 'Invoke-WebRequest', 'Download',
                          'Invoke-Expression', 'Stop-Process', 'Start-Process', 'ExecutionPolicy', 'WSL', 'token-tv'):
            self.assertNotIn(forbidden, reader)
        self.assertIn('RegisterTaskDefinition($taskName, $definition, 18,', text)
        self.assertIn("ExecutionTimeLimit = 'PT15S'", text)
        self.assertIn("Repetition.Interval = 'PT1M'", text)
        self.assertIn('MultipleInstances = 2', text)
        self.assertIn('0x1200a9;;;BU', text)  # Windows expands generic rights on creation
        self.assertIn('GetFileSystemEntries($directory).Length -ne 0', text)
        self.assertIn('MoveFileEx($pending, $output, 9)', reader)
        self.assertIn('-WindowStyle Hidden', text)
        self.assertIn("$env:PSModulePath = [IO.Path]::Combine($PSHOME, 'Modules')", reader)
        self.assertNotIn('SetSecurityDescriptor(', text)  # no unprotected registration followed by ACL repair


if __name__ == '__main__':
    unittest.main()
