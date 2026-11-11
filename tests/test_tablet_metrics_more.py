"""The tablet's richer PC data: programs, network, battery, uptime and the trend memory.

Everything here uses fabricated script output: no real PC, PowerShell or GPU is needed.
"""
import base64
import json
import math
import re
import subprocess
import threading
import unittest
from unittest.mock import patch

from token_tv import tablet_history, tablet_metrics
from token_tv.tablet_history import MetricsHistory
from token_tv.tablet_rates import MAX_ROWS, RateTracker, clean_name

TICKS = 10_000_000          # Stopwatch and CPU time units per second (100 ns)
MIB = 1024 * 1024
FILETIME_BASE = 134_387_000_000_000_000     # above 2**53: counters must stay exact integers
LUID_A, LUID_B = '0x00000000_0x00016EC6', '0x00000000_0x068CC779'


def processes(seconds, rows, cpus=4):
    """The script's process block at `seconds`; rows are (name, pid, cpu seconds or None, MB or None)."""
    return {'t': int(seconds * TICKS), 'f': TICKS, 'n': cpus,
            'p': [[name, pid, None if cpu is None else int(cpu * TICKS),
                   None if mb is None else int(mb * MIB)] for name, pid, cpu, mb in rows]}


def gpu(seconds, rows):
    """The GPU engine block; rows are (pid, luid, engine number, engine type, busy seconds)."""
    return {'t': FILETIME_BASE + int(seconds * TICKS),
            'p': [['pid_%d_luid_%s_phys_0_eng_%d_engtype_%s' % (pid, luid, engine, kind), int(busy * TICKS)]
                  for pid, luid, engine, kind, busy in rows]}


def network(seconds, adapters):
    return {'t': int(seconds * TICKS), 'f': TICKS, 'a': [list(adapter) for adapter in adapters]}


def update(tracker, pr=None, gp=None, net=None):
    data = {key: value for key, value in (('pr', pr), ('gp', gp), ('net', net)) if value is not None}
    return tracker.update(data)


class NameTests(unittest.TestCase):
    def test_extension_is_dropped_whatever_its_case(self):
        self.assertEqual(clean_name('chrome.exe'), 'chrome')
        self.assertEqual(clean_name('CHROME.EXE'), 'CHROME')
        self.assertEqual(clean_name('Sierra Chart'), 'Sierra Chart')

    def test_only_printable_characters_survive(self):
        self.assertEqual(clean_name('ev\x00il\n\t.exe'), 'evil')
        self.assertEqual(clean_name('safe\u202eexe.txt'), 'safeexe.txt')       # right-to-left override
        self.assertEqual(clean_name('zero\u200bwidth'), 'zerowidth')

    def test_names_are_cut_at_24_characters_after_the_extension(self):
        self.assertEqual(clean_name('x' * 40), 'x' * 24)
        self.assertEqual(clean_name('y' * 30 + '.exe'), 'y' * 24)

    def test_nothing_left_means_no_name(self):
        for value in (None, 5, b'chrome', '', '   ', '.exe', '\x00\x01', ['chrome']):
            with self.subTest(value=value):
                self.assertIsNone(clean_name(value))


