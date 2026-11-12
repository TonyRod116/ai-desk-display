"""Memory action policy tests: all results and programs here are fictional."""
import threading
import subprocess
from unittest.mock import patch
import unittest
from token_tv import tablet_memory
from token_tv.tablet_memory import MemoryRelief


class Clock:
    def __init__(self): self.now = 1000.0
    def __call__(self): return self.now


class MemoryReliefTests(unittest.TestCase):
    def setUp(self):
        self.clock=Clock();self.calls=[]
        self.value={'state':'done','apps':['Slack'],'before':4_000_000_000,'after':4_100_000_000}
        self.relief=MemoryRelief(runner=self.fake_runner,clock=self.clock,cooldown=120)
    def fake_runner(self):
        self.calls.append(True);return self.value
    def test_creation_never_starts_a_cleanup(self):
        with patch.object(tablet_memory.subprocess, 'run') as run:
            MemoryRelief()
            run.assert_not_called()

    def test_a_success_is_bounded_and_rate_limited(self):
        self.assertEqual(self.relief.release(),self.value)
        self.assertEqual(self.relief.release()['state'],'cooldown')
        self.assertEqual(len(self.calls),1)
        self.clock.now+=121
        self.assertEqual(self.relief.release(),self.value)
        self.assertEqual(len(self.calls),2)
    def test_no_candidates_is_honest_and_unknown_is_never_a_number(self):
        self.value={'state':'nothing','apps':[],'before':None,'after':None}
        self.assertEqual(self.relief.release(),self.value)
    def test_untrusted_runner_output_cannot_name_another_process_or_leak_text(self):
        for bad in ({'state':'done','apps':['python'],'before':1,'after':2},
                    {'state':'done','apps':[{}],'before':1,'after':2},
                    {'state':'done','apps':['Slack','Slack'],'before':1,'after':2},
                    {'state':'done','apps':['Slack'],'before':-1,'after':2},
                    {'state':'done','apps':['Slack'],'before':1,'after':2,'secret':'do-not-return'},
                    {'state':'done','apps':[],'before':1,'after':2},
                    {'state':'nothing','apps':['Slack'],'before':1,'after':2},
                    {'state':'wrong','apps':[],'before':None,'after':None}):
            with self.subTest(bad=bad):
                self.clock.now+=121;self.value=bad
                self.assertEqual(self.relief.release()['state'],'unknown')
    def test_runner_exception_is_unknown_and_cannot_be_retried_immediately(self):
        def failed(): raise RuntimeError('private details')
        relief=MemoryRelief(runner=failed,clock=self.clock)
        self.assertEqual(relief.release(),{'state':'unknown'})
        self.assertEqual(relief.release()['state'],'cooldown')
    def test_relay_probes_are_fixed_and_stop_at_the_first_working_socket(self):
        responses=[subprocess.TimeoutExpired('probe',1.5), subprocess.CompletedProcess(['probe'],0,stdout=b'')]
        with patch.object(tablet_memory.os.path, 'isfile', return_value=True), \
             patch.object(tablet_memory.tablet_metrics, '_interop_candidates', return_value=['/run/WSL/1_interop','/run/WSL/2_interop']), \
             patch.object(tablet_memory.tablet_metrics, '_interop_override', None), \
             patch.object(tablet_memory.subprocess, 'run', side_effect=responses) as run:
            self.assertEqual(tablet_memory._relay({'PATH':'/bin'}),'/run/WSL/2_interop')
        self.assertEqual(run.call_count,2)
        for call in run.call_args_list:
            self.assertEqual(call.args[0][-4:], ['/d','/c','exit','0'])
            self.assertNotIn('SECRET',call.kwargs['env'])
    def test_invalid_or_oversized_output_is_unknown_and_never_retried(self):
        for output in (b'not-json', b'X' * (tablet_memory.MAX_OUTPUT + 1)):
            with self.subTest(size=len(output)), patch.object(tablet_memory.os.path,'isfile',return_value=True), \
                 patch.object(tablet_memory,'_relay',return_value='/run/WSL/123_interop'), \
                 patch.object(tablet_memory.subprocess,'run',return_value=subprocess.CompletedProcess([],0,stdout=output)) as run:
                self.assertEqual(tablet_memory._execute(),{'state':'unknown'})
                self.assertEqual(run.call_count,1)

    def test_windows_action_is_not_retried_after_an_ambiguous_timeout(self):
        with patch.object(tablet_memory.os.path, 'isfile', return_value=True), \
             patch.object(tablet_memory, '_relay', return_value='/run/WSL/123_interop'), \
             patch.object(tablet_memory.subprocess, 'run', side_effect=subprocess.TimeoutExpired('fake',25)) as run:
            self.assertEqual(tablet_memory._execute(), {'state':'unknown'})
            self.assertEqual(run.call_count, 1, 'never repeat an action that may already have happened')
    def test_action_uses_a_fixed_command_and_does_not_pass_unrelated_environment(self):
        import json
        output=json.dumps({'state':'done','apps':['Slack'],'before':100,'after':110}).encode()
        with patch.dict(tablet_memory.os.environ, {'PATH':'/bin','SECRET':'never-pass'}, clear=True), \
             patch.object(tablet_memory.os.path, 'isfile', return_value=True), \
             patch.object(tablet_memory, '_relay', return_value='/run/WSL/123_interop'), \
             patch.object(tablet_memory.subprocess, 'run', return_value=subprocess.CompletedProcess([],0,stdout=output)) as run:
            self.assertEqual(tablet_memory._execute()['state'], 'done')
        self.assertEqual(run.call_count, 1)
        self.assertNotIn('SECRET', run.call_args.kwargs['env'])
        self.assertEqual(run.call_args.args[0][0], tablet_memory.WINDOWS_POWERSHELL)
        self.assertIn('-EncodedCommand', run.call_args.args[0])

    def test_no_relay_never_starts_an_action(self):
        with patch.object(tablet_memory.os.path, 'isfile', return_value=True), \
             patch.object(tablet_memory, '_relay', return_value=None), \
             patch.object(tablet_memory.subprocess, 'run') as run:
            self.assertEqual(tablet_memory._execute(), {'state':'unavailable'})
            run.assert_not_called()
    def test_the_fixed_windows_script_is_bounded_and_does_not_kill_or_elevate(self):
        import base64
        code=tablet_memory.WINDOWS_SCRIPT
        self.assertLess(len(base64.b64encode(code.encode('utf-16le'))),30000)
        for forbidden in ('Stop-Process','Kill(', 'SeDebugPrivilege', 'runas', 'NtSetSystemInformation'):
            self.assertNotIn(forbidden,code)
        self.assertIn('EmptyWorkingSet',code)
        self.assertIn("@('Slack','OneDrive')",code)
        self.assertIn('Foreground()',code)
        self.assertIn('SameGroup(',code)
        self.assertIn('Idle(',code)
        self.assertIn('CanTry()',code)
        self.assertIn('SameUser(',code)
        self.assertNotIn('GetProcesses()',code)

    def test_parallel_taps_never_launch_two_operations(self):
        started=threading.Event();finish=threading.Event()
        def running(): started.set();finish.wait(2);return self.value
        relief=MemoryRelief(runner=running,clock=self.clock)
        thread=threading.Thread(target=relief.release);thread.start()
        self.assertTrue(started.wait(1))
        self.assertEqual(relief.release(),{'state':'busy'})
        finish.set();thread.join(2);self.assertFalse(thread.is_alive())


if __name__ == '__main__': unittest.main()
