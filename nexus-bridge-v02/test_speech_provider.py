import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch
import speech_provider as provider

class SpeechTests(unittest.TestCase):
    def test_rejects_invalid_input_before_process(self):
        for text, language in [('', 'fr'), ('x' * 501, 'fr'), ('test', 'xx')]:
            with self.assertRaises(ValueError): provider.synthesize(text, language)

    def test_worker_receives_input_without_shell_and_rejects_bad_audio(self):
        with patch.object(provider.Path, 'is_file', return_value=True), patch.object(provider.subprocess, 'run', return_value=SimpleNamespace(stdout=b'RIFF\x04\x00\x00\x00WAVE')) as run:
            self.assertTrue(provider.synthesize('Phrase de test', 'fr').startswith(b'RIFF'))
            self.assertFalse(run.call_args.kwargs['shell'])
            self.assertNotIn('Phrase de test', ' '.join(run.call_args.args[0]))
        with patch.object(provider.Path, 'is_file', return_value=True), patch.object(provider.subprocess, 'run', return_value=SimpleNamespace(stdout=b'invalid')):
            with self.assertRaises(provider.SpeechUnavailable): provider.synthesize('test')

    def test_timeout_fails_closed(self):
        with patch.object(provider.Path, 'is_file', return_value=True), patch.object(provider.subprocess, 'run', side_effect=subprocess.TimeoutExpired('worker', 30)):
            with self.assertRaises(provider.SpeechUnavailable): provider.synthesize('test')
