"""Session/capability isolation and fault injection, without real desktop input."""
import os
import unittest
from unittest.mock import patch, Mock
from authority_fixture import AuthorityCase, approval
from computer_mcp import agent_session, capabilities, consent_ipc, permission, permission_bridge as bridge
from computer_mcp import panic, input_guard

_real_target = capabilities.check_target

class CapabilityTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def scope(self, *scopes):
        auth = dict(approval(),scopes=list(scopes))
        bridge.write_state(True,client='fixture',event='action',authorization=auth)

    def test_mouse_approval_cannot_read_screen(self):
        self.scope('input')
        for name in ('screenshot','ocr_read','ui_tree','ui_find','list_windows','find_element','screen_state'):
            with self.subTest(name=name): self.assertIsNotNone(permission.check_tool(name))
        self.assertIsNone(permission.check_tool('click'))

    def test_privacy_approval_does_not_allow_input(self):
        self.scope('screen_read')
        self.assertIsNone(permission.check_tool('screenshot'))
        self.assertIsNotNone(permission.check_tool('click'))
        self.assertIsNotNone(permission.check_tool('control_claim'))

    def test_high_impact_actions_require_their_own_scope(self):
        self.scope('input')
        for name in ('type','key_press','ui_set_text','close_window','dataset_export','macro_save'):
            with self.subTest(name=name): self.assertIsNotNone(permission.check_tool(name))

    def test_two_agents_cannot_share_approval(self):
        self.assertTrue(permission.status()['granted'])
        with agent_session.bind('b'*48):
            self.assertFalse(permission.status()['granted'])
            self.assertIsNotNone(permission.check_tool('screenshot'))
            self.assertIsNotNone(permission.check_tool('click'))
        self.assertTrue(permission.status()['granted'])

    def test_tool_parameter_cannot_select_an_authorized_identity(self):
        real_identity = agent_session.current()
        with agent_session.bind('c'*48):
            self.assertIsNotNone(permission.check_tool('click',{'agent_session':real_identity}))

    def test_live_broker_failure_blocks_old_signed_file(self):
        with patch.object(consent_ipc,'live_valid',return_value=False):
            self.assertFalse(permission.status()['granted'])

    def test_failed_revoke_persistence_cannot_leave_old_file_effective(self):
        agent_session.register()
        with patch('computer_mcp.permission_bridge.os.replace',side_effect=OSError('disk full')):
            with self.assertRaises(OSError): bridge.write_state(False,client='fixture',event='action')
        def live(state, identity):
            return consent_ipc.dispatch(dict(command='authority',agent_session=identity,
                session=state['session'],revision=state['revision']),os.getpid())['granted']
        with patch.object(consent_ipc,'live_valid',side_effect=live):
            self.assertFalse(permission.status()['granted'])

    def test_untrusted_pipe_client_cannot_grant(self):
        with patch.object(consent_ipc,'_native_client',return_value=False):
            with self.assertRaises(PermissionError):
                consent_ipc.dispatch(dict(command='grant',agent_session=agent_session.current()),os.getpid())

    def test_pipe_checks_registered_peer_pid(self):
        agent_session.register()
        state = bridge.read_state()
        message = dict(command='authority',agent_session=agent_session.current(),
                       session=state['session'],revision=state['revision'])
        self.assertTrue(consent_ipc.dispatch(message,os.getpid())['granted'])
        self.assertFalse(consent_ipc.dispatch(message,os.getpid()+100000)['granted'])

    def test_new_revision_invalidates_inflight_authority_query(self):
        agent_session.register();state=bridge.read_state()
        bridge.write_state(False,client='fixture',event='action')
        self.assertFalse(consent_ipc.dispatch(dict(command='authority',agent_session=agent_session.current(),
            session=state['session'],revision=state['revision']),os.getpid())['granted'])

    def test_emergency_releases_keys_before_io_failure(self):
        raw = Mock(); keyboard = input_guard.KeyboardController(raw); keyboard.press('a')
        def fail():
            raw.release.assert_called_with('a')
            raise OSError('disk full')
        switch = panic.PanicSwitch(verbose=False)
        from pynput.keyboard import Key
        with patch('computer_mcp.security.latch_stop',side_effect=fail):
            switch._on_press(Key.esc);switch._on_release(Key.esc);switch._on_press(Key.esc)
        self.assertTrue(switch.triggered)
        self.assertFalse(keyboard.held)

    def test_agent_config_does_not_override_application_list(self):
        import win32gui, win32process
        process = Mock()
        process.cmdline.return_value = ['app.exe']
        with patch.object(win32gui,'GetForegroundWindow',return_value=12), \
             patch.object(win32gui,'GetAncestor',return_value=12), \
             patch.object(win32gui,'GetWindowText',return_value='User document'), \
             patch.object(win32process,'GetWindowThreadProcessId',return_value=(1,42)), \
             patch('psutil.Process',return_value=process), \
             patch.object(capabilities,'process_record',return_value={'pid':42,'created':3,'exe':'app.exe'}):
            self.assertIsNotNone(_real_target(bridge.read_state(),hwnd=12))

    def test_native_permission_ui_can_never_be_an_input_target(self):
        import win32gui, win32process
        process = Mock();process.cmdline.return_value=['pythonw.exe','-m','computer_mcp.consent']
        with patch.object(win32process,'GetWindowThreadProcessId',return_value=(1,42)), \
             patch('psutil.Process',return_value=process):
            self.assertIn('cannot be automated',_real_target(bridge.read_state(),hwnd=12))

    def test_response_metadata_does_not_capture_without_privacy(self):
        self.scope('input')
        from computer_mcp.core.state import ComputerState
        state=ComputerState()
        with patch('computer_mcp.core.state.capture_screenshot',side_effect=AssertionError('privacy leak')):
            self.assertEqual(state.get_state(),{})

if __name__=='__main__': unittest.main()