class ProgramShareTests(unittest.TestCase):
    def setUp(self):
        self.tracker = RateTracker()

    def two_readings(self, before, after, window=30, cpus=4):
        update(self.tracker, pr=processes(1000, before, cpus))
        return update(self.tracker, pr=processes(1000 + window, after, cpus))[0]

    def test_first_reading_ranks_memory_but_has_no_cpu_share(self):
        result, network_result = update(self.tracker, pr=processes(1000, [('a', 1, 50, 300), ('b', 2, 10, 800)]))
        self.assertIsNone(result['cpu'])
        self.assertIsNone(result['gpu'])
        self.assertEqual(result['memory'], [{'name': 'b', 'mem_mb': 800}, {'name': 'a', 'mem_mb': 300}])
        self.assertIsNone(network_result)

    def test_share_is_a_percentage_of_the_whole_machine(self):
        # 12 CPU seconds in 30 s on 4 logical processors: 12 / (30 * 4) = 10 %.
        result = self.two_readings([('worker', 10, 100, 300)], [('worker', 10, 112, 310)])
        self.assertEqual(result['cpu'], [{'name': 'worker', 'percent': 10.0, 'mem_mb': 310}])

    def test_processes_with_one_name_are_merged_whatever_their_case(self):
        before = [('chrome', 1, 10, 100), ('chrome', 2, 20, 150), ('Chrome', 3, 30, 50), ('other', 4, 5, 20)]
        after = [('chrome', 1, 13, 100), ('chrome', 2, 26, 150), ('Chrome', 3, 33, 50), ('other', 4, 5, 20)]
        result = self.two_readings(before, after)
        self.assertEqual(result['cpu'], [{'name': 'chrome', 'percent': 10.0, 'mem_mb': 300}])
        self.assertEqual(result['memory'][0], {'name': 'chrome', 'mem_mb': 300})

    def test_top_six_by_cpu_in_descending_order_and_idle_ones_are_left_out(self):
        names = 'abcdefgh'
        deltas = [24, 12, 6, 3, 1.2, 0.6, 0.12, 0]       # seconds in the 30 s window: 20, 10, 5, 2.5, 1, 0.5, 0.1, 0 %
        before = [(name, 10 + i, 100, 10) for i, name in enumerate(names)]
        after = [(name, 10 + i, 100 + delta, 10) for i, (name, delta) in enumerate(zip(names, deltas))]
        result = self.two_readings(before, after)
        self.assertEqual([(entry['name'], entry['percent']) for entry in result['cpu']],
                         [('a', 20.0), ('b', 10.0), ('c', 5.0), ('d', 2.5), ('e', 1.0), ('f', 0.5)])

    def test_equal_shares_are_ordered_by_name(self):
        result = self.two_readings([('zeta', 1, 0, 1), ('Alpha', 2, 0, 1), ('mid', 3, 0, 1)],
                                   [('zeta', 1, 6, 1), ('Alpha', 2, 6, 1), ('mid', 3, 6, 1)])
        self.assertEqual([entry['name'] for entry in result['cpu']], ['Alpha', 'mid', 'zeta'])

    def test_memory_is_the_top_six_by_working_set_and_includes_unreadable_cpu(self):
        rows = [('n%d' % i, i, None if i == 7 else 1, 100 * (i + 1)) for i in range(8)]
        result = update(self.tracker, pr=processes(1000, rows))[0]
        self.assertEqual([entry['name'] for entry in result['memory']], ['n7', 'n6', 'n5', 'n4', 'n3', 'n2'])
        self.assertEqual(result['memory'][0], {'name': 'n7', 'mem_mb': 800})

    def test_a_quiet_machine_is_an_empty_list_not_unknown(self):
        result = self.two_readings([('a', 1, 5, 10)], [('a', 1, 5, 10)])
        self.assertEqual(result['cpu'], [])

    def test_bookkeeping_entries_and_the_idle_placeholder_are_never_shown(self):
        hidden = ['Idle', 'System', 'Registry', 'Memory Compression', 'System Idle Process',
                  'MemCompression', 'Secure System', 'idle.exe']
        before = [(name, 100 + i, 0, 5000) for i, name in enumerate(hidden)] + [('real', 1, 0, 10)]
        after = [(name, 100 + i, 120, 5000) for i, name in enumerate(hidden)] + [('real', 1, 6, 10)]
        result = self.two_readings(before, after)
        self.assertEqual([entry['name'] for entry in result['cpu']], ['real'])
        self.assertEqual([entry['name'] for entry in result['memory']], ['real'])

    def test_a_new_program_counts_from_zero_and_one_that_left_counts_for_nothing(self):
        result = self.two_readings([('gone', 1, 50, 10), ('stays', 2, 0, 10)],
                                   [('stays', 2, 6, 10), ('fresh', 3, 12, 10)])
        self.assertEqual([(e['name'], e['percent']) for e in result['cpu']], [('fresh', 10.0), ('stays', 5.0)])

    def test_a_reused_process_id_is_a_new_program_not_a_negative_share(self):
        # Same id and name but less CPU time than before: the old one ended and a new one took the id.
        result = self.two_readings([('worker', 7, 500, 10)], [('worker', 7, 6, 10)])
        self.assertEqual(result['cpu'], [{'name': 'worker', 'percent': 5.0, 'mem_mb': 10}])

    def test_same_id_under_another_name_is_another_program(self):
        result = self.two_readings([('old', 7, 500, 10)], [('new', 7, 12, 10)])
        self.assertEqual([entry['name'] for entry in result['cpu']], ['new'])

    def test_unreadable_cpu_time_is_skipped_never_a_zero_or_a_lifetime_total(self):
        # Unreadable before, readable now: no difference can be taken. Unreadable now: not ranked.
        result = self.two_readings([('was', 1, None, 10), ('is', 2, 5, 10)], [('was', 1, 900, 10), ('is', 2, None, 10)])
        self.assertEqual(result['cpu'], [])
        self.assertEqual({entry['name'] for entry in result['memory']}, {'was', 'is'})

    def test_missing_working_set_leaves_the_memory_unknown(self):
        result = self.two_readings([('a', 1, 0, None)], [('a', 1, 6, None)])
        self.assertEqual(result['cpu'], [{'name': 'a', 'percent': 5.0, 'mem_mb': None}])
        self.assertEqual(result['memory'], [])

    def test_a_share_cannot_pass_one_hundred_percent(self):
        # Readings are not taken at one instant: a hair above the possible is noise and is capped...
        result = self.two_readings([('a', 1, 0, 1)], [('a', 1, 123, 1)])
        self.assertEqual(result['cpu'][0]['percent'], 100.0)
        # ...and several programs of one name cannot add up to more than the machine either.
        result = self.two_readings([('b', 1, 0, 1), ('b', 2, 0, 1)], [('b', 1, 100, 1), ('b', 2, 100, 1)])
        self.assertEqual(result['cpu'][0]['percent'], 100.0)

    def test_more_cpu_time_than_the_machine_has_is_not_a_new_program_but_a_missed_one(self):
        # 'old' lived for hours but was missing from the previous reading: its lifetime total is not
        # what it used in these 30 s, so it must not show up as a spike (or at all).
        result = self.two_readings([('stays', 2, 0, 10)], [('stays', 2, 6, 10), ('old', 3, 5000, 10)])
        self.assertEqual([entry['name'] for entry in result['cpu']], ['stays'])
        self.assertEqual({entry['name'] for entry in result['memory']}, {'stays', 'old'})

    def test_nothing_but_names_leaves_the_module(self):
        rows = [['Sierra Chart', 987654321, 0, 1024 * MIB],
                ['leaky', 987654322, 0, 5 * MIB, 'C:\\Users\\tony\\secret\\leaky.exe'],     # a row with extras is dropped
                ['quiet', 987654323, 0, 5 * MIB]]
        block = {'t': 1000 * TICKS, 'f': TICKS, 'n': 4, 'p': rows}
        self.tracker.update({'pr': block})
        later = {'t': 1030 * TICKS, 'f': TICKS, 'n': 4,
                 'p': [['Sierra Chart', 987654321, 12 * TICKS, 1024 * MIB], rows[1], ['quiet', 987654323, 0, 5 * MIB]]}
        result = self.tracker.update({'pr': later})[0]
        text = json.dumps(result)
        for secret in ('987654321', '987654322', 'secret', 'leaky', 'Users', 'tony'):
            self.assertNotIn(secret, text)
        self.assertEqual(set(result), {'cpu', 'memory', 'gpu'})
        for entry in result['cpu']:
            self.assertEqual(set(entry), {'name', 'percent', 'mem_mb'})
        for entry in result['memory']:
            self.assertEqual(set(entry), {'name', 'mem_mb'})

    def test_names_are_cleaned_before_merging(self):
        before = [('Tool.exe', 1, 0, 1), ('tool', 2, 0, 1), ('x' * 40, 3, 0, 1)]
        after = [('Tool.exe', 1, 3, 1), ('tool', 2, 3, 1), ('x' * 40, 3, 6, 1)]
        result = self.two_readings(before, after)
        self.assertEqual([(e['name'], e['percent']) for e in result['cpu']], [('Tool', 5.0), ('x' * 24, 5.0)])

    def test_two_readings_too_close_keep_the_older_baseline(self):
        update(self.tracker, pr=processes(1000, [('a', 1, 0, 1)]))
        close = update(self.tracker, pr=processes(1002, [('a', 1, 2, 1)]))[0]
        self.assertIsNone(close['cpu'])
        # 32 s after the FIRST reading, not 30 s after the second: 12 s of 32 * 4 = 9.375 %.
        later = update(self.tracker, pr=processes(1032, [('a', 1, 12, 1)]))[0]
        self.assertEqual(later['cpu'][0]['percent'], 9.4)

    def test_a_long_gap_or_a_clock_that_went_back_starts_again(self):
        update(self.tracker, pr=processes(1000, [('a', 1, 0, 1)]))
        self.assertIsNone(update(self.tracker, pr=processes(1000 + 600, [('a', 1, 300, 1)]))[0]['cpu'])
        self.assertEqual(update(self.tracker, pr=processes(1630, [('a', 1, 306, 1)]))[0]['cpu'][0]['percent'], 5.0)
        self.assertIsNone(update(self.tracker, pr=processes(10, [('a', 1, 400, 1)]))[0]['cpu'])
        self.assertEqual(update(self.tracker, pr=processes(40, [('a', 1, 406, 1)]))[0]['cpu'][0]['percent'], 5.0)

    def test_garbage_never_raises_and_is_never_a_reading(self):
        bad_rows = [[], ['only'], ['a', 1], ['a', 1, 2, 3, 4], 'text', 5, None, [None, 1, 1, 1], ['', 1, 1, 1],
                    ['a', -1, 1, 1], ['a', 'x', 1, 1], ['a', True, 1, 1], {'name': 'a'}]
        blocks = [None, [], 'text', 5, {}, {'p': 5}, {'t': 'x', 'f': 1, 'n': 4, 'p': [['a', 1, 1, 1]]},
                  {'t': 1, 'f': 0, 'n': 4, 'p': [['a', 1, 1, 1]]}, {'t': 1, 'f': 1, 'n': 0, 'p': [['a', 1, 1, 1]]},
                  {'t': math.nan, 'f': 1, 'n': 4, 'p': [['a', 1, 1, 1]]}, {'t': 1, 'f': 1, 'n': 4, 'p': bad_rows},
                  {'t': 1, 'f': 1, 'n': 4, 'p': []}, {'t': 1, 'f': 1, 'n': 4, 'p': [['a', 1, 1, 1]] * (MAX_ROWS + 1)}]
        for block in blocks:
            with self.subTest(block=repr(block)[:60]):
                self.assertEqual(RateTracker().update({'pr': block}), (None, None))
        for data in (None, [], 'text', 5, {'pr': None}):
            with self.subTest(data=data):
                self.assertEqual(RateTracker().update(data), (None, None))

    def test_bad_rows_beside_good_ones_are_ignored(self):
        block = processes(1000, [('good', 1, 0, 10)])
        block['p'] += [[], ['a', 1], None, ['bad', 'x', 1, 1]]
        result = RateTracker().update({'pr': block})[0]
        self.assertEqual(result['memory'], [{'name': 'good', 'mem_mb': 10}])

    def test_an_unreadable_counter_keeps_the_rest_of_its_row(self):
        for broken in (math.nan, math.inf, -5, True, 'x', None):
            with self.subTest(broken=broken):
                tracker = RateTracker()
                tracker.update({'pr': {'t': 1000 * TICKS, 'f': TICKS, 'n': 4, 'p': [['a', 1, broken, 8 * MIB]]}})
                later = {'t': 1030 * TICKS, 'f': TICKS, 'n': 4, 'p': [['a', 1, broken, 8 * MIB]]}
                result = tracker.update({'pr': later})[0]
                self.assertEqual(result['cpu'], [])
                self.assertEqual(result['memory'], [{'name': 'a', 'mem_mb': 8}])
        # An unreadable working set leaves the memory out of the list, not zero.
        result = RateTracker().update({'pr': {'t': TICKS, 'f': TICKS, 'n': 4, 'p': [['a', 1, 1, math.nan]]}})[0]
        self.assertEqual(result['memory'], [])

    def test_many_threads_may_report_at_once(self):
        errors = []

        def work(offset):
            try:
                for step in range(40):
                    self.tracker.update({'pr': processes(offset + step * 31, [('a', 1, step * 3, 10)])})
            except Exception as exc:     # pragma: no cover - only on a regression
                errors.append(exc)

        threads = [threading.Thread(target=work, args=(1000 * n,)) for n in range(6)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])


