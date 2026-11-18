import subprocess
import unittest
from unittest.mock import patch

import homelab_probe


class HomelabProbeTests(unittest.TestCase):
    @patch('homelab_probe.subprocess.run')
    def test_fixed_command_and_closed_response(self, run):
        run.return_value.stdout = b'codex=present\nclaude=absent\nfixture=present\n'
        self.assertEqual(homelab_probe.check(), {'codex': 'present', 'claude': 'absent', 'fixture': 'present'})
        self.assertEqual(run.call_args.args[0], homelab_probe._ARGS)
        self.assertFalse(run.call_args.kwargs['shell'])
        self.assertEqual(run.call_args.kwargs['timeout'], 12)

    @patch('homelab_probe.subprocess.run')
    def test_rejects_unexpected_or_duplicate_fields(self, run):
        for output in (b'codex=present\nclaude=absent\nfixture=present\nextra=secret\n',
                       b'codex=present\ncodex=absent\nfixture=present\n', b'x' * 129):
            run.return_value.stdout = output
            with self.assertRaises(homelab_probe.ProbeUnavailable):
                homelab_probe.check()

    @patch('homelab_probe.subprocess.run', side_effect=subprocess.TimeoutExpired('ssh', 12))
    def test_timeout_is_reported_without_raw_details(self, run):
        with self.assertRaisesRegex(homelab_probe.ProbeUnavailable, '^runner_unavailable$'):
            homelab_probe.check()
