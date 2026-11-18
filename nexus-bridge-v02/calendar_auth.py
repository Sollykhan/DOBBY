"""Interactive local Google Calendar authorization; no credentials in logs or SQLite."""
import os
from pathlib import Path

import keyring
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/calendar.readonly']
SERVICE = 'DOBBY.GoogleCalendar.readonly'
ACCOUNT = 'local-user'

def credential_path():
    directory = Path(os.environ['LOCALAPPDATA']) / 'DOBBY' / 'secrets'
    explicit = directory / 'google_credentials.json'
    if explicit.is_file():
        return explicit
    matches = [p for p in directory.glob('client_secret_*.json') if p.is_file() and not p.is_symlink()]
    if len(matches) != 1:
        raise RuntimeError('Fichier OAuth absent ou ambigu dans le dossier des secrets.')
    return matches[0]

def authorize():
    backend = keyring.get_keyring()
    if backend.__class__.__module__ != 'keyring.backends.Windows':
        raise RuntimeError('Le coffre Windows Credential Manager est indisponible.')
    flow = InstalledAppFlow.from_client_secrets_file(str(credential_path()), SCOPES)
    credentials = flow.run_local_server(host='127.0.0.1', port=0, open_browser=True,
                                        authorization_prompt_message='', success_message='Autorisation DOBBY terminée. Vous pouvez fermer cet onglet.')
    keyring.set_password(SERVICE, ACCOUNT, credentials.to_json())

if __name__ == '__main__':
    try:
        authorize()
        print('Autorisation Google Agenda enregistrée dans le Gestionnaire d’identifiants Windows.')
    except Exception:
        raise SystemExit('Autorisation impossible. Vérifiez le fichier OAuth, le coffre Windows et la configuration Google.') from None
