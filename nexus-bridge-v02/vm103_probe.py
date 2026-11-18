"""Offline bubblewrap probe: no Codex, no network, no real secret access."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile

CHECK = r'''
import os, pathlib, sys
assert os.getcwd() == '/workspace'
assert not pathlib.Path('/home').exists()
assert not pathlib.Path('/etc').exists()
assert not pathlib.Path('/outside-canary').exists()
assert 'FAKE_SECRET_TOKEN' not in os.environ
assert os.environ.get('HOME') == '/tmp'
assert os.environ.get('CODEX_HOME') == '/tmp/codex'
for path, mode in [('/workspace/new.txt', 'w'), ('/workspace/fixture.txt', 'a')]:
    try:
        with open(path, mode) as f:
            f.write('probe')
    except OSError as e:
        assert e.errno == 30, e.errno
    else:
        raise AssertionError('write permitted')
try:
    pathlib.Path('/workspace/fixture.txt').unlink()
except OSError as e:
    assert e.errno == 30, e.errno
else:
    raise AssertionError('delete permitted')
assert os.readlink('/proc/self/ns/net') != sys.argv[1]
print('offline probe passed')
'''


def main():
    if os.name != 'posix':
        raise SystemExit('Linux required')
    os.environ['FAKE_SECRET_TOKEN'] = 'synthetic-test-marker'
    with tempfile.TemporaryDirectory(prefix='offline-probe-', dir='.') as temp:
        root = Path(temp).resolve()
        fixture = root / 'nexus-test'
        fixture.mkdir(mode=0o700)
        (fixture / 'fixture.txt').write_text('public dummy data\n')
        (root / 'outside-canary').write_text('synthetic canary, not a credential\n')
        before = hashlib.sha256((fixture / 'fixture.txt').read_bytes()).hexdigest()
        args = ['/usr/bin/bwrap', '--die-with-parent', '--new-session', '--unshare-pid',
                '--unshare-ipc', '--unshare-uts', '--unshare-net', '--ro-bind', '/usr', '/usr',
                '--ro-bind', '/lib', '/lib', '--ro-bind', '/lib64', '/lib64',
                '--symlink', 'usr/bin', '/bin', '--proc', '/proc', '--dev', '/dev',
                '--tmpfs', '/tmp', '--ro-bind', str(fixture), '/workspace',
                '--setenv', 'HOME', '/tmp', '--setenv', 'CODEX_HOME', '/tmp/codex',
                '--chdir', '/workspace', '/usr/bin/python3', '-c', CHECK,
                os.readlink('/proc/self/ns/net')]
        env = {'PATH': '/usr/bin:/bin', 'HOME': '/tmp', 'CODEX_HOME': '/tmp/codex', 'LANG': 'C.UTF-8'}
        result = subprocess.run(args, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15, check=False)
        if result.returncode:
            print('probe_failed: exit', result.returncode)
            print(result.stderr.decode('utf-8', errors='replace')[:1024])
            raise SystemExit(1)
        assert hashlib.sha256((fixture / 'fixture.txt').read_bytes()).hexdigest() == before
        assert not (fixture / 'new.txt').exists()
        print(result.stdout.decode('utf-8').strip())
        print('fixture unchanged; canary not exposed; network namespace isolated')


if __name__ == '__main__':
    main()
