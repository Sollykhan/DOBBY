"""Set the DOBBY PIN interactively on this computer; never echo its value."""
import getpass
import sys
from pathlib import Path
from pin_auth import PinAuth


def main():
    if not sys.stdin.isatty():
        raise SystemExit('Exécutez cette commande dans un terminal interactif local.')
    print('Définition du PIN DOBBY : saisie masquée, six chiffres.')
    pin = getpass.getpass('Nouveau PIN : ')
    confirm = getpass.getpass('Confirmer le PIN : ')
    if not PinAuth.valid(pin) or pin == '000000' or pin != confirm:
        raise SystemExit('PIN invalide ou confirmation différente ; rien n’a été modifié.')
    directory = Path(__file__).resolve().parent / '.dobby-local'
    directory.mkdir(exist_ok=True)
    PinAuth(directory / 'missions.sqlite3').configure(pin)
    print('PIN enregistré sous forme dérivée ; les anciennes sessions sont invalidées.')


if __name__ == '__main__':
    main()
