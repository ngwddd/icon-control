"""Robustness of the v1.4.0 local policy: bad state, bad home, concurrent resume."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from computer_mcp import policy


class PolicyRobustnessCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.home = Path(self.temp.name)
        (self.home / 'state').mkdir()
        self.env = patch.dict(os.environ, ICON_CONTROL_HOME=str(self.home),
                              ICON_CONTROL_POLICY='local')
        self.env.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.temp.cleanup)


class CorruptStateTests(PolicyRobustnessCase):
    def test_garbage_record_falls_back_to_a_fresh_authorisation(self):
        (self.home / 'state' / 'local-policy.json').write_text('{not json', encoding='utf-8')
        self.assertTrue(policy.state()['granted'])
        self.assertGreater(policy.authorized_at(), 0)

    def test_record_with_wrong_types_is_tolerated(self):
        (self.home / 'state' / 'local-policy.json').write_text(
            json.dumps({'authorized_at': 'yesterday', 'mode': 7}), encoding='utf-8')
        self.assertTrue(policy.state()['granted'])

    def test_unreadable_stop_file_fails_closed(self):
        (self.home / 'state' / 'emergency-stop.json').write_text('garbage', encoding='utf-8')
        self.assertFalse(policy.state()['granted'])

    def test_missing_state_directory_is_created(self):
        import shutil
        shutil.rmtree(self.home / 'state')
        self.assertTrue(policy.state()['granted'])
        self.assertTrue((self.home / 'state' / 'local-policy.json').exists())


class ResumeTests(PolicyRobustnessCase):
    def test_resume_is_idempotent_and_monotonic(self):
        first = policy.resume()['authorized_at']
        second = policy.resume()['authorized_at']
        self.assertGreaterEqual(second, first)
        self.assertTrue(policy.state()['granted'])

    def test_concurrent_resume_keeps_one_record(self):
        import threading
        results = []

        def worker():
            results.append(policy.resume()['authorized_at'])

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(results), 8)
        record = json.loads((self.home / 'state' / 'local-policy.json').read_text(encoding='utf-8'))
        self.assertIn('authorized_at', record)
        self.assertTrue(policy.state()['granted'])


class ControlStatusTests(PolicyRobustnessCase):
    def test_control_status_exposes_policy_block(self):
        from computer_mcp.input_guard import KeyboardController, MouseController
        from computer_mcp.zones.dispatch import ComputerState, dispatch
        with patch('computer_mcp.control.blocking_reason', return_value=None):
            out = dispatch('control_status', {}, computer_state=ComputerState(),
                           mouse_controller=MouseController(),
                           keyboard_controller=KeyboardController())
        result = out.get('result') or {}
        self.assertEqual(result['policy'], dict(mode='local', runtime='ready'))
        self.assertIn('runtime_contract', result)

    def test_tool_effects_are_still_declared_for_audit(self):
        from computer_mcp import tool_registry
        spec = tool_registry.get('click')
        self.assertEqual(set(spec.effects), {'input'})
        self.assertTrue(spec.needs_authority({}))


if __name__ == '__main__':
    unittest.main()