class GpuShareTests(unittest.TestCase):
    def setUp(self):
        self.tracker = RateTracker()
        self.names = [('dwm', 10, 0, 1), ('game', 20, 0, 1), ('chrome', 30, 0, 1), ('chrome', 31, 0, 1),
                      ('System', 4, 0, 1)]

    def second(self, before, after, window=30):
        update(self.tracker, pr=processes(1000, self.names), gp=gpu(1000, before))
        return update(self.tracker, pr=processes(1000 + window, self.names), gp=gpu(1000 + window, after))[0]['gpu']

    def test_first_reading_has_no_gpu_share(self):
        result = update(self.tracker, pr=processes(1000, self.names), gp=gpu(1000, [(10, LUID_A, 0, '3D', 5)]))[0]
        self.assertIsNone(result['gpu'])

    def test_share_is_the_engine_busy_time_over_the_window(self):
        # dwm kept the 3D engine busy 3 s of 30 s = 10 %; the game 15 s = 50 %.
        result = self.second([(10, LUID_A, 0, '3D', 100), (20, LUID_B, 0, '3D', 0)],
                             [(10, LUID_A, 0, '3D', 103), (20, LUID_B, 0, '3D', 15)])
        self.assertEqual(result, [{'name': 'game', 'percent': 50.0}, {'name': 'dwm', 'percent': 10.0}])

    def test_a_program_counts_as_its_busiest_engine_not_the_sum(self):
        result = self.second([(20, LUID_B, 0, '3D', 0), (20, LUID_B, 1, 'Compute_0', 0)],
                             [(20, LUID_B, 0, '3D', 3), (20, LUID_B, 1, 'Compute_0', 9)])
        self.assertEqual(result, [{'name': 'game', 'percent': 30.0}])

    def test_several_engines_of_one_type_add_up(self):
        result = self.second([(20, LUID_A, 0, '3D', 0), (20, LUID_A, 1, '3D', 0)],
                             [(20, LUID_A, 0, '3D', 3), (20, LUID_A, 1, '3D', 3)])
        self.assertEqual(result, [{'name': 'game', 'percent': 20.0}])

    def test_processes_with_one_name_add_up_on_a_gpu_and_the_busiest_gpu_wins(self):
        same = self.second([(30, LUID_A, 0, '3D', 0), (31, LUID_A, 0, '3D', 0)],
                           [(30, LUID_A, 0, '3D', 3), (31, LUID_A, 0, '3D', 3)])
        self.assertEqual(same, [{'name': 'chrome', 'percent': 20.0}])
        self.tracker.reset()
        apart = self.second([(30, LUID_A, 0, '3D', 0), (31, LUID_B, 0, '3D', 0)],
                            [(30, LUID_A, 0, '3D', 6), (31, LUID_B, 0, '3D', 3)])
        self.assertEqual(apart, [{'name': 'chrome', 'percent': 20.0}])

    def test_top_four_only_and_idle_programs_are_left_out(self):
        self.names = [('p%d' % i, 100 + i, 0, 1) for i in range(7)]
        before = [(100 + i, LUID_A, 0, '3D', 0) for i in range(7)]
        after = [(100 + i, LUID_A, 0, '3D', 3 * (i + 1) if i < 6 else 0) for i in range(7)]
        result = self.second(before, after)
        self.assertEqual([entry['name'] for entry in result], ['p5', 'p4', 'p3', 'p2'])

    def test_an_idle_gpu_is_an_empty_list_not_unknown(self):
        self.assertEqual(self.second([(10, LUID_A, 0, '3D', 5)], [(10, LUID_A, 0, '3D', 5)]), [])

    def test_share_cannot_pass_one_hundred_percent(self):
        self.assertEqual(self.second([(10, LUID_A, 0, '3D', 0)], [(10, LUID_A, 0, '3D', 31)])[0]['percent'], 100.0)

    def test_an_engine_busy_longer_than_the_window_is_not_a_new_engine_but_a_missed_one(self):
        result = self.second([(10, LUID_A, 0, '3D', 0)],
                             [(10, LUID_A, 0, '3D', 3), (20, LUID_B, 0, '3D', 90)])
        self.assertEqual(result, [{'name': 'dwm', 'percent': 10.0}])

    def test_programs_not_in_the_process_list_and_bookkeeping_are_skipped(self):
        result = self.second([(999, LUID_A, 0, '3D', 0), (4, LUID_A, 0, '3D', 0), (10, LUID_A, 0, '3D', 0)],
                             [(999, LUID_A, 0, '3D', 15), (4, LUID_A, 0, '3D', 15), (10, LUID_A, 0, '3D', 3)])
        self.assertEqual(result, [{'name': 'dwm', 'percent': 10.0}])

    def test_a_restarted_engine_counter_is_not_a_negative_share(self):
        result = self.second([(10, LUID_A, 0, '3D', 500)], [(10, LUID_A, 0, '3D', 3)])
        self.assertEqual(result, [{'name': 'dwm', 'percent': 10.0}])

    def test_counters_that_cannot_be_read_mean_unknown(self):
        bad_blocks = [None, 5, 'text', {}, {'t': FILETIME_BASE, 'p': []}, {'t': FILETIME_BASE, 'p': 'x'},
                      {'t': 'x', 'p': [['pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D', 1]]},
                      {'t': FILETIME_BASE, 'p': [['not an instance', 1], ['pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D', -1],
                                                 ['pid_1_luid_0x0_0x1_phys_0_eng_0_engtype_3D', math.nan], 5, None]}]
        for block in bad_blocks:
            with self.subTest(block=repr(block)[:60]):
                tracker = RateTracker()
                update(tracker, pr=processes(1000, self.names))
                result = tracker.update({'pr': processes(1030, self.names), 'gp': block})[0]
                self.assertIsNone(result['gpu'])
                self.assertIsNotNone(result['memory'])

    def test_no_process_list_means_no_names_and_so_no_gpu_shares(self):
        update(self.tracker, gp=gpu(1000, [(10, LUID_A, 0, '3D', 0)]))
        self.assertEqual(update(self.tracker, gp=gpu(1030, [(10, LUID_A, 0, '3D', 3)])), (None, None))

    def test_an_old_baseline_is_dropped(self):
        update(self.tracker, pr=processes(1000, self.names), gp=gpu(1000, [(10, LUID_A, 0, '3D', 0)]))
        result = update(self.tracker, pr=processes(1400, self.names), gp=gpu(1400, [(10, LUID_A, 0, '3D', 40)]))[0]
        self.assertIsNone(result['gpu'])


