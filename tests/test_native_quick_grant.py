import os
import unittest
from unittest.mock import patch
from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, consent_ipc
from computer_mcp.quick_grant import COMMON, QuickGrantPolicy


class NativeQuickGrantTests(AuthorityCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.identity = agent_session.register()['id']
        self.app = capabilities.process_record(os.getpid())
        self.policy = QuickGrantPolicy()

    def test_no_preference_needs_selection(self):
        self.assertEqual(self.policy.resolve()['status'], 'ambiguous')

    def test_process_reuse_requires_confirmation(self):
        self.policy.remember(self.identity, self.app)
        with patch.object(capabilities, 'process_record', return_value=dict(self.app, created=0)):
            self.assertEqual(self.policy.resolve()['status'], 'denied')

    def test_only_saved_agent_can_match(self):
        self.policy.remember(self.identity, self.app)
        with patch.object(agent_session, 'active', return_value=[{'id':'other'}]):
            self.assertEqual(self.policy.resolve()['status'], 'ambiguous')

    def test_untrusted_request_rejected(self):
        with self.assertRaises(PermissionError):
            consent_ipc.dispatch(dict(command='quick_grant'),os.getpid())

    def test_native_click_uses_fixed_scopes(self):
        from computer_mcp import permission_bridge as bridge
        self.policy.remember(self.identity, self.app)
        with patch.object(consent_ipc,'_native_client',return_value=True):
            result=consent_ipc.dispatch(dict(command='quick_grant',scopes=['process']),os.getpid())
        self.assertEqual(result['status'],'granted')
        self.assertEqual(set(bridge.read_state()['authorization']['scopes']),set(COMMON))
