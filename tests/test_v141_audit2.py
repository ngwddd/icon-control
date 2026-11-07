"""v1.4.1rc2 audit: the reported defects, each with the behaviour we now expect."""
import unittest
from unittest.mock import Mock, PropertyMock, patch

from authority_fixture import AuthorityCase
from computer_mcp import element_ops as EO
from computer_mcp import snapshots as S
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones import sense_fallback as SF
from computer_mcp.zones import wait_for as WF
from computer_mcp.zones.dispatch import ComputerState, dispatch


def call(tool, **arguments):
    out = dispatch(tool, dict(arguments), computer_state=ComputerState(),
                   mouse_controller=MouseController(),
                   keyboard_controller=KeyboardController())
    return out.get("result") or {}


class PatternFailureTests(unittest.TestCase):
    """B01: a command that throws must not report success."""

    class Boom:
        def Invoke(self):
            raise RuntimeError('element is not enabled')

        def Toggle(self):
            raise RuntimeError('nope')

        def Select(self):
            raise RuntimeError('nope')

        def ScrollIntoView(self):
            raise RuntimeError('nope')

    class Control:
        Name = 'OK'
        ControlTypeName = 'ButtonControl'

        def GetInvokePattern(self):
            return PatternFailureTests.Boom()

        def GetTogglePattern(self):
            return PatternFailureTests.Boom()

    def setUp(self):
        self.obj = self.Control()
        patcher = patch.object(EO, '_obj', return_value=self.obj)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_invoke_failure_is_reported(self):
        result = EO.perform(11, '0/1', 'invoke')
        self.assertFalse(result['ok'])
        self.assertIn('Invoke failed', result['error'])

    def test_toggle_failure_is_reported(self):
        result = EO.perform(11, '0/1', 'toggle')
        self.assertFalse(result['ok'])
        self.assertIn('Toggle failed', result['error'])

    def test_set_value_uses_set_value_and_reports_failure(self):
        class ValuePattern:
            IsReadOnly = False

            def SetValue(self, text):
                raise RuntimeError('write rejected')

            @property
            def Value(self):
                return ''

        self.obj.GetValuePattern = lambda: ValuePattern()
        result = EO.perform(11, '0/1', 'set_value', 'x')
        self.assertFalse(result['ok'])
        self.assertIn('SetValue failed', result['error'])

    def test_read_only_control_is_refused(self):
        class ValuePattern:
            IsReadOnly = True

            def SetValue(self, text):
                raise AssertionError('must not be called')

        self.obj.GetValuePattern = lambda: ValuePattern()
        result = EO.perform(11, '0/1', 'set_value', 'x')
        self.assertFalse(result['ok'])
        self.assertIn('read-only', result['error'])


class CandidateFieldTests(unittest.TestCase):
    """B02: the UIA path has to survive normalisation."""

    def test_normalisation_keeps_the_structural_fields(self):
        raw = dict(x=10, y=20, w=30, h=40, name='OK', type='ButtonControl',
                   path='0/2', element_id='abc')
        candidate = SF._norm_cand(raw, 'uia', 0.95)
        self.assertEqual(candidate['path'], '0/2')
        self.assertEqual(candidate['name'], 'OK')
        self.assertEqual(candidate['type'], 'ButtonControl')

    def test_mixed_batch_keeps_each_reference_at_its_own_ttl(self):
        S._snapshots.clear()
        identity = (11, 21, 123.0, 'Win', (0, 0, 300, 200), 144)
        nodes = [dict(x=1, y=1, w=10, h=10, name='Btn', type='Button', path='0/1'),
                 dict(x=50, y=50, w=10, h=10, name='文字', type=None)]
        with patch.object(S, 'window_identity', return_value=identity), \
                patch.object(S, 'screen_fingerprint', return_value='same'):
            result = S.attach(11, nodes)
        ttls = result['candidates']
        self.assertEqual(ttls[0]['ref'].split(':')[0], ttls[1]['ref'].split(':')[0])
        stored = S._snapshots[ttls[0]['ref'].split(':')[0]]
        self.assertEqual(stored['ttl_by_node'], [S.REF_TTL_UIA, S.REF_TTL_VISUAL])


class LineupTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_wait_for_any_reaches_the_implementation(self):
        """B03: the dispatch layer used to drop `any`."""
        with patch.object(WF, 'run', return_value=dict(ok=True)) as run:
            call('wait_for', kind='change', any=[dict(kind='text', query='done')])
        self.assertEqual(run.call_args.kwargs.get('any'),
                         [dict(kind='text', query='done')])


class DispatchBehaviourTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        self.target = dict(hwnd=11, path='0/1', x=1, y=2, w=10, h=10)

    def test_clear_first_types_once(self):
        """B04: select-all + delete must happen before the single type."""
        events = []
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state',
                      return_value=dict(value='', supported={})), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)), \
                patch('computer_mcp.actions.keyboard.key_down',
                      side_effect=lambda key, controller=None: events.append(('down', key))), \
                patch('computer_mcp.actions.keyboard.key_up',
                      side_effect=lambda key, controller=None: events.append(('up', key))), \
                patch('computer_mcp.actions.keyboard.key_press',
                      side_effect=lambda key, controller=None: events.append(('press', key))), \
                patch('computer_mcp.actions.keyboard.type_text',
                      side_effect=lambda text, controller=None: events.append(('type', text)) or
                      dict(success=True)):
            call('type_verified', ref='r:0', text='abc', clear_first=True)
        types = [event for event in events if event[0] == 'type']
        self.assertEqual(len(types), 1, events)
        self.assertLess(events.index(('press', 'delete')), events.index(('type', 'abc')))

    def test_absent_without_reference_is_not_a_success(self):
        """B05: resolving nothing must not prove the element disappeared."""
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value={}), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            result = call('execute_verified', ref=None, action='click',
                          expect=dict(kind='absent'), timeout_ms=80)
        self.assertNotEqual(result['status'], 'verified_success')

    def test_two_same_name_controls_are_ambiguous(self):
        """B07: do not act on the first of two identical buttons."""
        found = dict(target=dict(name='确定', path='0/1', x=1, y=1, w=5, h=5),
                     candidates=[dict(name='确定', path='0/1', x=1, y=1, w=5, h=5),
                                 dict(name='确定', path='0/9', x=50, y=50, w=5, h=5)])
        with patch('computer_mcp.ui_ext.ui_find', return_value=found):
            result = call('element_action', name='确定', action='invoke')
        self.assertEqual(result.get('code'), 'ambiguous')
        self.assertEqual(len(result.get('candidates') or []), 2)

    def test_name_lookup_without_hwnd_uses_the_foreground_window(self):
        """B06: without hwnd the call still has to know which window it priced."""
        found = dict(target=dict(name='OK', path='0/1', x=1, y=1, w=5, h=5),
                     candidates=[dict(name='OK', path='0/1', x=1, y=1, w=5, h=5)])
        with patch('computer_mcp.ui_ext.ui_find', return_value=found) as ui_find, \
                patch('win32gui.GetForegroundWindow', return_value=4242), \
                patch('computer_mcp.element_ops.read_state', return_value=dict(value='')), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)):
            call('element_state', name='OK')
        self.assertEqual(ui_find.call_args.kwargs.get('hwnd'), 4242)

    def test_unchanged_value_is_not_a_success(self):
        """B08: text that was already there is not proof of typing."""
        same = dict(value='abc', supported={})
        with patch.object(S, 'resolve', return_value=self.target), \
                patch('computer_mcp.element_ops.read_state', return_value=same), \
                patch('computer_mcp.element_ops.perform', return_value=dict(ok=True)), \
                patch('computer_mcp.actions.keyboard.type_text',
                      return_value=dict(success=True)):
            result = call('type_verified', ref='r:0', text='abc')
        self.assertEqual(result['verification'], 'no_effect')


class RankingTests(unittest.TestCase):
    def test_tie_prefers_the_smaller_control(self):
        """B11: a big pane carrying the label is not the button."""
        panel = dict(x=0, y=0, w=800, h=600, cx=400, cy=300, score=0.9, source='uia')
        button = dict(x=10, y=10, w=40, h=20, cx=30, cy=20, score=0.9, source='uia')
        self.assertIs(SF._rank([panel, button])[0], button)


class TrimTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)

    def test_long_values_are_summarised_by_default(self):
        target = dict(hwnd=11, path='0/1')
        big = dict(value='x' * 5000, supported={})
        with patch.object(S, 'resolve', return_value=target), \
                patch('computer_mcp.element_ops.read_state', return_value=big):
            result = call('element_state', ref='r:0')
        state = result['state']
        self.assertIsNone(state['value'])
        self.assertEqual(state['value_length'], 5000)
        self.assertTrue(state['value_truncated'])

    def test_full_returns_the_whole_value(self):
        target = dict(hwnd=11, path='0/1')
        big = dict(value='x' * 5000, supported={})
        with patch.object(S, 'resolve', return_value=target), \
                patch('computer_mcp.element_ops.read_state', return_value=big):
            result = call('element_state', ref='r:0', full=True)
        self.assertEqual(len(result['state']['value']), 5000)


class AutomationIdTests(unittest.TestCase):
    """B09: a reordered list must not silently rebind the reference."""

    def test_changed_automation_id_is_stale(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _patch

        from computer_mcp import snapshots as snaps
        from computer_mcp import ui_ext

        with tempfile.TemporaryDirectory():
            snaps._snapshots.clear()
            identity = (11, 21, 123.0, 'Win', (0, 0, 300, 200), 144)
            nodes = [dict(x=1, y=1, w=10, h=10, name='行', type='ListItem',
                          path='0/1', automation_id='row-7')]
            with _patch.object(snaps, 'window_identity', return_value=identity):
                ref = snaps.attach(11, nodes)['candidates'][0]['ref']
            fresh = dict(name='行', type='ListItem', x=1, y=1, w=10, h=10,
                         path='0/1', automation_id='row-9')
            with _patch.object(snaps, 'window_identity', return_value=identity), \
                    _patch.object(ui_ext, 'control_at_path', return_value=fresh):
                with self.assertRaises(snaps.StaleReference):
                    snaps.resolve(ref, 11)


if __name__ == '__main__':
    unittest.main()
