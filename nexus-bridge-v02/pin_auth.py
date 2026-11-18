"""Local six-digit PIN verifier and persistent online attempt limiter."""
import hashlib
import hmac
import os
import re
import sqlite3
import time
from contextlib import contextmanager

MAX_FAILURES = 5
LOCK_SECONDS = 15 * 60


class PinAuth:
    def __init__(self, database):
        self.database = str(database)
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS pin_auth (
                id INTEGER PRIMARY KEY CHECK(id=1), salt BLOB NOT NULL, digest BLOB NOT NULL,
                generation INTEGER NOT NULL, failures INTEGER NOT NULL, locked_until REAL NOT NULL)''')
            db.execute('''CREATE TABLE IF NOT EXISTS pin_setup_attempts (
                id INTEGER PRIMARY KEY CHECK(id=1), failures INTEGER NOT NULL, locked_until REAL NOT NULL)''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.database, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def valid(pin):
        return isinstance(pin, str) and re.fullmatch(r'[0-9]{6}', pin) is not None

    @staticmethod
    def derive(pin, salt):
        return hashlib.scrypt(pin.encode('ascii'), salt=salt, n=16384, r=8, p=1, dklen=32)

    def configure(self, pin):
        if not self.valid(pin) or pin == '000000':
            raise ValueError('Le PIN doit contenir six chiffres ASCII et différer du code de première configuration.')
        salt = os.urandom(16)
        digest = self.derive(pin, salt)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT generation FROM pin_auth WHERE id=1').fetchone()
            generation = row[0] + 1 if row else 1
            db.execute('INSERT OR REPLACE INTO pin_auth VALUES (1,?,?,?,?,?)', (salt, digest, generation, 0, 0))

    def configured(self):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM pin_auth WHERE id=1').fetchone() is not None

    def configure_from_bootstrap(self, bootstrap, pin, confirmation):
        """One-time first-use setup. The bootstrap value is never stored."""
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM pin_auth WHERE id=1').fetchone():
                return False
            row = db.execute('SELECT failures,locked_until FROM pin_setup_attempts WHERE id=1').fetchone()
            failures, locked_until = row if row else (0, 0)
            now = time.time()
            if now < locked_until:
                return False
            if bootstrap != '000000' or not self.valid(pin) or pin == '000000' or pin != confirmation:
                failures += 1
                db.execute('INSERT OR REPLACE INTO pin_setup_attempts VALUES (1,?,?)',
                           (failures, now + LOCK_SECONDS if failures >= MAX_FAILURES else 0))
                return False
            salt = os.urandom(16)
            digest = self.derive(pin, salt)
            db.execute('INSERT INTO pin_auth VALUES (1,?,?,1,0,0)', (salt, digest))
            db.execute('DELETE FROM pin_setup_attempts WHERE id=1')
            return True

    def generation(self):
        with self.connect() as db:
            row = db.execute('SELECT generation FROM pin_auth WHERE id=1').fetchone()
        return row[0] if row else None

    def verify(self, pin):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT salt,digest,generation,failures,locked_until FROM pin_auth WHERE id=1').fetchone()
            if row is None:
                return None
            salt, digest, generation, failures, locked_until = row
            now = time.time()
            if now < locked_until:
                return None
            correct = self.valid(pin) and hmac.compare_digest(self.derive(pin, salt), digest)
            if correct:
                db.execute('UPDATE pin_auth SET failures=0,locked_until=0 WHERE id=1')
                return generation
            failures += 1
            db.execute('UPDATE pin_auth SET failures=?,locked_until=? WHERE id=1',
                       (failures, now + LOCK_SECONDS if failures >= MAX_FAILURES else 0))
            return None
