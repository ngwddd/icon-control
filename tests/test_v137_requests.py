"""RC2 authorization regressions. These are isolated test definitions, not live consent."""
import os
import threading
import queue
import unittest
from unittest.mock import Mock, patch
from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, consent_ipc, consent_requests, permission
from computer_mcp import macro_ext, native_consent, native_dialog


class RequestLifecycleTests(AuthorityCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.peer = agent_session.register('request fixture')
        self.app = capabilities.process_record(os.getpid())
        self.requests = consent_requests.RequestQueue()

    def create(self):
        return self.requests.create(os.getpid(), self.peer['id'], self.app, ['input'])

    def test_spoofed_session_is_rejected(self):
        with self.assertRaises(PermissionError):
            self.requests.create(os.getpid(), 'a'*48, self.app, ['input'])

    def test_terminal_entries_free_space_immediately(self):
        with patch.object(consent_requests, 'MAX_REQUESTS', 1):
            first = self.create()
            self.requests.get(first['request_id'], display=True)
            self.requests.finish(first['request_id'], 'denied')
            second = self.create()
        self.assertNotEqual(first['request_id'], second['request_id'])

    def test_active_duplicates_do_not_extend_expiry(self):
        first, second = self.create(), self.create()
        self.assertEqual(first['request_id'], second['request_id'])
        self.assertEqual(first['expires_at'], second['expires_at'])

    def test_consumed_request_cannot_be_replayed(self):
        record = self.create()
        self.requests.get(record['request_id'], display=True)
        self.requests.finish(record['request_id'], 'approved')
        self.requests.finish(record['request_id'], 'consumed')
        with self.assertRaises(PermissionError):
            self.requests.get(record['request_id'], display=True)

    def test_target_process_replacement_expires_request(self):
        record = self.create()
        with patch.object(capabilities, 'process_record', return_value=dict(self.app, created=0)):
            with self.assertRaises(PermissionError):
                self.requests.get(record['request_id'])

    def test_bad_signature_cannot_be_approved(self):
        record = self.create()
        self.requests.records[record['request_id']]['scopes'] = ['process']
        with self.assertRaises(PermissionError):
            self.requests.get(record['request_id'])

    def test_workspace_does_not_drift_after_chdir(self):
        before = agent_session.identity()
        with patch('psutil.Process.cwd', return_value='C:/different-workspace'):
            agent_session.register()
            after = agent_session.identity()
        self.assertEqual(before, after)

    def test_same_workspace_sessions_have_distinct_subjects(self):
        first = agent_session.identity()
        with agent_session.bind('b'*48):
            agent_session.register('second HTTP credential')
            second = agent_session.identity()
        self.assertNotEqual(first, second)

    def test_sessions_do_not_merge_targets_or_scopes(self):
        first = self.create()
        with agent_session.bind('b'*48):
            second_peer = agent_session.register('other caller')
            second = self.requests.create(os.getpid(), second_peer['id'], None, ['screen_read'])
        self.assertNotEqual(first['request_id'], second['request_id'])
        self.assertEqual(self.requests.get(first['request_id'])['application'], self.app)
        self.assertEqual(self.requests.get(second['request_id'])['scopes'], ['screen_read'])
        self.assertIsNone(self.requests.get(second['request_id'])['application'])


class ConsentBoundaryTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_cross_app_target_denial_requests_consent(self):
        with patch.object(capabilities, 'check_target', return_value='Target application is outside the human-approved application list'), patch.object(permission, 'request_target_consent') as request:
            with self.assertRaises(permission.PermissionDenied):
                capabilities.require_target(hwnd=4321)
        request.assert_called_once_with(hwnd=4321, point=None)

    def test_paste_requires_clipboard_read(self):
        self.assertIn('clipboard_read', macro_ext._MACRO_SCOPES['paste'])
        with patch.object(capabilities, 'has_scope', return_value=False):
            with self.assertRaises(permission.PermissionDenied):
                macro_ext._clipboard_text()

    def test_unknown_preset_does_not_become_all(self):
        self.assertEqual(native_dialog.preset_for(['input_observe']), -1)

    def test_pending_unknown_agent_never_selects_latest(self):
        host = object.__new__(native_consent.ConsentHost)
        live = [dict(id='b'*48, pid=123, created=10)]
        with patch.object(agent_session, 'active', return_value=live):
            self.assertIsNone(host._pick_agent('a'*48))

    def test_lost_grant_reply_cancels_same_operation(self):
        ipc = Mock(side_effect=[TimeoutError('lost reply'), {'status':'cancelled'}])
        with self.assertRaises(TimeoutError):
            consent_ipc.confirmed_grant(ipc, agent_session='a'*48)
        first, second = ipc.call_args_list
        self.assertEqual(first.args, ('grant',))
        self.assertEqual(second.args, ('cancel_grant',))
        self.assertEqual(first.kwargs['operation_id'], second.kwargs['operation_id'])

    def test_successful_grant_requires_read_back(self):
        state = {'granted': True}
        ipc = Mock(side_effect=[state, {'status':'confirmed', 'state':state}])
        self.assertEqual(consent_ipc.confirmed_grant(ipc), state)
        self.assertEqual([c.args[0] for c in ipc.call_args_list], ['grant','grant_status'])

    def test_unconfirmed_read_back_cancels_grant(self):
        ipc = Mock(side_effect=[{'granted':True}, {'status':'unavailable'}, {'status':'cancelled'}])
        with self.assertRaises(PermissionError):
            consent_ipc.confirmed_grant(ipc)
        self.assertEqual(ipc.call_args_list[-1].args, ('cancel_grant',))

    def test_cancel_before_late_grant_rejects_replay(self):
        agent_session.register()
        operation_id = '1'*48
        with patch.object(consent_ipc, '_native_client', return_value=True), patch.object(consent_ipc, '_grant_operations', {}):
            consent_ipc.dispatch(dict(command='cancel_grant', operation_id=operation_id), os.getpid())
            with self.assertRaises(PermissionError):
                consent_ipc.dispatch(dict(command='grant', operation_id=operation_id), os.getpid())

    def test_stale_heartbeat_cannot_override_new_grant(self):
        host = object.__new__(native_consent.ConsentHost)
        host._state_lock = threading.RLock()
        host._state_generation = 2
        host._heartbeat_results = queue.Queue()
        host._heartbeat_results.put((1, {'granted':False}, None))
        host.granted = True
        host.state_unknown = False
        host._refresh_tray = Mock()
        host._receive_heartbeat()
        self.assertTrue(host.granted)
        host._refresh_tray.assert_not_called()

    def test_worker_only_posts_heartbeat_result(self):
        host = object.__new__(native_consent.ConsentHost)
        host._state_lock = threading.RLock()
        host._state_generation = 1
        host._heartbeat_results = queue.Queue(maxsize=4)
        host.granted = True
        host.state_unknown = False
        host.lease_until = 10**12
        host.hwnd = 123
        host.user32 = Mock()
        host.ipc = Mock(return_value={'granted':False})
        host._refresh_tray = Mock()
        host._heartbeat()
        self.assertTrue(host.granted)
        host._refresh_tray.assert_not_called()
        host.user32.PostMessageW.assert_called_once()
