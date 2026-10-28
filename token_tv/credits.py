"""Codex's extra usage credits are separate from saved weekly reset credits."""
from decimal import Decimal, InvalidOperation, ROUND_DOWN


def parse_balance(value):
    """Accept only a bounded plain decimal string from the official response."""
    if not isinstance(value, str) or not 1 <= len(value) <= 24:
        return None
    text = value.strip()
    if not text or any(c not in '0123456789.-' for c in text):
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    if not amount.is_finite() or abs(amount) > Decimal('1000000000') or amount.normalize().as_tuple().exponent < -10:
        return None
    result = format(amount, 'f')
    if '.' in result:
        result = result.rstrip('0').rstrip('.')
    return '0' if Decimal(result) == 0 else result


def exhausted_credits(row):
    """Return the balance label only for a confirmed, fresh, exhausted Codex week."""
    if (row.get('provider') != 'codex' or row.get('quota_origin') != 'codex_official_cli'
            or row.get('identity_verified') is not True or row.get('status') != 'ok'):
        return None
    if not any(w.get('label') == 'WEEK' and w.get('used_percent') == 100
               for w in row.get('windows', [])):
        return None
    return parse_balance(row.get('credits_balance')) or '?'


def format_balance(balance):
    """Keep the display legible without rounding a tiny balance up to zero."""
    if balance == '?':
        return balance
    amount = Decimal(balance)
    if amount and abs(amount) < Decimal('0.01'):
        return '-<0.01' if amount < 0 else '<0.01'
    displayed = amount.quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    text = format(displayed, 'f').rstrip('0').rstrip('.')
    return text if text and text != '-0' else '0'