class NetworkSpeedTests(unittest.TestCase):
    def setUp(self):
        self.tracker = RateTracker()

    def speeds(self, before, after, window=30):
        update(self.tracker, net=network(1000, before))
        return update(self.tracker, net=network(1000 + window, after))[1]

    def test_first_reading_has_no_speed(self):
        self.assertEqual(update(self.tracker, net=network(1000, [('a', 10, 10)]))[1],
                         {'down_bps': None, 'up_bps': None})

    def test_speed_is_bits_per_second_from_the_byte_difference(self):
        # 3,750,000 bytes in 30 s is 125,000 B/s = 1,000,000 bit/s; 750,000 bytes up is 200,000 bit/s.
        result = self.speeds([('a', 1000, 2000)], [('a', 1000 + 3_750_000, 2000 + 750_000)])
        self.assertEqual(result, {'down_bps': 1_000_000, 'up_bps': 200_000})

    def test_adapters_add_up_and_a_real_zero_stays_zero(self):
        result = self.speeds([('a', 0, 0), ('b', 0, 0)], [('a', 375_000, 0), ('b', 375_000, 0)])
        self.assertEqual(result, {'down_bps': 200_000, 'up_bps': 0})

    def test_counters_beyond_32_bits_are_exact(self):
        big = 12_412_761_749
        result = self.speeds([('a', big, big)], [('a', big + 5 * 1024 ** 3, big)])
        self.assertEqual(result, {'down_bps': int(round(5 * 1024 ** 3 * 8 / 30)), 'up_bps': 0})

    def test_an_adapter_that_appeared_or_vanished_is_not_counted(self):
        result = self.speeds([('old', 100, 100), ('gone', 5, 5)], [('old', 100 + 375_000, 100), ('new', 10 ** 9, 10 ** 9)])
        self.assertEqual(result, {'down_bps': 100_000, 'up_bps': 0})

    def test_a_counter_that_went_back_is_unknown_for_that_adapter_only(self):
        result = self.speeds([('wifi', 9_000_000, 9_000_000), ('eth', 0, 0)], [('wifi', 1000, 1000), ('eth', 375_000, 0)])
        self.assertEqual(result, {'down_bps': 100_000, 'up_bps': 0})

    def test_when_every_counter_went_back_both_speeds_are_unknown(self):
        result = self.speeds([('a', 9_000_000, 9_000_000)], [('a', 10, 10)])
        self.assertEqual(result, {'down_bps': None, 'up_bps': None})

    def test_a_32_bit_looking_wrap_is_not_guessed(self):
        result = self.speeds([('a', 2 ** 32 - 1000, 2 ** 32 - 1000)], [('a', 500, 500)])
        self.assertEqual(result, {'down_bps': None, 'up_bps': None})

    def test_no_adapter_up_means_no_speed(self):
        self.assertEqual(self.speeds([], []), {'down_bps': None, 'up_bps': None})

    def test_an_impossible_speed_is_a_broken_counter_not_traffic(self):
        self.assertEqual(self.speeds([('a', 0, 0)], [('a', 10 ** 15, 0)]), {'down_bps': None, 'up_bps': None})

    def test_a_long_gap_starts_again(self):
        update(self.tracker, net=network(1000, [('a', 0, 0)]))
        self.assertEqual(update(self.tracker, net=network(1500, [('a', 10 ** 9, 0)]))[1],
                         {'down_bps': None, 'up_bps': None})

    def test_unreadable_blocks_are_none(self):
        for block in (None, 5, 'text', {}, {'t': 1, 'f': 1}, {'t': 1, 'f': 1, 'a': 'x'}, {'t': 1, 'f': 0, 'a': []},
                      {'t': math.nan, 'f': 1, 'a': []}):
            with self.subTest(block=block):
                self.assertIsNone(RateTracker().update({'net': block})[1])

    def test_bad_rows_beside_good_ones_are_ignored(self):
        block = network(1000, [('a', 1, 1)])
        block['a'] += [[], ['b'], [5, 1, 1], ['c', -1, 1], ['d', math.nan, 1], ['e', 'x', 1], None]
        self.tracker.update({'net': block})
        later = network(1030, [('a', 1 + 3_750_000, 1)])
        self.assertEqual(self.tracker.update({'net': later})[1], {'down_bps': 1_000_000, 'up_bps': 0})


