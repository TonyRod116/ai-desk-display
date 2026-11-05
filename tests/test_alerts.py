"""Desk alerts: one toast per outage after half an hour without a reading, one when it is back. No test starts powershell."""
import base64
import contextlib
import io
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree

from token_tv import alerts
from token_tv.alerts import ALERT_AFTER_SECONDS, MARKER, Alerts, message, powershell_command, toast_script
from token_tv.reader_status import REASONS

OK = (0, MARKER + '\n')
T0 = 1_800_000_000


class Runner:
    """Stands in for powershell.exe: answers from a script of results (a pair, or an exception to raise), then repeats the last."""
    def __init__(self, *results):
        self.results, self.calls = list(results), []

    def __call__(self, command, timeout):
        self.calls.append((command, timeout))
        result = self.results.pop(0) if len(self.results) > 1 else self.results[0]
        if isinstance(result, Exception):
            raise result
        return result

    def scripts(self):
        return [base64.b64decode(call[0][-1]).decode('utf-16-le') for call in self.calls]


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'state/alerts-claude.json'

    def make(self, *results, provider='claude'):
        runner = Runner(*(results or (OK,)))
        return Alerts(self.path, provider, runner=runner), runner

    def watch(self, alert, start, seconds, usable, reason=None, every=60):
        for moment in range(start, start + seconds + 1, every):
            alert.observe(usable, reason, moment)

    def test_nothing_is_said_before_half_an_hour_and_one_toast_after_it_for_the_whole_outage(self):
        alert, runner = self.make()
        self.watch(alert, T0, ALERT_AFTER_SECONDS - 60, False, 'rate_limited')
        self.assertEqual(runner.calls, [])
        self.watch(alert, T0 + ALERT_AFTER_SECONDS - 60, 120, False, 'rate_limited')
        self.assertEqual(len(runner.calls), 1)
        self.watch(alert, T0 + ALERT_AFTER_SECONDS + 120, 3 * 86400, False, 'rate_limited', every=600)   # three more days
        self.assertEqual(len(runner.calls), 1)
        self.assertIn('Claude readings are missing', runner.scripts()[0])
        self.assertIn('Too many requests', runner.scripts()[0])

    def test_a_recovery_after_a_delivered_alert_gets_its_own_toast_once(self):
        alert, runner = self.make()
        self.watch(alert, T0, ALERT_AFTER_SECONDS + 60, False, 'org_blocked')
        self.watch(alert, T0 + ALERT_AFTER_SECONDS + 120, 600, True, every=60)
        self.assertEqual(len(runner.calls), 2)
        self.assertIn('Claude readings are back', runner.scripts()[1])
        self.watch(alert, T0 + 5 * 3600, 3600, True)
        self.assertEqual(len(runner.calls), 2)
        # A new outage later is a new alert.
        self.watch(alert, T0 + 6 * 3600, ALERT_AFTER_SECONDS + 60, False, 'login_required')
        self.assertEqual(len(runner.calls), 3)

    def test_an_outage_that_ends_before_the_threshold_says_nothing_at_all(self):
        alert, runner = self.make()
        self.watch(alert, T0, ALERT_AFTER_SECONDS - 120, False, 'reader_stuck')
        self.watch(alert, T0 + ALERT_AFTER_SECONDS, 3600, True)
        self.assertEqual(runner.calls, [])

    def test_a_lost_toast_is_never_counted_as_delivered_and_is_retried_gently(self):
        # powershell can fail here without a word (UtilAcceptVsock accept4 failed 110), or print nothing, or hang.
        failures = [(1, ''), (0, ''), (0, 'something else'), subprocess.TimeoutExpired('powershell.exe', 12), OSError('no interop')]
        alert, runner = self.make(*failures, OK)
        self.watch(alert, T0, ALERT_AFTER_SECONDS, False, 'rate_limited')
        self.assertEqual(len(runner.calls), 1)                                 # first try: failed
        moments = []
        for moment in range(T0 + ALERT_AFTER_SECONDS, T0 + ALERT_AFTER_SECONDS + 6 * 3600, 60):
            before = len(runner.calls)
            alert.observe(False, 'rate_limited', moment)
            if len(runner.calls) > before:
                moments.append(moment)
        self.assertEqual(len(runner.calls), 6)                                 # four failures, a timeout... then it went through
        gaps = [b - a for a, b in zip([T0 + ALERT_AFTER_SECONDS] + moments, moments)]
        self.assertEqual(gaps, [300, 600, 1200, 2400, 3600][:len(gaps)])       # no sooner than five minutes, then ever less often
        self.assertTrue(all(gap >= 300 for gap in gaps))
        later = len(runner.calls)
        self.watch(alert, T0 + 7 * 3600, 6 * 3600, False, 'rate_limited', every=600)
        self.assertEqual(len(runner.calls), later)                            # delivered once: never again for this outage

    def test_a_lost_back_toast_is_retried_then_dropped_when_it_is_no_longer_news(self):
        alert, runner = self.make(OK, (1, ''))
        self.watch(alert, T0, ALERT_AFTER_SECONDS + 60, False, 'reader_stuck')
        self.assertEqual(len(runner.calls), 1)
        start = T0 + ALERT_AFTER_SECONDS + 120
        self.watch(alert, start, 3 * 3600, True, every=60)
        sent = len(runner.calls)
        self.assertGreater(sent, 2)                                           # it tried again, gently...
        self.assertLessEqual(sent, 6)                                         # ...and gave up within the hour
        after = len(runner.calls)
        self.watch(alert, start + 3 * 3600, 3600, True, every=60)
        self.assertEqual(len(runner.calls), after)                            # an hour after the recovery it is dropped

    def test_a_restart_neither_repeats_nor_forgets_a_toast(self):
        alert, runner = self.make()
        self.watch(alert, T0, ALERT_AFTER_SECONDS + 60, False, 'rate_limited')
        self.assertEqual(len(runner.calls), 1)
        again = Alerts(self.path, 'claude', runner=runner)                    # a new process, same state file
        again.observe(False, 'rate_limited', T0 + ALERT_AFTER_SECONDS + 120)
        self.assertEqual(len(runner.calls), 1)
        again.observe(True, None, T0 + ALERT_AFTER_SECONDS + 180)             # and it still knows it must say the readings are back
        self.assertEqual(len(runner.calls), 2)
        # A toast that failed before the restart is still owed after it.
        other = Path(self.directory.name) / 'owed.json'
        failing = Runner((1, ''))
        self.watch(Alerts(other, 'codex', runner=failing), T0, ALERT_AFTER_SECONDS + 60, False, 'reader_stuck')
        self.assertEqual(len(failing.calls), 1)
        working = Runner(OK)
        Alerts(other, 'codex', runner=working).observe(False, 'reader_stuck', T0 + ALERT_AFTER_SECONDS + 460)
        self.assertEqual(len(working.calls), 1)

    def test_time_when_nobody_was_watching_does_not_count_as_an_outage(self):
        alert, runner = self.make()
        alert.observe(False, 'rate_limited', T0)
        alert.observe(False, 'rate_limited', T0 + 600)
        # The service was off for two days; on return the reading is still missing, but the clock starts again.
        alert.observe(False, 'rate_limited', T0 + 2 * 86400)
        self.assertEqual(runner.calls, [])
        alert.observe(False, 'rate_limited', T0 + 2 * 86400 + 60)
        self.assertEqual(runner.calls, [])
        self.watch(alert, T0 + 2 * 86400 + 120, ALERT_AFTER_SECONDS, False, 'rate_limited')
        self.assertEqual(len(runner.calls), 1)

    def test_a_second_outage_before_the_back_toast_is_one_long_outage(self):
        alert, runner = self.make(OK, (1, ''))
        self.watch(alert, T0, ALERT_AFTER_SECONDS + 60, False, 'reader_stuck')
        alert.observe(True, None, T0 + 2400)                                    # back, but the toast fails
        alert.observe(False, 'reader_stuck', T0 + 2460)                         # and down again
        self.watch(alert, T0 + 2520, 4 * 3600, False, 'reader_stuck', every=300)
        self.assertEqual(len(runner.calls), 2)                                # no new "missing" toast for what he still sees as one outage

    def test_nothing_an_alert_does_can_disturb_its_caller(self):
        alert, _ = self.make(RuntimeError('PRIVATE'))
        alert.observe(False, 'rate_limited', T0)
        alert.observe(False, 'rate_limited', T0 + ALERT_AFTER_SECONDS)            # the runner raises: swallowed
        self.path.write_text('not json')
        alert.observe(True, None, T0 + ALERT_AFTER_SECONDS + 60)                  # a broken state file: swallowed
        blocked = Alerts(Path(self.directory.name) / 'state/alerts-claude.json/inside', 'claude', runner=Runner(OK))
        blocked.observe(False, 'rate_limited', T0)                                # an unwritable path: swallowed
        with self.assertRaises(ValueError):
            Alerts(self.path, 'grok')

    def test_the_state_file_is_private_and_holds_only_numbers_and_flags(self):
        alert, _ = self.make()
        self.watch(alert, T0, ALERT_AFTER_SECONDS + 60, False, 'rate_limited')
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        state = json.loads(self.path.read_text())
        self.assertEqual(set(state), {'seen', 'down_since', 'told', 'owed', 'owed_at', 'tried', 'failures'})
        self.assertTrue(all(value is None or type(value) in (int, bool) or value in ('missing', 'back') for value in state.values()))
        self.assertTrue(state['told'])


