"""v1.4.1rc3: reference integrity, target resolution, execution truth (C01-C08)."""
import unittest
from unittest.mock import Mock, PropertyMock, patch

from authority_fixture import AuthorityCase
from computer_mcp import snapshots as S
from computer_mcp import ui_ext as U
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones import sense_fallback as SF
from computer_mcp.zones.dispatch import ComputerState, dispatch

IDENTITY = (11, 21, 123.0, 'Win', (0, 0, 300, 200), 144)


def call(tool, **arguments):
    return dispatch(tool, dict(arguments), computer_state=ComputerState(),
                    mouse_controller=MouseController(),
                    keyboard_controller=KeyboardController()).get("result") or {}


class ReferenceIntegrityTests(unittest.TestCase):
    def setUp(self):
        S._snapshots.clear()

    def attach(self, nodes, identity=IDENTITY):
        with patch.object(S, 'window_identity', return_value=identity):
            return S.attach(11, nodes)

    def test_c01_geometry_hash_is_not_compared_with_automation_id(self):
        """C01: element_id is a geometry hash; comparing it to AutomationId lied."""
        node = dict(x=1, y=1, w=10, h=10, name='OK', type='ButtonControl',
                    path='0/1', automation_id='btn-7', element_id='deadbeef')
        ref = self.attach([node])['candidates'][0]['ref']
        fresh = dict(name='OK', type='ButtonControl', x=1, y=1, w=10, h=10,
                     path='0/1', automation_id='btn-7')
        with patch.object(S, 'window_identity', return_value=IDENTITY), \
                patch.object(U, 'control_at_path', return_value=fresh):
            self.assertEqual(S.resolve(ref, 11)['name'], 'OK')

    def test_c01_fusion_keeps_the_automation_id(self):
        candidate = SF._norm_cand(dict(x=1, y=1, w=10, h=10, name='OK',
                                       automation_id='btn-7', path='0/1'), 'uia', 0.9)
        self.assertEqual(candidate['automation_id'], 'btn-7')

    def test_c02_moved_window_reports_the_new_centre(self):
        """C02: the old centre survived relocation and pointed at nothing."""
        node = dict(x=10, y=10, w=40, h=20, name='OK', type='ButtonControl',
                    path='0/1', cx=30, cy=20)
        ref = self.attach([node])['candidates'][0]['ref']
        moved = (*IDENTITY[:4], (500, 400, 800, 600), 144)
        fresh = dict(name='OK', type='ButtonControl', x=510, y=410, w=40, h=20, path='0/1')
        with patch.object(S, 'window_identity', return_value=moved), \
                patch.object(U, 'control_at_path', return_value=fresh):
            target = S.resolve(ref, 11)
        self.assertEqual((target['cx'], target['cy']), (530, 420))

    def test_c07_a_short_lived_hit_does_not_evict_a_long_lived_reference(self):
        """C07: the snapshot lifetime must be the longest reference inside it."""
        nodes = [dict(x=1, y=1, w=10, h=10, name='Btn', type='Button', path='0/1'),
                 dict(x=5, y=5, w=10, h=10, name='文字')]
        with patch.object(S, 'screen_fingerprint', return_value='same'):
            first = self.attach(nodes)
        key = first['candidates'][0]['ref'].split(':')[0]
        self.assertEqual(S._snapshots[key]['ttl'], S.REF_TTL_UIA)

        clock = [0.0]
        with patch.object(S.time, 'monotonic', side_effect=lambda: clock[0]), \
                patch.object(S, 'screen_fingerprint', return_value='same'):
            clock[0] = 7.0
            self.attach([dict(x=1, y=1, w=10, h=10, name='其他')])
        self.assertIn(key, S._snapshots, 'a 7 second old snapshot evicted a 120 second reference')

    def test_c03_query_without_hwnd_still_returns_a_reference(self):
        """C03: UIA used the foreground window but never attached a snapshot."""
        found = dict(ok=True, found=1, target=dict(name='确定', path='0/1', x=1, y=1, w=5, h=5),
                     candidates=[dict(name='确定', path='0/1', x=1, y=1, w=5, h=5)])
        with patch('win32gui.GetForegroundWindow', return_value=4242), \
                patch.object(U, 'ui_find', return_value=found), \
                patch.object(S, 'window_identity', return_value=IDENTITY):
            result = SF.find_element('确定')
        self.assertTrue(result['ok'])
        self.assertTrue(result['candidates'][0].get('ref'), 'no reference was attached')
        self.assertEqual(result['hwnd'], 4242)


class TargetResolutionTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        self.target = dict(hwnd=11, path='0/1', x=1, y=2, w=10, h=10)

    def test_c05_named_target_that_cannot_be_found_types_nothing(self):
        """C05: a named input box that is missing must not receive keystrokes."""
        missing = dict(ok=True, found=0, target=None, candidates=[])
        with patch.object(U, 'ui_find', return_value=missing), \
                patch('computer_mcp.actions.keyboard.type_text') as type_text:
            result = call('type_verified', name='不存在的输入框', text='hello')
        type_text.assert_not_called()
        self.assertFalse(result['ok'])
        self.assertEqual(result['code'], 'no_target')

    def test_c06_execute_verified_refuses_two_same_name_controls(self):
        """C06: the ambiguity rule must also cover execute_verified."""
        found = dict(target=dict(name='确定', path='0/1', x=1, y=1, w=5, h=5),
                     candidates=[dict(name='确定', path='0/1', x=1, y=1, w=5, h=5),
                                 dict(name='确定', path='0/9', x=50, y=50, w=5, h=5)])
        with patch.object(U, 'ui_find', return_value=found):
            result = call('execute_verified', query='确定', action='click')
        self.assertEqual(result.get('code'), 'ambiguous')

    def test_c04_expired_reference_is_not_proof_of_absence(self):
        """C04: a dead reference alone must not produce verified_success."""
        with patch.object(S, 'resolve', side_effect=S.StaleReference('expired')), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            result = call('execute_verified', ref='dead:0', action='click',
                          expect=dict(kind='absent'), timeout_ms=80)
        self.assertNotEqual(result['status'], 'verified_success')

    def test_c04_absence_confirmed_by_recheck(self):
        found = dict(ok=True, found=0, target=None, candidates=[])
        with patch.object(S, 'resolve', side_effect=S.StaleReference('expired')), \
                patch.object(U, 'ui_find', return_value=found), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            result = call('execute_verified', ref='dead:0', query='已关闭的对话框',
                          action='click', expect=dict(kind='absent'), timeout_ms=80)
        self.assertEqual(result['status'], 'verified_absent')
        self.assertFalse(result['action_executed'])
        self.assertTrue(result['observation_only'])


class ScrollPatternTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        for name in ('GetWindowRect',):
            patcher = patch(f'win32gui.{name}', return_value=(0, 0, 400, 300))
            patcher.start()
            self.addCleanup(patcher.stop)
        scroll = patch.object(MouseController, 'scroll', autospec=True)
        self.wheel = scroll.start()
        self.addCleanup(scroll.stop)
        position = patch.object(MouseController, 'position', new_callable=PropertyMock,
                                create=True)
        position.start()
        self.addCleanup(position.stop)

    def test_c08_no_wheel_when_scroll_item_already_scrolled(self):
        """C08: a successful ScrollIntoView must not be followed by a wheel."""
        outside = dict(name='目标', type='ListItem', x=0, y=900, w=10, h=10, path='0/9')
        inside = dict(name='目标', type='ListItem', x=0, y=100, w=10, h=10, path='0/9')
        trees = [dict(ok=True, nodes=[outside]), dict(ok=True, nodes=[inside])]
        with patch.object(U, 'ui_tree', side_effect=trees), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='scroll_into_view')):
            result = call('scroll_into_view', query='目标', settle_ms=0)
        self.wheel.assert_not_called()
        self.assertTrue(result['found'])


if __name__ == '__main__':
    unittest.main()
