import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from token_tv.board import BoardDisplay

class BoardRotationTests(unittest.TestCase):
    def test_heartbeat_uses_local_civil_time_and_no_external_request(self):
        board=BoardDisplay('http://192.168.1.2','0123456789abcdef')
        now=datetime(2026,10,22,16,29,59,tzinfo=timezone(timedelta(hours=2)))
        with patch('token_tv.board.datetime') as clock, patch.object(board,'request',return_value=(200,b'11111111')) as request:
            clock.now.return_value.astimezone.return_value=now
            self.assertEqual(board.ping(),'11111111')
            request.assert_called_once_with(f'/ping?clock={int(now.timestamp())+7200}',data=b'')

    def test_monitor_start_respects_firmware_selection_memory(self):
        for remembers in (True,False):
            board=BoardDisplay('http://192.168.1.2','0123456789abcdef')
            with patch.object(board,'info',return_value={'selection_memory':remembers,'paired':True}), patch.object(board,'show') as show:
                board.ensure_paired();board.select_initial_page()
                if remembers: show.assert_not_called()
                else: show.assert_called_once_with(0)
