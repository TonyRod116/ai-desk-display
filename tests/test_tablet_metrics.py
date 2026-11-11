import subprocess
import unittest
from unittest.mock import patch

from token_tv import tablet_metrics


class TabletMetricsTests(unittest.TestCase):
    def test_windows_metrics_keep_each_disk_and_real_zero(self):
        data = {
            'cpu': [{'LoadPercentage': 40, 'NumberOfLogicalProcessors': 8}],
            'os': {'TotalVisibleMemorySize': 8000, 'FreePhysicalMemory': 2000},
            'disks': [
                {'DeviceID': 'C:', 'Size': 1000, 'FreeSpace': 250},
                {'DeviceID': 'D:', 'Size': 2000, 'FreeSpace': 0},
                {'DeviceID': 'E:', 'Size': None, 'FreeSpace': None},
            ],
        }
        result = tablet_metrics.normalize_windows(data)
        self.assertEqual(result['cpu_percent'], 40)
        self.assertIsNone(result['cpu_temp_c'])
        self.assertEqual(result['memory'], {'total': 8192000, 'free': 2048000})
        self.assertEqual(result['disks'], [
            {'name': 'C:', 'total': 1000, 'free': 250},
            {'name': 'D:', 'total': 2000, 'free': 0},
        ])

    def test_validated_cpu_temperature_is_shown_but_invalid_values_are_unknown(self):
        self.assertEqual(tablet_metrics.normalize_cpu_temperature('73'), 73)
        for value in (None, '-5', '0', '111', 'NaN', 'n/a', True):
            with self.subTest(value=value):
                self.assertIsNone(tablet_metrics.normalize_cpu_temperature(value))

    def test_cpu_sensor_failure_does_not_hide_memory_or_disks(self):
        windows = ('{"cpu": [], "os": {"TotalVisibleMemorySize": 8000, "FreePhysicalMemory": 2000}, '
                   '"disks": [{"DeviceID": "C:", "Size": 1000, "FreeSpace": 100}]}')
        with patch('token_tv.tablet_metrics._run', side_effect=[windows, None, None]):
            result = tablet_metrics.collect()
        self.assertIsNotNone(result['memory'])
        self.assertEqual(len(result['disks']), 1)
        self.assertIsNone(result['cpu_temp_c'])

    def test_cpu_sensor_value_is_included_when_available(self):
        # The sensor rides on the same PowerShell process: a 'T=' line after the JSON line.
        windows = '{"cpu": [], "os": null, "disks": []}\r\nT=73\r\n'
        with patch('token_tv.tablet_metrics._run', side_effect=[windows, None]):
            result = tablet_metrics.collect()
        self.assertEqual(result['cpu_temp_c'], 73)

    def test_missing_metrics_never_become_zero(self):
        result = tablet_metrics.normalize_windows({'cpu': [], 'os': None, 'disks': []})
        self.assertIsNone(result['cpu_percent'])
        self.assertIsNone(result['memory'])
        self.assertEqual(result['disks'], [])

    def test_google_drive_cache_is_not_claimed_as_cloud_quota(self):
        result = tablet_metrics.normalize_windows({'disks': [
            {'DeviceID': 'C:', 'VolumeName': 'Windows', 'Size': 1000, 'FreeSpace': 40},
            {'DeviceID': 'G:', 'VolumeName': 'Google Drive', 'Size': 1000, 'FreeSpace': 40},
        ]})
        self.assertEqual(result['disks'][0], {'name': 'C:', 'total': 1000, 'free': 40})
        self.assertEqual(result['disks'][1], {'name': 'G:', 'kind': 'google_drive', 'total': None, 'free': None})

    def test_manually_confirmed_cloud_quota_is_dated_and_bound_to_one_drive(self):
        system = {'disks': [{'name': 'G:', 'kind': 'google_drive', 'total': None, 'free': None},
                            {'name': 'H:', 'kind': 'google_drive', 'total': None, 'free': None}]}
        reading = {'drive': 'G:', 'total': 5000, 'used': 115, 'recorded_at': 1000}
        tablet_metrics.apply_manual_google_quota(system, reading, now=1100)
        self.assertEqual(system['disks'][0], {'name': 'G:', 'kind': 'google_drive', 'total': 5000, 'free': 4885,
                                              'quota_source': 'manual', 'quota_at': 1000})
        self.assertIsNone(system['disks'][1]['free'])
        system = {'disks': [{'name': 'G:', 'kind': 'google_drive', 'total': None, 'free': None}]}
        tablet_metrics.apply_manual_google_quota(system, {**reading, 'used': 6000}, now=1100)
        self.assertIsNone(system['disks'][0]['free'])

    def test_invalid_storage_and_cpu_values_are_not_misreported(self):
        data = {'cpu': [{'LoadPercentage': -2}],
                'os': {'TotalVisibleMemorySize': 8, 'FreePhysicalMemory': 9},
                'disks': [{'DeviceID': 'C:', 'Size': 10, 'FreeSpace': 11},
                          {'DeviceID': 'invalid', 'Size': 10, 'FreeSpace': 2}]}
        result = tablet_metrics.normalize_windows(data)
        self.assertIsNone(result['cpu_percent'])
        self.assertIsNone(result['memory'])
        self.assertEqual(result['disks'], [])

    def test_nvidia_metrics_are_per_gpu_and_unavailable_is_unknown(self):
        data = 'GPU A, 55, 27, 300, 8000\nGPU B, [N/A], 0, 0, 4000\n'
        self.assertEqual(tablet_metrics.normalize_nvidia(data), [
            {'name': 'GPU A', 'temp_c': 55, 'percent': 27, 'memory_used_mb': 300, 'memory_total_mb': 8000},
            {'name': 'GPU B', 'temp_c': None, 'percent': 0, 'memory_used_mb': 0, 'memory_total_mb': 4000},
        ])

    def test_system_service_uses_absolute_windows_powershell_when_available(self):
        powershell = '/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe'
        data = '{"cpu": [], "os": null, "disks": []}'
        with patch('token_tv.tablet_metrics.os.path.isfile', side_effect=lambda path: path == powershell), \
             patch('token_tv.tablet_metrics._run', side_effect=[data, None, None]) as run:
            tablet_metrics.collect()
        self.assertEqual(run.call_args_list[0].args[0][0], powershell)

    def test_windows_uses_native_gpu_tool_when_available(self):
        with patch('token_tv.tablet_metrics.os.path.isfile', return_value=True), \
             patch('token_tv.tablet_metrics._run', side_effect=[None, 'GPU A, 55, 27, 300, 8000']) as run:
            result = tablet_metrics.collect()
        self.assertEqual(result['gpus'][0]['temp_c'], 55)
        self.assertEqual(run.call_args.args[0][0], '/mnt/c/Windows/System32/nvidia-smi.exe')

    def test_unavailable_commands_do_not_crash_the_collector(self):
        with patch('token_tv.tablet_metrics.subprocess.run', side_effect=subprocess.TimeoutExpired('test', 1)):
            result = tablet_metrics.collect()
        self.assertIsNone(result['cpu_percent'])
        self.assertIsNone(result['memory'])
        self.assertEqual(result['disks'], [])
        self.assertEqual(result['gpus'], [])


if __name__ == '__main__':
    unittest.main()
