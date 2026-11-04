"""RC3 follow-up regression definitions; no real consent or desktop actions."""
import os
import queue
import threading
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import agent_session, consent_ipc, native_consent, native_dialog, permission


class RequestCacheTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {'ICON_CONTROL_AUTO_CONSENT': '1'})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.cache = patch.object(permission, '_last_consent_request', {})
        self.cache.start()
        self.addCleanup(self.cache.stop)
        self.clock = patch.object(permission.time, 'monotonic', return_value=100.0)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def exercise(self, response):
        def reply(command, **fields):
            if command == 'open':
                return {'opened': True, 'request_id': 'old' if calls.count('open') == 1 else 'new'}
            if command == 'request_status':
                if isinstance(response, Exception):
                    raise response
                return response
            raise AssertionError(command)

        calls = []
        def recorded(command, **fields):
            calls.append(command)
            return reply(command, **fields)

        with patch.object(consent_ipc, 'request', side_effect=recorded) as ipc:
            first = permission._request_consent({}, ['input'])
            second = permission._request_consent({}, ['input'])
        self.assertEqual(first, 'old')
        self.assertEqual(ipc.call_args_list[1].kwargs['agent_session'], agent_session.current())
        self.assertEqual(ipc.call_args_list[1].kwargs['request_id'], 'old')
        return second, calls

    def test_pending_and_displayed_reuse_without_reopening(self):
        for status in ('pending', 'displayed'):
            with self.subTest(status=status), patch.object(permission, '_last_consent_request', {}):
                second, calls = self.exercise({'request_id': 'old', 'status': status})
                self.assertEqual(second, 'old')
                self.assertEqual(calls, ['open', 'request_status'])

    def test_unconfirmed_or_terminal_request_is_replaced(self):
        responses = [
            {'request_id': 'old', 'status': status}
            for status in ('consumed', 'denied', 'expired', 'approved', 'cancelled')
        ] + [{}, {'request_id': 'other', 'status': 'pending'},
             PermissionError('pruned'), TimeoutError('unavailable')]
        for response in responses:
            with self.subTest(response=response), patch.object(permission, '_last_consent_request', {}):
                second, calls = self.exercise(response)
                self.assertEqual(second, 'new')
                self.assertEqual(calls, ['open', 'request_status', 'open'])


class RequestStatusOwnershipTests(AuthorityCase, unittest.TestCase):
    def test_request_status_checks_actual_pipe_peer(self):
        with patch.object(agent_session, 'lookup', return_value=None), patch.object(consent_ipc, '_requests') as requests:
            with self.assertRaises(PermissionError):
                consent_ipc.dispatch({'command': 'request_status', 'agent_session': 'a', 'request_id': 'r'}, os.getpid())
        requests.get.assert_not_called()

    def test_request_status_rejects_other_sessions_and_processes(self):
        for record in ({'agent_session': 'b', 'peer': {'pid': os.getpid()}},
                       {'agent_session': 'a', 'peer': {'pid': os.getpid() + 1}}):
            with self.subTest(record=record), patch.object(agent_session, 'lookup', return_value={'id': 'a'}), patch.object(consent_ipc, '_requests') as requests:
                requests.get.return_value = record
                with self.assertRaises(PermissionError):
                    consent_ipc.dispatch({'command': 'request_status', 'agent_session': 'a', 'request_id': 'r'}, os.getpid())


class ModalRecoveryTests(unittest.TestCase):
    def host(self):
        host = object.__new__(native_consent.ConsentHost)
        host._state_lock = threading.RLock()
        host._state_generation = 0
        host._heartbeat_results = queue.Queue(maxsize=4)
        host.granted = True
        host.state_unknown = False
        host.authorization = {'agent_session': 'a'}
        host.lease_until = 10**12
        host.hwnd = 123
        host.tray = False
        host.user32 = Mock()
        host._refresh_tray = Mock()
        return host

    def assert_negative_heartbeat_during_notice(self, action, host):
        completed = threading.Event()
        failures = []

        def heartbeat():
            try:
                host._heartbeat()
            except BaseException as exc:
                failures.append(exc)
            finally:
                completed.set()

        def notice(*args):
            # The modal callback remains open until the independent worker
            # finishes: failure must not wait for the user to dismiss it.
            self.assertFalse(host.granted)
            self.assertTrue(host.state_unknown)
            worker = threading.Thread(target=heartbeat, daemon=True)
            worker.start()
            try:
                self.assertTrue(completed.wait(2), 'Heartbeat blocked by modal notification')
                self.assertEqual(failures, [])
                host.ipc.assert_any_call('heartbeat', granted=False)
            finally:
                self.addCleanup(worker.join, 2)

        with patch.object(native_dialog, 'ask_notice', side_effect=notice) as dialog:
            action()
        dialog.assert_called_once()

    def test_failed_revoke_does_not_hold_lock_during_notice(self):
        host = self.host()
        def reply(command, **fields):
            if command == 'heartbeat':
                return {'granted': False}
            if command == 'revoke':
                raise TimeoutError('revoke timeout')
            raise AssertionError(command)

        host.ipc = Mock(side_effect=reply)
        self.assert_negative_heartbeat_during_notice(host.revoke, host)

    def test_failed_grant_does_not_hold_lock_during_notice(self):
        host = self.host()
        host.ipc = Mock(return_value={'granted': False})
        with patch.object(consent_ipc, 'confirmed_grant', side_effect=TimeoutError('grant timeout')):
            self.assert_negative_heartbeat_during_notice(
                lambda: host._apply('a', ['input'], {'pid': 1, 'created': 1, 'exe': 'fixture.exe'}, 30), host)