class BatteryAndUptimeTests(unittest.TestCase):
    def test_on_ac_the_run_time_sentinel_and_charging_are_unknown(self):
        result = tablet_metrics.normalize_battery({'s': 2, 'p': 94, 'm': 71582788})
        self.assertEqual(result, {'percent': 94, 'charging': None, 'minutes': None, 'plugged': True})

    def test_on_battery_the_estimate_is_kept(self):
        result = tablet_metrics.normalize_battery({'s': 1, 'p': 80, 'm': 187})
        self.assertEqual(result, {'percent': 80, 'charging': False, 'minutes': 187, 'plugged': False})

    def test_charging_states(self):
        for status in (6, 7, 8, 9):
            with self.subTest(status=status):
                result = tablet_metrics.normalize_battery({'s': status, 'p': 50, 'm': 120})
                self.assertEqual(result, {'percent': 50, 'charging': True, 'minutes': None, 'plugged': True})
        self.assertEqual(tablet_metrics.normalize_battery({'s': 3, 'p': 100, 'm': 71582788}),
                         {'percent': 100, 'charging': False, 'minutes': None, 'plugged': True})
        for status in (4, 5):
            self.assertEqual(tablet_metrics.normalize_battery({'s': status, 'p': 9, 'm': 12}),
                             {'percent': 9, 'charging': False, 'minutes': 12, 'plugged': False})

    def test_unknown_status_stays_unknown(self):
        self.assertEqual(tablet_metrics.normalize_battery({'s': 10, 'p': 40, 'm': 50}),
                         {'percent': 40, 'charging': None, 'minutes': 50, 'plugged': None})
        self.assertEqual(tablet_metrics.normalize_battery({'p': 40}),
                         {'percent': 40, 'charging': None, 'minutes': None, 'plugged': None})

    def test_impossible_values_are_unknown(self):
        result = tablet_metrics.normalize_battery({'s': 1, 'p': 140, 'm': 0})
        self.assertEqual(result, {'percent': None, 'charging': False, 'minutes': None, 'plugged': False})
        self.assertIsNone(tablet_metrics.normalize_battery({'s': 1, 'p': 5, 'm': 10 ** 6})['minutes'])
        self.assertIsNone(tablet_metrics.normalize_battery({'s': 1, 'p': True, 'm': 5})['percent'])

    def test_no_battery_or_garbage_is_none(self):
        for value in (None, [], 'text', 5, {}, {'s': 'x', 'p': None}, {'s': True, 'p': math.nan}):
            with self.subTest(value=value):
                self.assertIsNone(tablet_metrics.normalize_battery(value))

    def test_uptime_is_whole_seconds_or_unknown(self):
        self.assertEqual(tablet_metrics.normalize_uptime(59082), 59082)
        self.assertEqual(tablet_metrics.normalize_uptime(59082.9), 59082)
        self.assertEqual(tablet_metrics.normalize_uptime(0), 0)
        for value in (None, -1, math.nan, math.inf, 'x', True, [], 10 ** 12):
            with self.subTest(value=value):
                self.assertIsNone(tablet_metrics.normalize_uptime(value))


