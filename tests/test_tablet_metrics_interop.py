import subprocess
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from token_tv import tablet_metrics as m

class InteropRecoveryTests(unittest.TestCase):
    def setUp(self):
        m.reset_state()
        self.addCleanup(m.reset_state)

    def test_only_trusted_sockets_are_candidates_and_a_disappearing_one_is_skipped(self):
        class Entry:
            def __init__(self, name, mode, uid=0, missing=False):
                self.name, self.mode, self.uid, self.missing = name, mode, uid, missing
            def __str__(self): return '/run/WSL/' + self.name
            def lstat(self):
                if self.missing: raise FileNotFoundError()
                return SimpleNamespace(st_mode=self.mode, st_uid=self.uid)
        class Directory:
            def lstat(self): return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755, st_uid=0)
            def iterdir(self):
                return iter([Entry('600_interop', stat.S_IFSOCK, missing=True), Entry('2_interop', stat.S_IFSOCK),
                             Entry('2468_interop', stat.S_IFSOCK), Entry('637_interop', stat.S_IFLNK),
                             Entry('638_interop', stat.S_IFSOCK, uid=1000), Entry('wrong_interop', stat.S_IFSOCK)])
        with patch.object(m, 'Path', return_value=Directory()):
            self.assertEqual(m._interop_candidates('/run/WSL/2_interop'), ['/run/WSL/2468_interop'])

    def test_an_untrusted_wsl_directory_is_never_scanned(self):
        class Directory:
            def __init__(self, mode, uid): self.mode, self.uid = mode, uid
            def lstat(self): return SimpleNamespace(st_mode=self.mode, st_uid=self.uid)
            def iterdir(self): raise AssertionError('untrusted directory must not be scanned')
        for mode, uid in ((stat.S_IFDIR | 0o777, 0), (stat.S_IFDIR | 0o755, 1000), (stat.S_IFLNK, 0)):
            with patch.object(m, 'Path', return_value=Directory(mode, uid)):
                self.assertEqual(m._interop_candidates(None), [])

    def test_timed_out_windows_program_recovers_once_and_reuses_new_socket(self):
        cmd = ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe', '-NoProfile']
        nvidia = ['/mnt/c/Windows/System32/nvidia-smi.exe']
        calls = []
        def run(args, **kw):
            calls.append((args, kw.get('env', {})))
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(args, kw['timeout'])
            return subprocess.CompletedProcess(args, 0, stdout=b'hello')
        with patch.object(m, '_interop_candidates', return_value=['/run/WSL/2468_interop']), \
             patch.object(m.os.path, 'isfile', return_value=True), patch.object(m.subprocess, 'run', side_effect=run):
            self.assertEqual(m._run(cmd, 20, partial=True), 'hello')
            self.assertEqual(m._run(nvidia, 8), 'hello')
        self.assertEqual(len(calls), 4, 'one failure, one probe, one retry and one later call')
        self.assertEqual(calls[1][0][-4:], ['/d', '/c', 'exit', '0'], 'probe cannot run Windows AutoRun commands')
        for _, env in calls[1:]: self.assertEqual(env['WSL_INTEROP'], '/run/WSL/2468_interop')

    def test_windows_reports_a_broken_vsock_as_an_error_instead_of_timing_out(self):
        cmd = ['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe']
        calls = []
        def run(args, **kw):
            calls.append(args)
            if len(calls) == 1:
                raise subprocess.CalledProcessError(1, args, output=b'', stderr=b'<3>WSL (5) ERROR: UtilAcceptVsock: accept4 failed')
            return subprocess.CompletedProcess(args, 0, stdout=b'ok')
        with patch.object(m, '_interop_candidates', return_value=['/run/WSL/2468_interop']),              patch.object(m.os.path, 'isfile', return_value=True), patch.object(m.subprocess, 'run', side_effect=run):
            self.assertEqual(m._run(cmd, 20, partial=True), 'ok')
        self.assertEqual(len(calls), 3)

    def test_an_unrelated_program_error_does_not_probe_other_sockets(self):
        cmd=['/mnt/c/Windows/System32/nvidia-smi.exe']
        error=subprocess.CalledProcessError(1, cmd, output=b'', stderr=b'GPU driver unavailable')
        with patch.object(m.subprocess, 'run', side_effect=error), patch.object(m, '_interop_candidates') as candidates:
            self.assertIsNone(m._run(cmd, 8))
            candidates.assert_not_called()

    def test_partial_sensor_results_are_not_replaced_by_a_recovery_probe(self):
        cmd=['/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe']
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired(cmd, 20, output=b'{"cpu":[]}')), \
             patch.object(m, '_interop_candidates') as candidates:
            self.assertEqual(m._run(cmd, 20, partial=True), '{"cpu":[]}')
            candidates.assert_not_called()

    def test_non_windows_failure_does_not_try_windows_connections(self):
        cmd=['/usr/bin/no-such-program']
        with patch.object(m.subprocess, 'run', side_effect=subprocess.TimeoutExpired(cmd, 2)), \
             patch.object(m, '_interop_candidates') as candidates:
            self.assertIsNone(m._run(cmd, 2))
            candidates.assert_not_called()

if __name__ == "__main__":
    unittest.main()
