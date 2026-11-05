"""v1.3.9-alpha: consent host start intent, silent background start.

The popup this guards against is produced at two places:
  * ``ConsentHost.run()`` always called ``show()`` after wiring the tray, so
    every freshly spawned host raised a window (and, while the bridge was still
    starting, the "无法连接授权桥" notice);
  * a second host that hit the mutex posted ``WM_SHOW`` to the running one.

These tests pin the intent plumbing and the silent-start behaviour without
touching a real window.
"""
import os
import sys
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from computer_mcp import consent_ipc, native_consent


class ParseIntentTests(unittest.TestCase):
    def test_default_is_background(self):
        self.assertEqual(native_consent.parse_intent([]), 'background')
        self.assertEqual(
            native_consent.parse_intent(['--broker-session', 'abc']), 'background')

    def test_show_is_accepted(self):
        self.assertEqual(native_consent.parse_intent(['--intent=show']), 'show')
        self.assertEqual(
            native_consent.parse_intent(['--intent=SHOW ']), 'show')

    def test_unknown_intent_is_rejected(self):
        with self.assertRaises(ValueError):
            native_consent.parse_intent(['--intent=visible'])
        with self.assertRaises(ValueError):
            native_consent.parse_intent(['--intent='])

    def test_main_rejects_unknown_intent_before_starting(self):
        self.assertEqual(native_consent.main(['--intent=loud']), 2)


class ConsentHostIntentTests(unittest.TestCase):
    def test_host_defaults_to_background(self):
        host = native_consent.ConsentHost('nonce')
        self.assertEqual(host.intent, 'background')
        self.assertIsNone(host.last_sync_ok)

    def test_host_rejects_unknown_intent(self):
        with self.assertRaises(ValueError):
            native_consent.ConsentHost('nonce', intent='loud')

    def test_consent_cli_rejects_unknown_intent(self):
        from computer_mcp import consent
        with self.assertRaises(SystemExit) as caught:
            consent.main(['--broker-session', 'x', '--intent=loud'])
        self.assertEqual(caught.exception.code, 2)


class StatusFileTests(unittest.TestCase):
    def test_status_records_intent_and_background_sync_state(self):
        import json
        import tempfile
        from pathlib import Path
        from computer_mcp import security

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(security, 'data_home', return_value=Path(tmp)):
                host = native_consent.ConsentHost('nonce', intent='background')
                host.last_sync_ok = False
                host.state_unknown = True
                host._write_status()
            payload = json.loads((Path(tmp) / 'state' / 'consent-host.json')
                                 .read_text(encoding='utf-8'))
        self.assertEqual(payload['intent'], 'background')
        self.assertIs(payload['last_sync_ok'], False)
        self.assertIsNone(payload['granted'])


class ConsentCommandMatchTests(unittest.TestCase):
    """``_native_instance`` must keep proving the peer, intent included."""

    def test_command_without_intent_still_matches(self):
        cmd = ['pythonw.exe', '-I', '-m', 'computer_mcp.consent',
               '--broker-session', 'abc']
        self.assertTrue(consent_ipc._matches_consent_command(cmd, 'abc'))

    def test_known_intents_match(self):
        for intent in ('background', 'show'):
            cmd = ['pythonw.exe', '-I', '-m', 'computer_mcp.consent',
                   '--broker-session', 'abc', '--intent=' + intent]
            self.assertTrue(consent_ipc._matches_consent_command(cmd, 'abc'))

    def test_unknown_intent_is_not_a_consent_host(self):
        cmd = ['pythonw.exe', '-I', '-m', 'computer_mcp.consent',
               '--broker-session', 'abc', '--intent=loud']
        self.assertFalse(consent_ipc._matches_consent_command(cmd, 'abc'))

    def test_other_nonce_or_junk_arguments_are_rejected(self):
        other = ['pythonw.exe', '-I', '-m', 'computer_mcp.consent',
                 '--broker-session', 'other']
        self.assertFalse(consent_ipc._matches_consent_command(other, 'abc'))
        junk = ['pythonw.exe', '-I', '-m', 'computer_mcp.consent',
                '--broker-session', 'abc', '--evil']
        self.assertFalse(consent_ipc._matches_consent_command(junk, 'abc'))


class OpenNativeIntentTests(unittest.TestCase):
    def test_unknown_intent_raises_before_spawning(self):
        with patch.object(consent_ipc, '_host_window_exists', return_value=False), \
                patch.object(consent_ipc.subprocess, 'Popen') as popen:
            with self.assertRaises(ValueError):
                consent_ipc.open_native('loud')
            popen.assert_not_called()

    def test_background_never_wakes_a_running_host(self):
        with patch.object(consent_ipc, '_host_window_exists', return_value=True), \
                patch.object(consent_ipc, '_post_show') as wake, \
                patch.object(consent_ipc, '_native_instances', {}):
            result = consent_ipc.open_native('background')
        self.assertEqual(result, {'opened': True, 'woken': False})
        wake.assert_not_called()

    def test_show_intent_wakes_a_running_host(self):
        record = {'process': type('P', (), {'is_running': lambda self: True})()}
        with patch.object(consent_ipc, '_host_window_exists', return_value=True), \
                patch.object(consent_ipc, '_post_show', return_value=True) as wake, \
                patch.object(consent_ipc, '_native_instances', {'n': record}):
            result = consent_ipc.open_native('show')
        self.assertEqual(result, {'opened': True, 'woken': True})
        wake.assert_called_once()


class StartupSyncTests(unittest.TestCase):
    """A background start reports bridge trouble through the tray, not a modal."""

    def _host(self):
        host = native_consent.ConsentHost.__new__(native_consent.ConsentHost)
        host._state_lock = threading.RLock()
        host._state_generation = 0
        host.state_unknown = False
        host.last_sync_ok = None
        host.granted = False
        host.authorization = {}
        host.lease_until = 0.0
        host.tray = False
        host.hwnd = 0
        host.intent = 'background'
        host._showing = False
        return host

    def test_background_startup_never_opens_a_dialog(self):
        host = self._host()

        def ipc(*args, **kwargs):
            raise OSError('pipe down')

        host.ipc = ipc
        with patch.object(native_consent.native_dialog, 'ask_notice') as notice, \
                patch.object(native_consent.ConsentHost, '_write_status'):
            host._startup_sync()
        notice.assert_not_called()
        self.assertTrue(host.state_unknown)
        self.assertFalse(host.last_sync_ok)

    def test_background_startup_marks_sync_ok_when_bridge_answers(self):
        host = self._host()
        host.ipc = lambda *a, **k: {'state': {'granted': False}}
        with patch.object(native_consent.native_dialog, 'ask_notice') as notice, \
                patch.object(native_consent.ConsentHost, '_write_status'):
            host._startup_sync()
        notice.assert_not_called()
        self.assertFalse(host.state_unknown)
        self.assertTrue(host.last_sync_ok)

    def test_show_path_still_reports_unknown_state(self):
        """An explicit user open may explain the failure; it must not be silent."""
        host = self._host()
        host.intent = 'show'

        def ipc(*args, **kwargs):
            raise OSError('pipe down')

        host.ipc = ipc
        with patch.object(native_consent.native_dialog, 'ask_notice') as notice, \
                patch.object(native_consent.ConsentHost, '_write_status'):
            host.show()
        notice.assert_called_once()


if __name__ == '__main__':
    unittest.main()