def script_output(pr=None, net=None, gp=None, bat=None, up=None, temp=None):
    """What the PowerShell process prints: one JSON line and, on the MSI laptop, a T= line."""
    data = {'disks': [{'DeviceID': 'C:', 'VolumeName': 'Windows', 'Size': 1000, 'FreeSpace': 250}],
            'os': {'TotalVisibleMemorySize': 8000, 'FreePhysicalMemory': 2000},
            'cpu': [{'LoadPercentage': 40, 'NumberOfLogicalProcessors': 8}],
            'up': up, 'bat': bat, 'net': net, 'pr': pr, 'gp': gp}
    return json.dumps(data) + '\r\n' + ('T=%s\r\n' % temp if temp is not None else '')


def forbid_real_commands(case):
    """A unit test must never start PowerShell or nvidia-smi on this PC: fail loudly if it tries."""
    patcher = patch('token_tv.tablet_metrics.subprocess.run',
                    side_effect=AssertionError('a unit test tried to run a real command'))
    patcher.start()
    case.addCleanup(patcher.stop)


class CollectTests(unittest.TestCase):
    def setUp(self):
        forbid_real_commands(self)
        tablet_metrics.reset_state()
        self.addCleanup(tablet_metrics.reset_state)

    def readings(self):
        first = script_output(
            pr=processes(1000, [('worker', 10, 100, 300), ('Idle', 0, 0, 0)]), net=network(1000, [('a', 1000, 2000)]),
            gp=gpu(1000, [(10, LUID_A, 0, '3D', 1)]), bat={'s': 2, 'p': 94, 'm': 71582788}, up=3600, temp=60)
        second = script_output(
            pr=processes(1030, [('worker', 10, 112, 310), ('Idle', 0, 0, 0)]),
            net=network(1030, [('a', 1000 + 3_750_000, 2000 + 750_000)]),
            gp=gpu(1030, [(10, LUID_A, 0, '3D', 4)]), bat={'s': 1, 'p': 93, 'm': 200}, up=3630, temp=61)
        return first, second

    def test_new_keys_arrive_beside_the_old_ones_and_rates_need_two_calls(self):
        first, second = self.readings()
        with patch('token_tv.tablet_metrics._run', side_effect=[first, None, second, None]) as run:
            one, two = tablet_metrics.collect(), tablet_metrics.collect()
        self.assertEqual(run.call_count, 4)         # one PowerShell process and one nvidia-smi per call
        for key in ('cpu_percent', 'cpu_temp_c', 'memory', 'disks', 'gpus'):
            self.assertIn(key, one)
        self.assertEqual(one['cpu_percent'], 40)
        self.assertEqual(one['cpu_temp_c'], 60)
        self.assertEqual(one['uptime_s'], 3600)
        self.assertEqual(one['battery'], {'percent': 94, 'charging': None, 'minutes': None, 'plugged': True})
        self.assertEqual(one['network'], {'down_bps': None, 'up_bps': None})
        self.assertIsNone(one['processes']['cpu'])
        self.assertIsNone(one['processes']['gpu'])
        self.assertEqual(one['processes']['memory'], [{'name': 'worker', 'mem_mb': 300}])
        self.assertEqual(two['network'], {'down_bps': 1_000_000, 'up_bps': 200_000})
        self.assertEqual(two['processes']['cpu'], [{'name': 'worker', 'percent': 10.0, 'mem_mb': 310}])
        self.assertEqual(two['processes']['gpu'], [{'name': 'worker', 'percent': 10.0}])
        self.assertEqual(two['battery'], {'percent': 93, 'charging': False, 'minutes': 200, 'plugged': False})
        self.assertEqual(two['cpu_temp_c'], 61)

    def test_one_powershell_process_per_call(self):
        first, _ = self.readings()
        with patch('token_tv.tablet_metrics._run', side_effect=[first, None]) as run:
            tablet_metrics.collect()
        programs = [call.args[0][0] for call in run.call_args_list]
        self.assertEqual(sum(program.lower().endswith('powershell.exe') for program in programs), 1)
        encoded = run.call_args_list[0].args[0][-1]
        self.assertLess(len(encoded), 24000)         # CreateProcess allows 32,767 characters in all
        script = base64.b64decode(encoded).decode('utf-16le')
        self.assertIn('BelowNormal', script)
        self.assertIn('$item.Id -eq $PID', script)   # its own PowerShell is never listed

    def test_the_script_asks_for_names_and_counters_only(self):
        script = tablet_metrics._QUERY
        for forbidden in ('CommandLine', 'MainModule', 'MainWindowTitle', 'StartInfo', 'UserName', 'GetOwner',
                          '.Path', 'FileName', 'Get-WmiObject Win32', 'Invoke-WebRequest'):
            self.assertNotIn(forbidden, script)
        self.assertIsNone(re.search(r'Win32_Process\b', script))       # Win32_Processor (CPU load) is fine

    def test_uptime_is_taken_in_utc_so_a_clock_change_cannot_shift_it(self):
        self.assertIn('[DateTime]::UtcNow - $computer.LastBootUpTime.ToUniversalTime()', tablet_metrics._QUERY)

    def test_only_physical_adapters_that_are_up_are_asked_for(self):
        script = tablet_metrics._QUERY
        for needed in ("-ne 'Up'", "'Loopback'", "'Tunnel'", "'PCI'", "'USB'", 'PnpInstanceID'):
            self.assertIn(needed, script)

    def test_reset_state_forgets_the_previous_reading(self):
        first, second = self.readings()
        with patch('token_tv.tablet_metrics._run', side_effect=[first, None, second, None]):
            tablet_metrics.collect()
            tablet_metrics.reset_state()
            again = tablet_metrics.collect()
        self.assertIsNone(again['processes']['cpu'])
        self.assertEqual(again['network'], {'down_bps': None, 'up_bps': None})

    def test_the_result_is_plain_json(self):
        first, second = self.readings()
        with patch('token_tv.tablet_metrics._run', side_effect=[first, None, second, 'GPU A, 55, 27, 300, 8000']):
            tablet_metrics.collect()
            result = tablet_metrics.collect()
        self.assertEqual(json.loads(json.dumps(result, allow_nan=False)), result)

    def test_a_failed_script_leaves_every_new_key_unknown_and_the_old_ones_as_before(self):
        for output in (None, '', 'not json at all', '[1, 2]', '{"pr": 5}\r\n'):
            with self.subTest(output=output):
                with patch('token_tv.tablet_metrics._run', side_effect=[output, None]):
                    result = tablet_metrics.collect()
                self.assertIsNone(result['processes'])
                self.assertIsNone(result['network'])
                self.assertIsNone(result['battery'])
                self.assertIsNone(result['uptime_s'])
                self.assertIsNone(result['cpu_percent'])
                self.assertEqual((result['disks'], result['gpus']), ([], []))

    def test_the_temperature_line_is_validated(self):
        for line, expected in (('T=73', 73), ('T=5', None), ('T=300', None), ('T=hot', None), ('X=73', None)):
            with self.subTest(line=line):
                output = script_output() + line + '\r\n'
                with patch('token_tv.tablet_metrics._run', side_effect=[output, None]):
                    self.assertEqual(tablet_metrics.collect()['cpu_temp_c'], expected)
        with patch('token_tv.tablet_metrics._run', side_effect=[script_output(), None]):
            self.assertIsNone(tablet_metrics.collect()['cpu_temp_c'])

    def test_a_sensor_that_hangs_does_not_hide_what_was_already_printed(self):
        printed = script_output(pr=processes(1000, [('worker', 10, 100, 300)]), up=77).encode()
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args[0])
            if len(calls) == 1:
                raise subprocess.TimeoutExpired(args, kwargs['timeout'], output=printed)
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])

        with patch('token_tv.tablet_metrics.subprocess.run', side_effect=fake_run):
            result = tablet_metrics.collect()
        self.assertEqual(result['disks'], [{'name': 'C:', 'total': 1000, 'free': 250}])
        self.assertEqual(result['uptime_s'], 77)
        self.assertEqual(result['processes']['memory'], [{'name': 'worker', 'mem_mb': 300}])
        self.assertIsNone(result['cpu_temp_c'])

    def test_a_failing_exit_code_after_the_readings_were_printed_keeps_them(self):
        # PowerShell exits with 1 when the last statement swallowed an error (a missing sensor).
        printed = script_output(pr=processes(1000, [('worker', 10, 100, 300)]), up=77).encode()

        def fake_run(args, **kwargs):
            if 'nvidia' in args[0]:
                raise subprocess.CalledProcessError(1, args, output=b'GPU A, 55, 27, 300, 8000')
            raise subprocess.CalledProcessError(1, args, output=printed)

        with patch('token_tv.tablet_metrics.subprocess.run', side_effect=fake_run):
            result = tablet_metrics.collect()
        self.assertEqual(result['uptime_s'], 77)
        self.assertEqual(result['disks'], [{'name': 'C:', 'total': 1000, 'free': 250}])
        self.assertEqual(result['gpus'], [])          # a failing nvidia-smi is still just unknown

    def test_the_script_ends_with_an_explicit_success(self):
        self.assertTrue(tablet_metrics._QUERY.rstrip().endswith('exit 0'))

    def test_stray_lines_around_the_readings_are_ignored(self):
        output = 'WARNING: something unexpected\r\n' + script_output(up=5, temp=61) + 'trailing words\r\n'
        with patch('token_tv.tablet_metrics._run', side_effect=[output, None]):
            result = tablet_metrics.collect()
        self.assertEqual((result['uptime_s'], result['cpu_temp_c']), (5, 61))

    def test_a_timeout_with_nothing_printed_is_a_failed_reading(self):
        with patch('token_tv.tablet_metrics.subprocess.run', side_effect=subprocess.TimeoutExpired('powershell', 20)):
            result = tablet_metrics.collect()
        self.assertIsNone(result['processes'])
        self.assertEqual(result['disks'], [])

    def test_history_is_exported_from_the_collector_module(self):
        self.assertIs(tablet_metrics.MetricsHistory, tablet_history.MetricsHistory)


