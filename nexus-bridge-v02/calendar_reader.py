"""Read-only Google Calendar access; credentials remain in Windows keyring."""
import datetime
import json
import threading
import re
import unicodedata
from zoneinfo import ZoneInfo

_lock = threading.Lock()

class CalendarUnavailable(Exception):
    pass

PARIS = ZoneInfo('Europe/Paris')

def _service():
    import keyring
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from calendar_auth import ACCOUNT, SCOPES, SERVICE
    if keyring.get_keyring().__class__.__module__ != 'keyring.backends.Windows':
        raise CalendarUnavailable()
    secret = keyring.get_password(SERVICE, ACCOUNT)
    if not secret:
        raise CalendarUnavailable()
    creds = Credentials.from_authorized_user_info(json.loads(secret), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        keyring.set_password(SERVICE, ACCOUNT, creds.to_json())
    if not creds.valid:
        raise CalendarUnavailable()
    return build('calendar', 'v3', credentials=creds, cache_discovery=False)

def day_bounds(day):
    if not isinstance(day, datetime.date) or isinstance(day, datetime.datetime):
        raise ValueError('invalid_date')
    start = datetime.datetime.combine(day, datetime.time.min, tzinfo=PARIS)
    end = datetime.datetime.combine(day + datetime.timedelta(days=1), datetime.time.min, tzinfo=PARIS)
    return start, end

def _instant(value):
    if 'dateTime' in value:
        dt = datetime.datetime.fromisoformat(value['dateTime'].replace('Z', '+00:00'))
        if dt.tzinfo is None:
            raise ValueError('missing_timezone')
        return dt.astimezone(PARIS)
    return day_bounds(datetime.date.fromisoformat(value['date']))[0]

def events_between(start, end):
    if start.tzinfo is None or end.tzinfo is None or end <= start or end - start > datetime.timedelta(days=32):
        raise ValueError('invalid_range')
    try:
        with _lock:
            service = _service()
            items, token = [], None
            for _ in range(4):
                params = dict(calendarId='primary', timeMin=start.isoformat(), timeMax=end.isoformat(),
                              maxResults=250, singleEvents=True, orderBy='startTime', timeZone='Europe/Paris',
                              fields='items(summary,start,end,status,transparency),nextPageToken')
                if token: params['pageToken'] = token
                page = service.events().list(**params).execute(num_retries=0)
                items.extend(page.get('items', []))
                token = page.get('nextPageToken')
                if not token: break
            if token: raise CalendarUnavailable()
        result = []
        for item in items:
            if item.get('status') == 'cancelled': continue
            first, last = _instant(item['start']), _instant(item['end'])
            if last <= first: raise CalendarUnavailable()
            title = item.get('summary') or '(sans titre)'
            if not isinstance(title, str): title = '(sans titre)'
            result.append({'title': ' '.join(title.split())[:160], 'start': first, 'end': last,
                           'all_day': 'date' in item['start'], 'busy': item.get('transparency') != 'transparent'})
        return result
    except Exception:
        raise CalendarUnavailable('calendar_unavailable') from None

def free_slots(events, start, end, minimum_minutes=30):
    occupied = sorted((max(e['start'], start), min(e['end'], end)) for e in events if e['busy'] and e['start'] < end and e['end'] > start)
    slots, cursor = [], start
    for first, last in occupied:
        if first > cursor and (first - cursor).total_seconds() >= minimum_minutes * 60: slots.append((cursor, first))
        cursor = max(cursor, last)
    if (end - cursor).total_seconds() >= minimum_minutes * 60: slots.append((cursor, end))
    return slots

def interpret(question, now=None, fetch=None, extra_events=None):
    text = ''.join(c for c in unicodedata.normalize('NFKD', question.casefold()) if not unicodedata.combining(c))
    if not re.search(r'\b(agenda|calendrier|familywall|planning|programme|journee|rendez.vous|disponibilit\w*|disponible|dispo|libre|evenements?)\b', text): return None
    today = (now or datetime.datetime.now(PARIS)).astimezone(PARIS).date()
    day = today
    named = None
    explicit = re.search(r'\b(20\d{2}-\d{2}-\d{2})\b', text)
    if re.search(r'\b\d{1,2}[/.]\d{1,2}', text):
        return 'Précisez la date en disant par exemple 19 novembre ou au format année-mois-jour.'
    if explicit:
        try: day = datetime.date.fromisoformat(explicit.group(1))
        except ValueError: return 'Date invalide. Donnez une date au format année-mois-jour.'
    elif (named := re.search(r'\b(\d{1,2})\s+(janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre)(?:\s+(20\d{2}))?\b', text)):
        months = ('janvier','fevrier','mars','avril','mai','juin','juillet','aout','septembre','octobre','novembre','decembre')
        try: day = datetime.date(int(named.group(3) or today.year), months.index(named.group(2)) + 1, int(named.group(1)))
        except ValueError: return 'Date invalide. Donnez une date valable.'
    elif 'apres-demain' in text or 'apres demain' in text: day += datetime.timedelta(days=2)
    elif 'demain' in text: day += datetime.timedelta(days=1)
    else:
        weekdays = ('lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche')
        for index, name in enumerate(weekdays):
            if re.search(r'\b' + name + r'\b', text):
                delta = (index - today.weekday()) % 7
                if delta == 0 and ('prochain' in text or 'prochaine' in text): delta = 7
                day += datetime.timedelta(days=delta)
                break
    available = bool(re.search(r'\b(disponibilit\w*|disponible|dispo|libre)\b', text))
    week = ('semaine' in text or 'hebdomadaire' in text) and not explicit and not named
    if week:
        day = today - datetime.timedelta(days=today.weekday()) + datetime.timedelta(days=7 if 'prochaine' in text or 'prochain' in text else 0)
    if available and week:
        return 'Précisez une journée pour consulter les disponibilités entre 9 heures et 18 heures.'
    start, end = day_bounds(day)
    if week: end = day_bounds(day + datetime.timedelta(days=7))[0]
    if not week and day == today and not available and not any(x in text for x in ('aujourd', 'demain', 'journee', 'programme')) and not explicit and not named and not any(x in text for x in ('lundi','mardi','mercredi','jeudi','vendredi','samedi','dimanche')):
        start = now.astimezone(PARIS) if now else datetime.datetime.now(PARIS)
        end = start + datetime.timedelta(days=7)
    events = (fetch or events_between)(start, end)
    if extra_events:
        seen = {(e['title'].casefold(), e['start'], e['end']) for e in events}
        for e in extra_events:
            key = (e['title'].casefold(), e['start'], e['end'])
            if key not in seen and e['start'] < end and e['end'] > start:
                events.append(e); seen.add(key)
        events.sort(key=lambda e: e['start'])
    if available:
        work_start = datetime.datetime.combine(day, datetime.time(9), tzinfo=PARIS)
        work_end = datetime.datetime.combine(day, datetime.time(18), tzinfo=PARIS)
        if day == today: work_start = max(work_start, (now or datetime.datetime.now(PARIS)).astimezone(PARIS))
        if work_start >= work_end: return 'Aucun créneau restant entre 9 heures et 18 heures aujourd’hui.'
        slots = free_slots(events, work_start, work_end)
        if not slots: return 'Aucun créneau libre de 30 minutes entre 9 heures et 18 heures dans les agendas consultés.'
        return ('Créneaux libres dans les agendas consultés, le ' + day.strftime('%d/%m') + ' : ' + '; '.join(a.strftime('%Hh%M') + ' à ' + b.strftime('%Hh%M') for a,b in slots[:4]) + ('. Autres créneaux disponibles.' if len(slots)>4 else '.'))
    if not events: return 'Aucun événement trouvé pour cette période dans les agendas consultés.'
    parts = [(e['start'].strftime('%d/%m') + (' toute la journée' if e['all_day'] else ' à ' + e['start'].strftime('%Hh%M')) + ' : ' + e['title']) for e in events[:4]]
    return ('Agendas consultés : ' + '; '.join(parts) + ('. D’autres événements sont prévus.' if len(events)>4 else '.'))[:500]

def plan(question):
    bounds = []
    response = interpret(question, fetch=lambda start, end: bounds.append((start, end)) or [])
    if not bounds:
        return {'calendar': False, 'message': response}
    start, end = bounds[0]
    return {'calendar': True, 'start': start.isoformat(), 'end': end.isoformat()}

def upcoming(now=None, days=7, limit=10):
    if not isinstance(days, int) or not 1 <= days <= 31 or not isinstance(limit, int) or not 1 <= limit <= 10:
        raise ValueError('invalid_range')
    start = now or datetime.datetime.now(datetime.timezone.utc)
    if start.tzinfo is None:
        raise ValueError('timezone_required')
    try:
        import keyring
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from calendar_auth import ACCOUNT, SCOPES, SERVICE
        with _lock:
            backend = keyring.get_keyring()
            if backend.__class__.__module__ != 'keyring.backends.Windows':
                raise CalendarUnavailable()
            secret = keyring.get_password(SERVICE, ACCOUNT)
            if not secret:
                raise CalendarUnavailable()
            credentials = Credentials.from_authorized_user_info(json.loads(secret), SCOPES)
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                keyring.set_password(SERVICE, ACCOUNT, credentials.to_json())
            if not credentials.valid:
                raise CalendarUnavailable()
            end = start + datetime.timedelta(days=days)
            service = build('calendar', 'v3', credentials=credentials, cache_discovery=False)
            result = service.events().list(calendarId='primary', timeMin=start.isoformat(), timeMax=end.isoformat(),
                                           maxResults=limit, singleEvents=True, orderBy='startTime').execute(num_retries=0)
        events = []
        for event in result.get('items', [])[:limit]:
            start_value = event.get('start', {})
            time_value = start_value.get('dateTime') or start_value.get('date')
            if not isinstance(time_value, str) or len(time_value) > 64:
                continue
            title = event.get('summary') or '(sans titre)'
            if not isinstance(title, str):
                title = '(sans titre)'
            events.append({'title': ' '.join(title.split())[:160], 'start': time_value})
        return events
    except Exception:
        raise CalendarUnavailable('calendar_unavailable') from None
