"""v1.3.9-beta: revocation must be monotonic, persisted and final.

A revoke while a macro is running, a bridge restart, or a cached payload from
before the revoke must all be visible to the next authority check.
"""
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from authority_fixture import AuthorityCase, approval
from computer_mcp import execution, permission, security, trust
from computer_mcp import permission_bridge as bridge


class RevocationGenerationTests(AuthorityCase, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._saved = (bridge._revocation_generation, bridge._revoked_at)
        bridge._revocation_generation = 0
        bridge._revoked_at = 0.0
        self.addCleanup(lambda: setattr(bridge, '_revocation_generation', self._saved[0]))
        self.addCleanup(lambda: setattr(bridge, '_revoked_at', self._saved[1]))

    def _grant(self):
        bridge.write_state(True, client='fixture', event='action',
                           authorization=approval())
        return bridge.read_state()

    def test_grant_carries_a_generation(self):
        state = self._grant()
        self.assertEqual(state['revocation_generation'], 0)
        self.assertEqual(state['revoked_at'], 0.0)

    def test_revoke_increments_the_generation_and_persists_it(self):
        self._grant()
        bridge.write_state(False, client='fixture', event='action')
        state = bridge.read_state()
        self.assertEqual(state['revocation_generation'], 1)
        self.assertGreater(state['revoked_at'], 0)
        self.assertEqual(bridge._load_revocation_generation(), 1)

    def test_second_revoke_keeps_counting(self):
        self._grant()
        bridge.write_state(False, client='fixture', event='action')
        bridge.write_state(True, client='fixture', event='action', authorization=approval())
        bridge.write_state(False, client='fixture', event='action')
        self.assertEqual(bridge.read_state()['revocation_generation'], 2)

    def test_status_exposes_the_revocation_block(self):
        self._grant()
        state = permission.status(force=True)
        self.assertTrue(state['granted'])
        self.assertIn('revocation', state)
        self.assertEqual(state['revocation']['generation'], 0)

    def test_revoked_state_is_denied_with_a_reason(self):
        self._grant()
        bridge.write_state(False, client='fixture', event='action')
        state = permission.status(force=True)
        self.assertFalse(state['granted'])
        self.assertEqual(state['code'], 'permission_revoked')
        self.assertIn('revocation', state)


class ExecutionStampTests(unittest.TestCase):
    def _state(self, **extra):
        base = dict(granted=True, session='s' * 16, revision=3, revocation_generation=0)
        base.update(extra)
        return base

    def test_stamp_includes_the_generation(self):
        first = execution.authority_stamp(self._state())
        second = execution.authority_stamp(self._state(revocation_generation=1))
        self.assertNotEqual(first, second)
        self.assertEqual(first[0][2], 0)

    def test_task_stamp_mismatch_cancels_execution(self):
        with patch.object(execution, '_current') as current:
            current.get.return_value = dict(generation=0,
                                            revision=('s' * 16, 3, 0),
                                            tool='click', arguments={})
            with patch('computer_mcp.control.status', return_value={'generation': 0}):
                # Same snapshot: allowed.
                execution.authority_stamp(self._state())
                # Generation moved: cancelled.
                with self.assertRaises(permission.PermissionDenied):
                    execution.authority_stamp(self._state(revocation_generation=1))

    def test_revocation_releases_held_input(self):
        with patch('computer_mcp.input_guard._held_controllers', {object()}), \
                patch('computer_mcp.input_guard.release_all') as release:
            with self.assertRaises(permission.PermissionDenied):
                execution.authority_stamp(self._state(granted=False))
        release.assert_called_once()

    def test_revocation_without_held_input_touches_nothing(self):
        with patch('computer_mcp.input_guard._held_controllers', set()), \
                patch('computer_mcp.input_guard.release_all') as release:
            with self.assertRaises(permission.PermissionDenied):
                execution.authority_stamp(self._state(granted=False))
        release.assert_not_called()

    def test_takeover_stamp_mismatch_releases_held_input(self):
        with patch.object(execution, '_current') as current, \
                patch('computer_mcp.control.status', return_value={'generation': 0}), \
                patch('computer_mcp.input_guard._held_controllers', {object()}), \
                patch('computer_mcp.input_guard.release_all') as release:
            current.get.return_value = dict(generation=0,
                                            revision=('s' * 16, 3, 0),
                                            tool='click', arguments={})
            with self.assertRaises(permission.PermissionDenied):
                execution.authority_stamp(self._state(revocation_generation=1))
        release.assert_called_once()


class TrustRevocationTests(AuthorityCase, unittest.TestCase):
    def _advance_bridge_generation(self, generation=5, revoked_at=None):
        payload = dict(granted=False, revision=generation,
                       revocation_generation=generation,
                       revoked_at=revoked_at or time.time(),
                       source='bridge', checked_at_ts=time.time())
        payload['signature'] = security.signature(payload, security.load_token())
        path = bridge.STATE_PATH
        with open(path, 'w', encoding='utf-8') as handle:
            json.dump(payload, handle)

    def test_bridge_revocation_beats_an_earlier_trust(self):
        trust.grant(confirm=lambda: True)
        self.assertTrue(trust.validate()['ok'])
        self._advance_bridge_generation()
        state = trust.validate()
        self.assertFalse(state['ok'])
        self.assertIn('revoked', state['reason'])

    def test_trust_records_the_generation_it_was_granted_at(self):
        self._advance_bridge_generation(generation=2)
        record = trust.grant(confirm=lambda: True)
        self.assertEqual(record['revocation_generation'], 2)
        state = trust.validate()
        self.assertTrue(state['ok'], f"unexpected: {state}")
        self._advance_bridge_generation(generation=3)
        self.assertFalse(trust.validate()['ok'])


if __name__ == '__main__':
    unittest.main()
