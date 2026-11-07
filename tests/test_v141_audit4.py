"""v1.4.1rc4: absence checks, focus discipline, honest statuses (D01-D06)."""
import unittest
from unittest.mock import Mock, PropertyMock, patch

from authority_fixture import AuthorityCase
from computer_mcp import snapshots as S
from computer_mcp import ui_ext as U
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch


def call(tool, **arguments):
    return dispatch(tool, dict(arguments), computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get("result") or {}


class AbsenceTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_d01_uia_error_is_not_proof_of_absence(self):
        """A failed scan must not read as 'the element is gone'."""
        error = dict(error='could not resolve window')
        with patch.object(S, 'resolve', side_effect=S.StaleReference('expired')), \
                patch.object(U, 'ui_find', return_value=error), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            result = call('execute_verified', ref='dead:0', query='按钮', action='click',
                          expect=dict(kind='absent'), timeout_ms=80)
        self.assertEqual(result['status'], 'executed_unverified')

    def test_d02_query_only_absence_can_succeed(self):
        """Name-only absence checks used to loop until the timeout."""
        gone = dict(ok=True, found=0, target=None, candidates=[])
        with patch.object(U, 'ui_find', return_value=gone), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            result = call('execute_verified', query='已关闭的对话框', action='click',
                          expect=dict(kind='absent'), timeout_ms=120)
        self.assertEqual(result['status'], 'verified_absent')
        self.assertFalse(result['action_executed'])

    def test_d02_query_only_absence_reports_presence(self):
        there = dict(ok=True, found=1, target=dict(name='对话框', path='0/1', x=1, y=1, w=5, h=5),
                     candidates=[dict(name='对话框', path='0/1', x=1, y=1, w=5, h=5)])
        with patch.object(U, 'ui_find', return_value=there), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            result = call('execute_verified', query='对话框', action='click',
                          expect=dict(kind='absent'), timeout_ms=80)
        self.assertNotIn(result['status'], ('verified_absent', 'verified_success'))


class FocusDisciplineTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        self.target = dict(hwnd=11, path='0/1', x=1, y=1, w=5, h=5)

    def test_d03_focus_failure_stops_typing(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=False, error='SetFocus failed')), \
                patch('computer_mcp.element_ops.read_state',
                      return_value=dict(focused=False, value='')), \
                patch('computer_mcp.actions.keyboard.type_text') as type_text:
            result = call('type_verified', ref='r:0', text='hello')
        type_text.assert_not_called()
        self.assertEqual(result['code'], 'focus_failed')

    def test_d03_already_focused_control_is_typed_into(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=False, error='SetFocus refused')), \
                patch('computer_mcp.element_ops.read_state',
                      side_effect=[dict(focused=True, value=''),
                                   dict(focused=True, value='hello')]), \
                patch('computer_mcp.actions.keyboard.type_text',
                      return_value=dict(success=True)) as type_text:
            result = call('type_verified', ref='r:0', text='hello')
        type_text.assert_called_once()
        self.assertTrue(result['ok'])

    def test_d03_execute_verified_type_honours_focus(self):
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=False, error='SetFocus failed')), \
                patch('computer_mcp.element_ops.read_state',
                      return_value=dict(focused=False, value='')), \
                patch('computer_mcp.actions.keyboard.type_text') as type_text:
            result = call('execute_verified', ref='r:0', action='type', value='hi')
        type_text.assert_not_called()
        self.assertFalse(result['action_executed'])


class TrimAndCountTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        self.target = dict(hwnd=11, path='0/1', x=1, y=1, w=5, h=5)

    def test_d06_action_state_is_trimmed(self):
        big = dict(value='x' * 4000, supported={})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value=big), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='invoke')):
            result = call('element_action', ref='r:0', action='invoke')
        self.assertTrue(result['after']['value_truncated'])
        self.assertEqual(result['after']['value_length'], 4000)

    def test_d06_execute_verified_before_is_trimmed(self):
        big = dict(value='y' * 4000, supported={})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value=big), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='invoke')):
            result = call('execute_verified', ref='r:0', action='invoke', timeout_ms=80)
        self.assertTrue(result['before']['value_truncated'])

    def test_d05_scroll_counts_only_real_wheel_events(self):
        outside = dict(name='目标', type='ListItem', x=0, y=900, w=10, h=10, path='0/9')
        inside = dict(name='目标', type='ListItem', x=0, y=100, w=10, h=10, path='0/9')
        trees = [dict(ok=True, nodes=[outside]), dict(ok=True, nodes=[inside])]
        with patch('win32gui.GetWindowRect', return_value=(0, 0, 400, 300)), \
                patch.object(U, 'ui_tree', side_effect=trees), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='scroll_into_view')), \
                patch.object(MouseController, 'scroll', autospec=True) as wheel, \
                patch.object(MouseController, 'position', new_callable=PropertyMock, create=True):
            result = call('scroll_into_view', query='目标', settle_ms=0)
        wheel.assert_not_called()
        self.assertEqual(result['scrolls'], 0)
        self.assertEqual(result['uia_scrolls'], 1)


if __name__ == '__main__':
    unittest.main()
