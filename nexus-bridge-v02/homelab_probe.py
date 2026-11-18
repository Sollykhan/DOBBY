"""Read-only, opt-in connectivity check for the existing development Runner.

No user or model input is passed to SSH. This probe never starts an agent.
"""
import subprocess


_REMOTE = (
    "if test -x /home/runner/.local/bin/codex; then printf 'codex=present\\n'; "
    "else printf 'codex=absent\\n'; fi; "
    "if test -x /home/runner/.local/bin/claude; then printf 'claude=present\\n'; "
    "else printf 'claude=absent\\n'; fi; "
    "if test -d /home/runner/projects/nexus-test/.git; then printf 'fixture=present\\n'; "
    "else printf 'fixture=absent\\n'; fi"
)
_ARGS = ('ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
         '-o', 'ConnectTimeout=8', 'nexus-runner', _REMOTE)


class ProbeUnavailable(Exception):
    pass


def check():
    """Return only fixed status values; suppress raw SSH output and errors."""
    try:
        result = subprocess.run(_ARGS, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=12, check=True,
                                shell=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        raise ProbeUnavailable('runner_unavailable') from None
    if len(result.stdout) > 128:
        raise ProbeUnavailable('invalid_response')
    try:
        lines = result.stdout.decode('ascii').splitlines()
        values = dict(line.split('=', 1) for line in lines)
        if (len(lines) != 3 or set(values) != {'codex', 'claude', 'fixture'}
                or any(value not in ('present', 'absent') for value in values.values())):
            raise ValueError
    except (UnicodeError, ValueError):
        raise ProbeUnavailable('invalid_response') from None
    return values
