"""Regressions from the bounded desktop run; isolated actuator backends only."""
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from authority_fixture import AuthorityCase
from computer_mcp import agent_session, security, permission, input_guard, control
from computer_mcp.actions import window


class DesktopFollowupTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def test_window_move_reaches_guarded_native_call(self):
        with patch('win32gui.GetWindowRect',return_value=(10,10,110,90)), \
                patch('win32gui.SetWindowPos') as move, \
                patch.object(window,'_set_dpi_aware_win'), \
                patch.object(window,'_check_exit_fullscreen_win'), \
                patch.object(window,'_get_window_data',return_value={'hwnd':999}):
            result=window.move_window(999,40,50)
        self.assertTrue(result.get('success'),result)
        move.assert_called_once()
        self.assertEqual(move.call_args.args[:6],(999,0,40,50,100,80))

    def test_live_peer_lookup_does_not_scan_historical_sessions(self):
        record=agent_session.register('isolated test')
        with patch.object(Path,'glob',side_effect=AssertionError('Full scan')):
            self.assertEqual(agent_session.lookup(record['id'],os.getpid()),record)

    def test_peer_lookup_rechecks_file_and_signature_each_time(self):
        record=agent_session.register('isolated test')
        self.assertIsNotNone(agent_session.lookup(record['id'],os.getpid()))
        record['created']+=1
        path=security.data_home()/'state'/'sessions'/(record['id']+'.json')
        path.write_text(json.dumps(record),encoding='utf-8')
        self.assertIsNone(agent_session.lookup(record['id'],os.getpid()))
        record['signature']=security.signature(record,security.load_token())
        path.write_text(json.dumps(record),encoding='utf-8')
        self.assertIsNone(agent_session.lookup(record['id'],os.getpid()))

    def test_peer_lookup_rejects_wrong_pid_and_path_injection(self):
        record=agent_session.register('isolated test')
        self.assertIsNone(agent_session.lookup(record['id'],os.getpid()+100000))
        for identity in ('../outside','C:/outside',None,'g'*48):
            self.assertIsNone(agent_session.lookup(identity,os.getpid()))

    def test_peer_lookup_rejects_signed_identity_mismatch(self):
        record=agent_session.register('isolated test');identity=record['id']
        record['id']='b'*48
        record['signature']=security.signature(record,security.load_token())
        (security.data_home()/'state'/'sessions'/(identity+'.json')).write_text(json.dumps(record),encoding='utf-8')
        self.assertIsNone(agent_session.lookup(identity,os.getpid()))

    def test_lost_modifier_cancels_following_letters(self):
        raw=Mock();controller=input_guard.KeyboardController(raw)
        with patch.object(input_guard,'_monitor_thread',Mock()), \
                patch.object(input_guard,'_held_controllers',set()), \
                patch.object(input_guard,'_controllers',{controller}):
            controller.press(input_guard.Key.ctrl)
            with patch.object(permission,'status',return_value={'granted':False}):
                input_guard._check_held()
            self.assertFalse(controller.held)
            self.assertEqual(control.status()['owner'],'user')
            with self.assertRaises(permission.PermissionDenied):controller.press('a')
        raw.press.assert_called_once_with(input_guard.Key.ctrl)
        raw.release.assert_called_once_with(input_guard.Key.ctrl)

    def test_monitor_exception_cancels_remaining_input(self):
        raw=Mock();controller=input_guard.KeyboardController(raw)
        with patch.object(input_guard,'_monitor_thread',Mock()), \
                patch.object(input_guard,'_held_controllers',set()), \
                patch.object(input_guard,'_controllers',{controller}):
            controller.press(input_guard.Key.ctrl)
            with patch.object(permission,'status',side_effect=OSError('authority unavailable')):
                input_guard._check_held()
            with self.assertRaises(permission.PermissionDenied):controller.press('a')
        raw.release.assert_called_once_with(input_guard.Key.ctrl)
