import unittest
from unittest.mock import patch
from computer_mcp import vision_state as V
from computer_mcp.result_outcome import normalize


class FailureSemanticsTests(unittest.TestCase):
    def test_wait_for_disappearance_does_not_report_absent_on_timeout(self):
        raw = getattr(V.wait_template, '__wrapped__', V.wait_template)
        with patch.object(V, 'match_template', return_value={'success': True, 'found': True}), \
                patch.object(V.time, 'monotonic', side_effect=[0, .001, .02, .02]), \
                patch.object(V._execution, 'sleep'), patch.object(V, '_bump'):
            result = raw('fixture', timeout_ms=10, appear=False)
        self.assertFalse(result['matched'])
        self.assertEqual(result['verdict'], 'timeout')
        self.assertEqual(result['outcome'], 'failed')
        self.assertTrue(result['last_found'])

    def test_ambiguous_wait_is_inconclusive(self):
        raw = getattr(V.wait_template, '__wrapped__', V.wait_template)
        with patch.object(V, 'match_template', return_value={'success': True, 'reason': 'ambiguous'}), \
                patch.object(V.time, 'monotonic', side_effect=[0, .001, .02, .02]), \
                patch.object(V._execution, 'sleep'), patch.object(V, '_bump'):
            result = raw('fixture', timeout_ms=10, appear=False)
        self.assertEqual(result['verdict'], 'inconclusive')

    def test_legacy_flags_remain_compatible_but_outcome_is_failed(self):
        original = {'success': True, 'matched': False, 'code': 'condition_timeout'}
        result = normalize(original)
        self.assertTrue(result['success'])
        self.assertEqual(result['outcome'], 'failed')
        self.assertNotIn('outcome', original)

    def test_postcondition_failure_is_not_execution_success(self):
        self.assertEqual(normalize({'ok': True, 'verification': 'no_effect'})['outcome'], 'failed')
