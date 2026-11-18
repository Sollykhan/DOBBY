import unittest

from speech_text import normalize_french


class SpeechTextTests(unittest.TestCase):
    def test_calendar_expressions(self):
        self.assertEqual(normalize_french('Le 11 novembre à 14 h 30.'), 'Le onze novembre à quatorze heures trente.')
        self.assertEqual(normalize_french('Le 01/11/2026 à 1h05 puis 8h.'), 'Le premier novembre deux mille vingt-six à une heure cinq puis huit heures.')

    def test_iso_and_invalid_values_are_not_invented(self):
        self.assertEqual(normalize_french('31/02/2026 à 25h70'), '31/02/2026 à 25h70')
        self.assertEqual(normalize_french('2026-11-01'), '2026-11-01')

    def test_unrelated_text_is_preserved(self):
        self.assertEqual(normalize_french('Bonjour, votre code est disponible.'), 'Bonjour, votre code est disponible.')
