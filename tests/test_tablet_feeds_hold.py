"""The tablet's feeds keep the last good reading through a failed poll (Tony, 2026-11-19: the small screen never loses its numbers, the tablet did).

Fakes only; no real monitor, Windows or network."""
import time
import unittest

from token_tv import tablet_server as ts
from token_tv.tablet_server import Feeds

GOOD = {'providers': {'codex': {'weekly': {'remaining': 40, 'resets_at': 1}, 'aged': False}, 'claude': {'weekly': {'remaining': 60, 'resets_at': 1}, 'aged': False}}}
PC = {'cpu_percent': 12, 'memory': {'total': 100, 'free': 50}, 'disks': [{'name': 'C:'}], 'gpus': []}


def once(feeds, method, name, stamp):
    """Run one iteration of a feed loop with this poll function."""
    def wrapped():
        try:
            return method()
        finally:
            feeds.stop.set()
    feeds._loop(wrapped, 5, name, stamp)


class QuotaHoldTests(unittest.TestCase):
    def feeds(self, age):
        feeds = Feeds(snapshot=lambda: None, metrics=lambda: None)
        feeds.quota, feeds.quota_at = GOOD, time.monotonic() - age
        return feeds

    def test_a_fresh_reading_is_connected_and_unmarked(self):
        status = self.feeds(2).status()
        self.assertTrue(status['quota_connected'])
        self.assertFalse(status['providers']['codex']['aged'])
        self.assertLessEqual(status['quota_age'], 3)

    def test_a_gap_keeps_the_numbers_marks_them_aged_and_says_not_connected(self):
        for age in (21, 60, 119):
            status = self.feeds(age).status()
            self.assertFalse(status['quota_connected'], age)
            self.assertEqual(status['providers']['claude']['weekly']['remaining'], 60, age)
            self.assertTrue(status['providers']['claude']['aged'] and status['providers']['codex']['aged'], age)

    def test_a_long_outage_ends_in_honest_dashes(self):
        status = self.feeds(ts.QUOTA_HOLD + 1).status()
        self.assertFalse(status['quota_connected'])
        self.assertEqual(status['providers'], {})
        self.assertIsNone(status['quota_age'])

    def test_the_held_reading_is_a_copy_the_original_is_not_marked(self):
        feeds = self.feeds(60)
        feeds.status()
        self.assertFalse(GOOD['providers']['codex']['aged'])

    def test_a_failed_or_raising_poll_keeps_the_last_good_one_and_its_age(self):
        feeds = Feeds(snapshot=lambda: None, metrics=lambda: None)
        once(feeds, lambda: GOOD, 'quota', 'quota_at')
        stamp = feeds.quota_at
        for failure in (lambda: None, lambda: (_ for _ in ()).throw(OSError('down'))):
            feeds.stop.clear()
            once(feeds, failure, 'quota', 'quota_at')
            self.assertIs(feeds.quota, GOOD)
            self.assertEqual(feeds.quota_at, stamp)              # the failure does not make the old reading look new

    def test_a_new_good_poll_replaces_it_and_renews_the_stamp(self):
        feeds = self.feeds(60)
        newer = {'providers': {'codex': {'weekly': {'remaining': 39, 'resets_at': 1}, 'aged': False}}}
        once(feeds, lambda: newer, 'quota', 'quota_at')
        status = feeds.status()
        self.assertTrue(status['quota_connected'])
        self.assertEqual(status['providers']['codex']['weekly']['remaining'], 39)


class HardwareHoldTests(unittest.TestCase):
    def test_an_empty_collection_is_a_failure_not_a_pc_without_parts(self):
        feeds = Feeds(snapshot=lambda: None, metrics=lambda: None)
        once(feeds, lambda: PC, 'hardware', 'hardware_at')
        stamp = feeds.hardware_at
        for empty in ({}, {'cpu_percent': None, 'memory': None, 'disks': [], 'gpus': []}, None):
            feeds.stop.clear()
            once(feeds, lambda empty=empty: empty, 'hardware', 'hardware_at')
            self.assertIs(feeds.hardware, PC)
            self.assertEqual(feeds.hardware_at, stamp)

    def test_the_pcs_numbers_are_held_for_a_few_missed_collections_then_dropped(self):
        feeds = Feeds(snapshot=lambda: None, metrics=lambda: None)
        feeds.hardware = PC
        feeds.hardware_at = time.monotonic() - 200
        self.assertEqual(feeds.status()['metrics']['cpu_percent'], 12)
        feeds.hardware_at = time.monotonic() - (ts.HARDWARE_HOLD + 1)
        self.assertIsNone(feeds.status()['metrics'])

    def test_usable_means_at_least_one_real_part(self):
        self.assertTrue(ts._usable_hardware(PC))
        self.assertTrue(ts._usable_hardware({'disks': [{'name': 'C:'}]}))
        for bad in (None, {}, [], 'x', {'cpu_percent': None}, {'disks': [], 'gpus': [], 'memory': None}):
            self.assertFalse(ts._usable_hardware(bad))


class ReportTests(unittest.TestCase):
    def test_the_page_may_report_how_its_polls_went_and_nothing_else_comes_through(self):
        clean = ts.clean_report({'why': 'tick', 'conn': 'offline', 'st_ok': 98, 'st_bad': 3, 'st_gap': 14, 'st_age': 6, 'st_ms': 210, 'held': True, 'conn_extra': 'x', 'st_evil': 9})
        self.assertEqual({k: clean[k] for k in ('conn', 'st_ok', 'st_bad', 'st_gap', 'st_age', 'st_ms', 'held')},
                         {'conn': 'offline', 'st_ok': 98, 'st_bad': 3, 'st_gap': 14, 'st_age': 6, 'st_ms': 210, 'held': True})
        self.assertNotIn('conn_extra', clean)
        self.assertNotIn('st_evil', clean)
        self.assertNotIn('conn', ts.clean_report({'why': 'tick', 'conn': 'hacked'}))
        self.assertNotIn('st_ok', ts.clean_report({'why': 'tick', 'st_ok': -1}))


if __name__ == '__main__':
    unittest.main()
