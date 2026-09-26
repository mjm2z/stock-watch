"""UTC calendar arithmetic shared by collection, replay, and paper exits."""
from datetime import datetime, timedelta, timezone
import calendar

TIMEFRAMES = ('1Min', '5Min', '15Min', '1Hour', '4Hour', '1Day', '1Week', '1Month')
MINUTES = {'1Min':1, '5Min':5, '15Min':15, '1Hour':60, '4Hour':240, '1Day':1440, '1Week':10080}


def months(at, count):
    year, month = divmod(at.year * 12 + at.month - 1 + count, 12)
    month += 1
    return at.replace(year=year, month=month, day=min(at.day, calendar.monthrange(year, month)[1]))


def advance(at, timeframe, count=1):
    if timeframe not in TIMEFRAMES: raise ValueError('Unsupported decision timeframe')
    return months(at, count) if timeframe == '1Month' else at + timedelta(minutes=MINUTES[timeframe]*count)


def boundary(at, timeframe):
    at = at.astimezone(timezone.utc)
    if timeframe == '1Month': return at.replace(day=1,hour=0,minute=0,second=0,microsecond=0)
    if timeframe == '1Week': return (at-timedelta(days=at.weekday())).replace(hour=0,minute=0,second=0,microsecond=0)
    minutes = MINUTES[timeframe]
    seconds = int(at.timestamp()) // (minutes*60) * minutes*60
    return datetime.fromtimestamp(seconds,timezone.utc)


def deadline(at, count, unit):
    if unit == 'months': return months(at,count)
    units = {'minutes':60, 'hours':3600, 'days':86400, 'weeks':604800}
    if unit not in units: raise ValueError('Unsupported holding unit')
    return at + timedelta(seconds=count*units[unit])


def next_review(now, timeframe):
    day=now.replace(hour=0,minute=15,second=0,microsecond=0)
    if timeframe in ('1Week','1Month'):
        return months(day.replace(day=1),1)
    if timeframe == '1Day':
        target=day+timedelta(days=(7-day.weekday())%7)
        return target if target>now else target+timedelta(days=7)
    return day if day>now else day+timedelta(days=1)


def evidence_expiry(cutoff, timeframe):
    if timeframe in ('1Week','1Month'): return next_review(cutoff,timeframe)+timedelta(hours=48)
    return cutoff+timedelta(days=8) if timeframe=='1Day' else cutoff+timedelta(hours=36)
