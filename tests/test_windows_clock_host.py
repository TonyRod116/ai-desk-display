from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import unittest


spec = spec_from_file_location(
    "windows_clock_host", Path(__file__).parents[1] / "scripts/windows_clock_host.py"
)
host = module_from_spec(spec)
spec.loader.exec_module(host)


class WindowsClockHostTests(unittest.TestCase):
    def execute(self, outputs):
        commands = []
        replies = iter(outputs)

        def run(command, **kwargs):
            commands.append(command)
            self.assertEqual(command[:2], ["/usr/bin/systemctl", "--user"])
            self.assertEqual(command[-1], "token-tv.service")
            self.assertIn("XDG_RUNTIME_DIR", kwargs["env"])
            answer = next(replies)
            if isinstance(answer, Exception):
                raise answer
            return subprocess.CompletedProcess(
                command, 1 if answer == "disabled" else 0, answer, ""
            )

        result = host.clock_host(run=run, sleep=lambda _: None)
        return result, commands

    def test_disabled_service_never_starts(self):
        result, commands = self.execute(["disabled"])
        self.assertEqual(result, 0)
        self.assertEqual(len(commands), 1)

    def test_stopped_service_ends_host_without_restarting(self):
        result, commands = self.execute([
            "enabled", "active", "activating"
        ] + ["inactive"] * 6)
        self.assertEqual(result, 0)
        self.assertFalse(any("start" in command for command in commands))

    def test_restart_and_transient_bus_failure_preserve_host(self):
        result, commands = self.execute([
            "enabled", "active", "deactivating", "activating", "active",
            subprocess.TimeoutExpired("systemctl", 15), "active"
        ] + ["inactive"] * 6)
        self.assertEqual(result, 0)
        self.assertFalse(any("start" in command for command in commands))
        self.assertFalse(any("restart" in command for command in commands))

    def test_launching_again_after_a_stop_never_resurrects_service(self):
        result, commands = self.execute(["enabled"] + ["inactive"] * 12)
        self.assertEqual(result, 0)
        self.assertFalse(any("start" in command for command in commands))

    def test_missing_bus_has_a_bounded_retry(self):
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            raise subprocess.TimeoutExpired(command, 15)

        self.assertEqual(host.clock_host(run=run, sleep=lambda _: None), 1)
        self.assertEqual(len(calls), 12)
        self.assertFalse(any("start" in command for command in calls))
