"""v1.4.1: the three new tools route correctly and verify what they claim."""
import unittest
from unittest.mock import Mock, patch

from authority_fixture import AuthorityCase
from computer_mcp import snapshots as S
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch


def run(name, **arguments):
    return dispatch(name, arguments, computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get('result')


class ToolRegistrationTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
    def test_tools_are_registered_with_the_right_shape(self):
        from computer_mcp import tool_registry
        ranked = tool_registry.get('find_elements_ranked')
        state = tool_registry.get('element_state')
        action = tool_registry.get('element_action')
        self.assertTrue(ranked.read_only and state.read_only)
        self.assertFalse(action.read_only)
        self.assertIn('input', action.effects)
        self.assertEqual(len(tool_registry.all_tools()), 95)

    def test_action_enum_covers_the_supported_set(self):
        from computer_mcp import tool_registry
        schema = tool_registry.get('element_action').schema
        self.assertEqual(set(schema['properties']['action']['enum']),
                         {'auto', 'invoke', 'set_value', 'toggle', 'select', 'focus', 'click'})


class ElementStateTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
    def test_state_comes_from_the_control_not_a_screenshot(self):
        target = dict(hwnd=11, path='0/1', x=10, y=10, w=40, h=20)
        state = dict(name='OK', type='ButtonControl', enabled=True, offscreen=False,
                     focused=False, focusable=True, value=None, toggle=None, selected=None,
                     expanded=None, supported={'invoke': True})
        with patch.object(S, 'resolve', return_value=target), \
                patch('computer_mcp.element_ops.read_state', return_value=state) as read:
            result = run('element_state', ref='abc:0')
        read.assert_called_once_with(11, '0/1')
        self.assertTrue(result['ok'])
        self.assertEqual(result['state']['name'], 'OK')

    def test_stale_reference_is_reported_as_stale_element(self):
        with patch.object(S, 'resolve', side_effect=S.StaleReference('expired')):
            result = run('element_state', ref='abc:0')
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'stale_element')

    def test_visual_candidate_without_path_is_rejected_clearly(self):
        with patch.object(S, 'resolve', return_value=dict(hwnd=11, x=1, y=2)):
            result = run('element_state', ref='abc:0')
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'no_path')


class ElementActionTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        # The real takeover guard reacts to whatever the agent itself is doing
        # with the mouse; pin it idle so this test measures routing only.
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
    target = dict(hwnd=11, path='0/1', x=10, y=10, w=40, h=20)

    def test_set_value_is_verified_by_reading_back(self):
        before = dict(value='old', toggle=None, selected=None, supported={'value': True})
        after = dict(value='new', toggle=None, selected=None, supported={'value': True})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', side_effect=[before, after]), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='set_value', method='uia')):
            result = run('element_action', ref='abc:0', action='set_value', value='new')
        self.assertTrue(result['ok'])
        self.assertEqual(result['verification'], 'verified_success')

    def test_set_value_that_did_not_stick_is_no_effect(self):
        same = dict(value='old', toggle=None, selected=None, supported={'value': True})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', side_effect=[same, same]), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='set_value', method='uia')):
            result = run('element_action', ref='abc:0', action='set_value', value='new')
        self.assertEqual(result['verification'], 'no_effect')

    def test_toggle_flip_is_verified(self):
        before = dict(toggle='off', value=None, selected=None, supported={'toggle': True})
        after = dict(toggle='on', value=None, selected=None, supported={'toggle': True})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', side_effect=[before, after]), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='toggle', method='uia')):
            result = run('element_action', ref='abc:0', action='toggle')
        self.assertEqual(result['verification'], 'verified_success')

    def test_click_stays_honest_about_verification(self):
        before = dict(value=None, toggle=None, selected=None, supported={})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', side_effect=[before, before]), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='click', method='mouse')):
            result = run('element_action', ref='abc:0', action='click')
        self.assertEqual(result['verification'], 'executed_unverified')

    def test_perform_failure_is_surfaced(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=False, error='no Invoke pattern')):
            result = run('element_action', ref='abc:0', action='invoke')
        self.assertFalse(result['ok'])
        self.assertIn('Invoke', result['error'])


class RankedTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
    def test_include_state_enriches_ranked_candidates(self):
        payload = dict(ok=True, hwnd=11, ambiguous=True, candidates=[
            dict(name='OK', path='0/1', source='uia', score=0.9, x=1, y=2, w=3, h=4),
            dict(name='OK', source='ocr', score=0.88, x=50, y=60, w=3, h=4),
        ])
        with patch('computer_mcp.zones.sense_fallback.find_element', return_value=payload), \
                patch('computer_mcp.element_ops.read_state',
                      return_value=dict(enabled=True, name='OK')):
            result = run('find_elements_ranked', query='OK', include_state=True)
        self.assertEqual(result['candidates'][0]['state']['name'], 'OK')
        self.assertNotIn('state', result['candidates'][1])
        self.assertTrue(result['ambiguous'])


if __name__ == '__main__':
    unittest.main()
