import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import calendar_auth

class CalendarAuthTests(unittest.TestCase):
    def test_finds_one_client_without_reading_it(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / 'DOBBY' / 'secrets'
            directory.mkdir(parents=True)
            path = directory / 'client_secret_test.json'
            path.touch()
            with patch.dict('os.environ', {'LOCALAPPDATA': temp}):
                self.assertEqual(calendar_auth.credential_path(), path)
                (directory / 'client_secret_other.json').touch()
                with self.assertRaises(RuntimeError): calendar_auth.credential_path()

    def test_authorization_uses_read_only_scope_and_keyring(self):
        class WindowsBackend: pass
        WindowsBackend.__module__ = 'keyring.backends.Windows'
        flow = Mock()
        flow.run_local_server.return_value.to_json.return_value = '{"synthetic":"token"}'
        with patch.object(calendar_auth, 'credential_path', return_value=Path('synthetic.json')), \
             patch.object(calendar_auth.keyring, 'get_keyring', return_value=WindowsBackend()), \
             patch.object(calendar_auth.keyring, 'set_password') as save, \
             patch.object(calendar_auth.InstalledAppFlow, 'from_client_secrets_file', return_value=flow) as create:
            calendar_auth.authorize()
            create.assert_called_once_with('synthetic.json', calendar_auth.SCOPES)
            save.assert_called_once_with(calendar_auth.SERVICE, calendar_auth.ACCOUNT, '{"synthetic":"token"}')

    def test_refuses_non_windows_secret_backend(self):
        with patch.object(calendar_auth.keyring, 'get_keyring', return_value=object()):
            with self.assertRaises(RuntimeError): calendar_auth.authorize()
