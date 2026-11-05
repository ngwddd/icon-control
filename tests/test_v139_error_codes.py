"""v1.3.9-alpha: machine-readable reason codes and permission-service health.

A blocked call must say *why* it was blocked: "the user did not grant me" and
"the permission service is unreachable" need different recovery, and a malformed
argument is not a permission problem at all.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, permission


class UnauthorizedStatusTests(AuthorityCase, unittest.TestCase):
    def test_status_reports_authority_unavailable_with_health_block(self):
        state = permission.status(force=True)
        self.assertFalse(state['granted'])
        self.assertEqual(state['code'], 'authority_unavailable')
        self.assertIn('authority', state)
        health = state['authority']
        for key in ('ok', 'probed', 'port', 'checked_at'):
            self.assertIn(key, health)
        # The status() hot path must not open sockets; only a probe fills these.
        self.assertFalse(health['probed'])
        self.assertIsNone(health['ok'])

    def test_explicit_probe_reports_a_boolean(self):
        health = permission.authority(probe=True, ttl=0.0)
        self.assertTrue(health['probed'])
        self.assertIsInstance(health['ok'], bool)
        self.assertIsInstance(health['bridge_up'], bool)

    def test_reason_code_mapping_covers_every_documented_reason(self):
        self.assertEqual(permission.code_for_reason('Lease expired'), 'permission_denied')
        self.assertEqual(permission.code_for_reason('Approval belongs to another Agent session'),
                         'permission_denied')
        self.assertEqual(permission.code_for_reason('Live permission authority unavailable or revoked'),
                         'authority_unavailable')
        self.assertEqual(permission.code_for_reason('Missing, expired or unauthenticated bridge state'),
                         'authority_unavailable')
        self.assertIn(permission.code_for_reason(None), permission.ERROR_CODES)


class AuthorizedStatusTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_granted_status_carries_no_failure_code(self):
        state = permission.status(force=True)
        self.assertTrue(state['granted'])
        self.assertNotIn('code', state)
        self.assertIn('authority', state)

    def test_foreign_session_denial_is_permission_denied(self):
        with patch.object(agent_session, 'current', return_value='f' * 48):
            state = permission.status(force=True)
        self.assertFalse(state['granted'])
        self.assertEqual(state['code'], 'permission_denied')


class CheckToolCodeTests(AuthorityCase, unittest.TestCase):
    def test_unknown_tool_is_invalid_argument(self):
        denial = permission.check_tool('definitely_not_a_tool', {})
        self.assertIsNotNone(denial)
        self.assertEqual(denial['code'], 'invalid_argument')

    def test_unauthorized_input_tool_reports_a_known_code(self):
        denial = permission.check_tool('click', {'x': 10, 'y': 10})
        self.assertIsNotNone(denial)
        self.assertTrue(denial['blocked'])
        self.assertIn(denial['code'], permission.ERROR_CODES)
        self.assertEqual(denial['code'], 'authority_unavailable')
        # A blocked call may probe once: the caller needs to know whether the
        # service is down or the user simply has not approved anything.
        self.assertTrue(denial['authority']['probed'])


class BridgeHealthTests(unittest.TestCase):
    def test_health_is_read_only_and_complete(self):
        from computer_mcp import permission_bridge as bridge
        health = bridge.health()
        for key in ('pid', 'transport', 'port', 'clients', 'revision', 'uptime_s'):
            self.assertIn(key, health)
        self.assertEqual(health['transport'], 'http')
        self.assertIsInstance(health['uptime_s'], float)
        self.assertGreaterEqual(health['uptime_s'], 0.0)


if __name__ == '__main__':
    unittest.main()