class ToastTests(unittest.TestCase):
    def test_the_words_are_fixed_and_a_reason_that_is_not_one_of_ours_says_nothing_about_it(self):
        for provider in ('claude', 'codex'):
            for reason in list(REASONS) + [None, 'rate_limited<script>', "x'y", 'user@example.com']:
                title, body = message('missing', provider, reason)
                self.assertTrue(title.startswith(provider.title() + ' readings'))
                known = reason if reason in REASONS else 'unknown'
                self.assertIn(REASONS[known][0], body)
                self.assertNotIn('example.com', title + body)
                self.assertNotIn('<script>', title + body)
        self.assertEqual(message('back', 'codex')[0], 'Codex readings are back')

    def test_the_script_is_one_quiet_toast_with_a_success_marker_and_no_account_data(self):
        script = toast_script(*message('missing', 'claude', 'org_blocked'), 'tokentv-claude')
        self.assertIn('Access blocked', script)
        self.assertIn('<audio silent="true"/>', script)                             # quiet
        self.assertNotIn('scenario', script)                                        # no reminder/alarm: nothing that holds the screen
        self.assertIn("$toast.Tag = 'tokentv-claude'", script)                      # replaces its predecessor
        self.assertIn(MARKER, script)
        self.assertNotIn('@', script)
        # Quotes and angle brackets in the words can neither break the script nor inject into it.
        nasty = toast_script("a'b<c>&d", "e'f", 'tokentv-x')
        self.assertIn("a''b&lt;c&gt;&amp;d", nasty)
        # The toast XML Windows will be given is well formed and says exactly the two lines.
        for text, expected in ((script, ['Claude readings are missing', 'Access blocked. No reading for over 30 minutes.']),
                               (nasty, ["a'b<c>&d", "e'f"])):
            xml = re.search(r"LoadXml\('(.*?)'\)", text).group(1).replace("''", "'")
            root = ElementTree.fromstring(xml)
            self.assertEqual([node.text for node in root.iter('text')], expected)
            self.assertEqual(root.find('audio').get('silent'), 'true')

    def test_the_command_is_hidden_non_interactive_and_carries_the_script_encoded(self):
        script = toast_script('t', 'b', 'tag')
        command = powershell_command(script)
        self.assertTrue(command[0].endswith('powershell.exe'))
        self.assertEqual(command[1:7], ['-NoProfile', '-NonInteractive', '-NoLogo', '-WindowStyle', 'Hidden', '-EncodedCommand'])
        self.assertEqual(base64.b64decode(command[-1]).decode('utf-16-le'), script)

    def test_the_provider_must_be_ours_and_the_test_command_refuses_other_arguments(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(alerts.main(['send', 'claude']), 2)
            self.assertEqual(alerts.main(['test', 'grok']), 2)
            self.assertEqual(alerts.main([]), 2)


class RealRunnerTests(unittest.TestCase):
    def test_output_in_a_windows_code_page_is_not_a_failure(self):
        import sys
        from token_tv.alerts import run_powershell
        script = "import sys; sys.stdout.buffer.write(b'caf\\xe9 TOKENTV-OK\\n'); sys.stderr.buffer.write(b'\\xa2')"
        code, output = run_powershell([sys.executable, '-c', script], 10)
        self.assertEqual(code, 0)
        self.assertIn('TOKENTV-OK', output)


if __name__ == '__main__':
    unittest.main()
