"""Prepare common French calendar expressions for speech, without changing display text."""
import datetime
import re

_SMALL = ('zéro un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze quinze seize').split()
_TENS = {20: 'vingt', 30: 'trente', 40: 'quarante', 50: 'cinquante', 60: 'soixante'}
_MONTHS = ('janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet', 'août', 'septembre', 'octobre', 'novembre', 'décembre')


def _number(n):
    if n <= 16:
        return _SMALL[n]
    if n < 20:
        return 'dix-' + _number(n - 10)
    if n < 70:
        tens, unit = divmod(n, 10)
        return _TENS[tens * 10] + (('-et-un' if unit == 1 else '-' + _number(unit)) if unit else '')
    if n < 80:
        return 'soixante-' + ('et-onze' if n == 71 else _number(n - 60))
    if n < 100:
        return 'quatre-vingt' + ('s' if n == 80 else '-' + _number(n - 80))
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        return ('' if hundreds == 1 else _number(hundreds) + ' ') + 'cent' + ('s' if hundreds > 1 and not rest else '') + (' ' + _number(rest) if rest else '')
    thousands, rest = divmod(n, 1000)
    return ('' if thousands == 1 else _number(thousands) + ' ') + 'mille' + (' ' + _number(rest) if rest else '')


def normalize_french(text):
    def date(match):
        day, month, year = map(int, match.groups())
        year = year + 2000 if year < 100 else year
        try:
            datetime.date(year, month, day)
        except ValueError:
            return match.group()
        return ('premier' if day == 1 else _number(day)) + ' ' + _MONTHS[month - 1] + ' ' + _number(year)

    def named_date(match):
        day = int(match.group(1))
        month = match.group(2)
        if not 1 <= day <= 31:
            return match.group()
        return ('premier' if day == 1 else _number(day)) + ' ' + month

    def time(match):
        hour = int(match.group(1))
        minutes = int(match.group(2) or 0)
        if hour > 23 or minutes > 59:
            return match.group()
        return ('une' if hour == 1 else _number(hour)) + (' heure' if hour == 1 else ' heures') + (' ' + _number(minutes) if minutes else '')

    text = re.sub(r'(?<![\d/])(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})(?![\d/])', date, text)
    text = re.sub(r'(?<!\w)(\d{1,2})\s+(' + '|'.join(_MONTHS) + r')\b', named_date, text, flags=re.IGNORECASE)
    return re.sub(r'(?<!\w)(\d{1,2})\s*(?:h|:)(?:\s*(\d{1,2}))?(?![\w:])', time, text, flags=re.IGNORECASE)
