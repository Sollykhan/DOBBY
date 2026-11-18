import datetime
import unittest
from unittest.mock import Mock, patch
import calendar_reader

class CalendarReaderTests(unittest.TestCase):
    def test_readonly_primary_upcoming_and_no_extra_event_fields(self):
        import keyring
        from google.oauth2.credentials import Credentials
        import googleapiclient.discovery
        class WindowsBackend: pass
        WindowsBackend.__module__ = 'keyring.backends.Windows'
        creds = Mock(valid=True, expired=False)
        service = Mock()
        service.events.return_value.list.return_value.execute.return_value = {'items': [
            {'summary':'Rendez-vous test', 'start':{'dateTime':'2026-11-17T12:00:00+01:00'}, 'description':'privé', 'id':'secret-id'}]}
        now = datetime.datetime(2026, 11, 17, tzinfo=datetime.timezone.utc)
        with patch.object(keyring, 'get_keyring', return_value=WindowsBackend()), \
             patch.object(keyring, 'get_password', return_value='{}'), \
             patch.object(Credentials, 'from_authorized_user_info', return_value=creds), \
             patch.object(googleapiclient.discovery, 'build', return_value=service):
            result = calendar_reader.upcoming(now=now)
        self.assertEqual(result, [{'title':'Rendez-vous test','start':'2026-11-17T12:00:00+01:00'}])
        args = service.events.return_value.list.call_args.kwargs
        self.assertEqual(args['calendarId'], 'primary')
        self.assertEqual(args['maxResults'], 10)
        self.assertTrue(args['singleEvents'])

    def test_rejects_limits_and_naive_time(self):
        with self.assertRaises(ValueError): calendar_reader.upcoming(limit=11)
        with self.assertRaises(ValueError): calendar_reader.upcoming(now=datetime.datetime(2026, 1, 1))

    def test_paris_daylight_saving_and_all_day(self):
        start, end = calendar_reader.day_bounds(datetime.date(2026, 3, 29))
        self.assertEqual((end.astimezone(datetime.timezone.utc) - start.astimezone(datetime.timezone.utc)).total_seconds(), 23 * 3600)
        self.assertEqual(calendar_reader._instant({'date':'2026-03-29'}), start)
        self.assertEqual(calendar_reader._instant({'dateTime':'2026-03-29T10:00:00Z'}).hour, 12)

    def test_free_slots_merge_busy_and_ignore_transparent(self):
        start, end = calendar_reader.day_bounds(datetime.date(2026, 11, 18))
        start = start.replace(hour=9); end = end.replace(day=18, hour=18)
        events = [dict(start=start.replace(hour=10), end=start.replace(hour=12), busy=True),
                  dict(start=start.replace(hour=11), end=start.replace(hour=13), busy=True),
                  dict(start=start.replace(hour=14), end=start.replace(hour=15), busy=False)]
        slots = calendar_reader.free_slots(events, start, end)
        self.assertEqual([(a.hour,b.hour) for a,b in slots], [(9,10),(13,18)])

    def test_interpret_day_week_availability_and_not_cuisine(self):
        now = datetime.datetime(2026, 11, 17, 10, tzinfo=calendar_reader.PARIS)
        with patch('calendar_reader.events_between', return_value=[]) as fetch:
            self.assertIn('Aucun événement', calendar_reader.interpret('Mon agenda demain', now))
            self.assertEqual(fetch.call_args.args[0].date(), datetime.date(2026, 11, 18))
            self.assertIn('Créneaux libres', calendar_reader.interpret('Suis-je disponible demain ?', now))
            calendar_reader.interpret('agenda semaine prochaine', now)
            self.assertEqual(fetch.call_args.args[0].date(), datetime.date(2026, 11, 23))
            calendar_reader.interpret('programme du 19 novembre', now)
            self.assertEqual(fetch.call_args.args[0].date(), datetime.date(2026, 11, 19))
            calendar_reader.interpret('FamilyWall demain', now)
            self.assertEqual(fetch.call_args.args[0].date(), datetime.date(2026, 11, 18))
            self.assertIsNone(calendar_reader.interpret('retrouve ma recette de chili', now))

    def test_events_pagination_recurrence_and_all_day_end_exclusive(self):
        service = Mock()
        service.events.return_value.list.return_value.execute.side_effect = [
            {'items':[{'summary':'Journée','start':{'date':'2026-11-18'},'end':{'date':'2026-11-19'}}], 'nextPageToken':'next'},
            {'items':[{'summary':'Réunion','start':{'dateTime':'2026-11-18T10:00:00+01:00'},'end':{'dateTime':'2026-11-18T11:00:00+01:00'}}]}]
        start,end = calendar_reader.day_bounds(datetime.date(2026,11,18))
        with patch('calendar_reader._service', return_value=service):
            events = calendar_reader.events_between(start,end)
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0]['all_day'])
        self.assertEqual(events[0]['end'], end)
        self.assertEqual(service.events.return_value.list.call_count, 2)
        self.assertTrue(service.events.return_value.list.call_args.kwargs['singleEvents'])
        self.assertEqual(calendar_reader.free_slots(events, start.replace(hour=9), start.replace(hour=18)), [])

    def test_phone_calendar_merges_exact_duplicates_and_busy(self):
        start, end = calendar_reader.day_bounds(datetime.date(2026,11,18))
        event = {'title':'Test','start':start.replace(hour=10),'end':start.replace(hour=11),'all_day':False,'busy':True}
        with patch('calendar_reader.events_between', return_value=[event.copy()]):
            text = calendar_reader.interpret('agenda le 2026-11-18', now=start, extra_events=[event.copy()])
            self.assertEqual(text.count('Test'), 1)
            free = calendar_reader.interpret('disponible 2026-11-18', now=start, extra_events=[event.copy()])
            self.assertIn('09h00 à 10h00', free)
            self.assertIn('11h00 à 18h00', free)
