"""v1.4.1 R2: one call that executes and then proves it worked."""
import unittest
from unittest.mock import patch

from authority_fixture import AuthorityCase
from computer_mcp import snapshots as S
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones import wait_for as WF
from computer_mcp.zones.dispatch import ComputerState, dispatch


def run(name, **arguments):
    return dispatch(name, arguments, computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get('result')


class WaitAnyTests(unittest.TestCase):
    def test_first_matching_condition_wins(self):
        seen = []

        def probe(condition):
            seen.append(condition['kind'])
            return dict(ok=condition['kind'] == 'text', detail='found')

        with patch.object(WF, 'probe', side_effect=probe):
            result = WF.run(any=[dict(kind='element', element_id='x'),
                                 dict(kind='text', query='done')], timeout_ms=300)
        self.assertTrue(result['ok'])
        self.assertEqual(result['matched']['kind'], 'text')
        self.assertEqual(result['kind'], 'any')

    def test_timeout_reports_every_condition_it_tried(self):
        with patch.object(WF, 'probe', return_value=dict(ok=False, detail='no')):
            result = WF.run(any=[dict(kind='text', query='a'),
                                 dict(kind='focused', query='b')], timeout_ms=120)
        self.assertFalse(result['ok'])
        self.assertIn('text', result['detail'])
        self.assertIn('focused', result['detail'])

    def test_empty_any_is_rejected(self):
        self.assertFalse(WF.run(any=[])['ok'])


class ProbeTests(unittest.TestCase):
    def test_value_probe_reads_the_control(self):
        with patch.object(S, 'resolve', return_value=dict(hwnd=11, path='0/1')), \
                patch('computer_mcp.element_ops.read_state', return_value=dict(value='abc')):
            self.assertTrue(WF.probe(dict(kind='value', query='r:0', text='abc'))['ok'])
            self.assertFalse(WF.probe(dict(kind='value', query='r:0', text='xyz'))['ok'])


class ExecuteVerifiedTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        self.target = dict(hwnd=11, path='0/1', x=10, y=10, w=40, h=20)

    def test_value_postcondition_is_verified(self):
        states = [dict(value='old'), dict(value='new'), dict(value='new')]
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', side_effect=states), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='set_value', method='uia')):
            result = run('execute_verified', ref='r:0', action='set_value', value='new',
                         expect=dict(kind='value', text='new'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'verified_success')
        self.assertGreaterEqual(result['elapsed_ms'], 0)

    def test_missing_postcondition_reports_no_effect(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value=dict(value='old')), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='click', method='mouse')):
            result = run('execute_verified', ref='r:0', action='click',
                         expect=dict(kind='value', text='new'), timeout_ms=120)
        self.assertEqual(result['status'], 'no_effect')

    def test_without_postcondition_it_stays_honest(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value=dict(value=None)), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='click', method='mouse')):
            result = run('execute_verified', ref='r:0', action='click')
        self.assertEqual(result['status'], 'executed_unverified')

    def test_stale_target_is_target_changed(self):
        with patch.object(S, 'resolve', side_effect=S.StaleReference('moved')):
            result = run('execute_verified', ref='r:0', action='click')
        self.assertEqual(result['status'], 'target_changed')

    def test_failed_action_surfaces_the_error(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=False, error='no Invoke pattern')):
            result = run('execute_verified', ref='r:0', action='invoke')
        self.assertFalse(result['ok'])
        self.assertIn('Invoke', result['error'])


if __name__ == '__main__':
    unittest.main()
