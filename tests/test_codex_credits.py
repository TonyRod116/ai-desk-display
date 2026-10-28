import unittest
from unittest.mock import patch

from token_tv.codex_resets import quota_record
from token_tv.credits import exhausted_credits, parse_balance, format_balance
from token_tv.local_usage import local_row, expire_official_quota


def response(balance='123.50', used=100):
    return {'ordinaryUsageAllowed': False, 'rateLimits': {'limitId': 'codex',
        'credits': {'balance': balance, 'hasCredits': True, 'unlimited': False},
        'primary': {'usedPercent': used, 'windowDurationMins': 10080, 'resetsAt': 2000},
        'secondary': None}}


def row(data=None):
    record = quota_record(response() if data is None else data, '/example', now=1000)
    record['identity_verified'] = True
    result = local_row({'key': 'codex', 'alias': 'CODEX', 'provider': 'codex'}, record, now=1000)
    result['identity_verified'] = True
    return result


class CreditTests(unittest.TestCase):
    def test_valid_exhausted_week_shows_credits_not_resets(self):
        data = response()
        data['rateLimitResetCredits'] = {'availableCount': 3}
        self.assertEqual(exhausted_credits(row(data)), '123.5')

    def test_unknown_zero_negative_and_invalid_balance(self):
        self.assertEqual(exhausted_credits(row(response('0'))), '0')
        self.assertEqual(exhausted_credits(row(response('-3.25'))), '-3.25')
        for value in (None, True, 'NaN', '1e5', 'oops', '1234567890123456789012345'):
            self.assertEqual(exhausted_credits(row(response(value))), '?')
        self.assertEqual(parse_balance(' 1.500 '), '1.5')
        self.assertEqual(parse_balance('12345.1234560000'), '12345.123456')
        self.assertEqual(format_balance('12345.123456'), '12345.12')
        self.assertEqual(format_balance('0.001'), '<0.01')
        self.assertEqual(format_balance('100'), '100')
        self.assertEqual(format_balance('-0.001'), '-<0.01')

    def test_week_not_exhausted_or_identity_unverified_is_not_credit_mode(self):
        data = response(used=99)
        data['ordinaryUsageAllowed'] = True
        self.assertIsNone(exhausted_credits(row(data)))
        r = row(); r['identity_verified'] = False
        self.assertIsNone(exhausted_credits(r))

    def test_failure_or_old_reading_cannot_show_previous_balance(self):
        r = row(); expire_official_quota(r, now=1181)
        self.assertIsNone(exhausted_credits(r))
        self.assertNotIn('credits_balance', r)
        r = row(); r['status'] = 'quota_unavailable'
        self.assertIsNone(exhausted_credits(r))

    def test_credit_balance_only_from_codex_bucket(self):
        d = response(); d['rateLimitsByLimitId'] = {'codex': d['rateLimits'],
            'other': {'credits': {'balance': '999'}}}
        self.assertEqual(exhausted_credits(row(d)), '123.5')
        d['rateLimitsByLimitId']['codex']['credits'] = None
        self.assertEqual(exhausted_credits(row(d)), '?')