class HistoryTests(unittest.TestCase):
    def system(self, **changes):
        base = {'cpu_percent': 40.0, 'cpu_temp_c': 59, 'memory': {'total': 8000, 'free': 2000},
                'gpus': [{'percent': 12, 'temp_c': 50.79}], 'network': {'down_bps': 1_000_000, 'up_bps': 200_000}}
        base.update(changes)
        return base

    def test_defaults_and_payload_shape(self):
        history = MetricsHistory()
        self.assertEqual(history.payload(), {'step': 30, 'cpu': [], 'gpu': [], 'cpu_temp': [], 'gpu_temp': [],
                                             'memory': [], 'down': [], 'up': []})
        self.assertEqual((history.step, history.keep), (30, 120))

    def test_step_and_size_are_kept_sane(self):
        small = MetricsHistory(step=0, keep=0)
        self.assertEqual((small.step, small.keep), (1, 1))
        small.add(self.system())
        small.add(self.system(cpu_percent=5))
        self.assertEqual(small.payload()['cpu'], [5.0])
        odd = MetricsHistory(step=30.9, keep=5.7)
        self.assertEqual((odd.step, odd.keep, odd.payload()['step']), (30, 5, 30))

    def test_each_series_comes_from_its_field(self):
        history = MetricsHistory()
        history.add(self.system())
        self.assertEqual(history.payload(), {
            'step': 30, 'cpu': [40.0], 'gpu': [12.0], 'cpu_temp': [59.0], 'gpu_temp': [50.8], 'memory': [75.0],
            'down': [1_000_000.0], 'up': [200_000.0]})

    def test_several_gpus_report_the_busiest_and_the_hottest(self):
        history = MetricsHistory()
        history.add(self.system(gpus=[{'percent': 5, 'temp_c': 70}, {'percent': 30, 'temp_c': 50}, {'percent': None}]))
        self.assertEqual((history.payload()['gpu'], history.payload()['gpu_temp']), ([30.0], [70.0]))

    def test_values_are_rounded_to_one_decimal_and_oldest_comes_first(self):
        history = MetricsHistory()
        for value in (10.04, 20.06, 33.349):
            history.add(self.system(cpu_percent=value))
        self.assertEqual(history.payload()['cpu'], [10.0, 20.1, 33.3])

    def test_the_ring_keeps_only_the_newest(self):
        history = MetricsHistory(keep=120)
        for number in range(150):
            history.add(self.system(cpu_percent=number % 100))
        series = history.payload()['cpu']
        self.assertEqual(len(series), 120)
        self.assertEqual(series[-1], 49.0)           # reading 149
        self.assertEqual(series[0], 30.0)            # reading 30: the first 30 were dropped
        for name in tablet_history.SERIES:
            self.assertEqual(len(history.payload()[name]), 120)

    def test_unknown_is_a_gap_never_a_zero(self):
        history = MetricsHistory()
        history.add({})
        history.add(self.system(cpu_percent=None, cpu_temp_c=None, memory=None, gpus=[], network=None))
        history.add(self.system(network={'down_bps': None, 'up_bps': 5}))
        payload = history.payload()
        self.assertEqual(payload['cpu'], [None, None, 40.0])
        self.assertEqual(payload['gpu'][1], None)
        self.assertEqual(payload['gpu_temp'][1], None)
        self.assertEqual(payload['memory'][:2], [None, None])
        self.assertEqual(payload['down'], [None, None, None])
        self.assertEqual(payload['up'], [None, None, 5.0])

    def test_a_failed_collection_is_a_gap_and_garbage_cannot_break_the_loop(self):
        history = MetricsHistory()
        for value in (None, 'text', 5, [], {'cpu_percent': 'x', 'gpus': 'x', 'memory': 'x', 'network': 'x'},
                      {'gpus': [None, 5, 'x']}):
            history.add(value)
        payload = history.payload()
        self.assertEqual(len(payload['cpu']), 6)
        for name in tablet_history.SERIES:
            self.assertEqual(payload[name], [None] * 6)

    def test_impossible_values_are_gaps(self):
        history = MetricsHistory()
        bad_numbers = (math.nan, math.inf, -1, True, '5', 101)
        for value in bad_numbers:
            history.add(self.system(cpu_percent=value, cpu_temp_c=value, network={'down_bps': value, 'up_bps': value}))
        payload = history.payload()
        self.assertEqual(payload['cpu'], [None] * len(bad_numbers))
        self.assertEqual(payload['down'][:5], [None] * 5)          # 101 bit/s is a perfectly good speed
        bad_memory = (None, {}, {'total': 100}, {'total': math.nan, 'free': 1}, {'total': math.inf, 'free': 1},
                      {'total': -1, 'free': 1}, {'total': True, 'free': 1}, {'total': '5', 'free': 1},
                      {'total': 0, 'free': 0}, {'total': 100, 'free': 200}, {'total': 100, 'free': -1})
        history = MetricsHistory()
        for memory in bad_memory:
            history.add(self.system(memory=memory, cpu_temp_c=500))
        self.assertEqual(history.payload()['memory'], [None] * len(bad_memory))
        self.assertEqual(history.payload()['cpu_temp'], [None] * len(bad_memory))

    def test_missed_beats_become_gaps_but_a_slow_loop_does_not(self):
        now = [0.0]
        history = MetricsHistory(clock=lambda: now[0])
        for moment in (0, 33, 66, 100):                  # a 30 s loop plus collection time: no gaps
            now[0] = moment
            history.add(self.system(cpu_percent=1))
        self.assertEqual(len(history.payload()['cpu']), 4)
        now[0] = 100 + 95                                 # about three beats later: two missed
        history.add(self.system(cpu_percent=2))
        self.assertEqual(history.payload()['cpu'], [1.0, 1.0, 1.0, 1.0, None, None, 2.0])

    def test_a_long_stall_cannot_grow_the_ring_past_its_size(self):
        now = [0.0]
        history = MetricsHistory(keep=10, clock=lambda: now[0])
        history.add(self.system())
        now[0] = 36000
        history.add(self.system(cpu_percent=7))
        series = history.payload()['cpu']
        self.assertEqual(len(series), 10)
        self.assertEqual(series[-1], 7.0)
        self.assertEqual(series[:-1], [None] * 9)

    def test_payload_is_a_copy(self):
        history = MetricsHistory()
        history.add(self.system())
        payload = history.payload()
        payload['cpu'].append(99)
        payload['step'] = 1
        self.assertEqual(history.payload()['cpu'], [40.0])
        self.assertEqual(history.payload()['step'], 30)

    def test_it_takes_the_real_collector_result(self):
        forbid_real_commands(self)
        tablet_metrics.reset_state()
        output = script_output(pr=processes(1000, [('a', 1, 0, 5)]), net=network(1000, [('x', 0, 0)]), temp=58)
        with patch('token_tv.tablet_metrics._run', side_effect=[output, 'GPU A, 55, 27, 300, 8000']):
            result = tablet_metrics.collect()
        history = MetricsHistory()
        history.add(result)
        payload = history.payload()
        self.assertEqual((payload['cpu'], payload['gpu'], payload['gpu_temp'], payload['cpu_temp'], payload['memory']),
                         ([40.0], [27.0], [55.0], [58.0], [75.0]))
        self.assertEqual((payload['down'], payload['up']), ([None], [None]))     # first call: no speed yet

    def test_many_threads_can_add_and_read_at_once(self):
        history = MetricsHistory()
        failures = []

        def writer(seed):
            for number in range(300):
                history.add(self.system(cpu_percent=(seed * 7 + number) % 100))

        def reader():
            for _ in range(300):
                payload = history.payload()
                lengths = {len(value) for name, value in payload.items() if name != 'step'}
                if len(lengths) != 1 or max(lengths) > 120:
                    failures.append(lengths)

        threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)] + \
                  [threading.Thread(target=reader) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(failures, [])
        self.assertEqual(len(history.payload()['cpu']), 120)


if __name__ == '__main__':
    unittest.main()
