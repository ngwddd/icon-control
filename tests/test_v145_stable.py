"""Stable identity and strict mouse-button regressions without real input."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from pynput.mouse import Button
from computer_mcp.core.utils import button_from_string
from computer_mcp.core.argument_error import ArgumentError
from computer_mcp.actions import mouse as A
from computer_mcp import ui_ext as U, vision_state as V

spec = importlib.util.spec_from_file_location('stable_gate', Path(__file__).resolve().parents[1] / 'tools/release_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


class TagTests(unittest.TestCase):
    def check(self, version, tag, stable=False):
        errors = []
        gate.check_tag(errors, version, tag, stable)
        return errors

    def test_stable_tag_cannot_wrap_rc_package(self):
        self.assertTrue(self.check('1.4.5rc2', 'v1.4.5'))

    def test_exact_stable_identity_is_accepted(self):
        self.assertEqual(self.check('1.4.5', 'v1.4.5', True), [])

    def test_wrong_version_tag_is_rejected(self):
        self.assertTrue(self.check('1.4.5', 'v1.4.6'))

    def test_prerelease_tags_cannot_be_promoted_to_stable(self):
        self.assertTrue(self.check('1.4.5rc2', 'v1.4.5rc2', True))

    def test_candidate_identity_can_still_be_checked(self):
        self.assertEqual(self.check('1.4.5rc2', 'v1.4.5rc2'), [])

    def test_dev_and_local_packages_cannot_be_stable(self):
        for version in ('1.4.5.dev1', '1.4.5+local', '1.4.5a1', '1.4.5.post1'):
            with self.subTest(version=version):
                self.assertTrue(self.check(version, 'v1.4.5', True))

    def test_stable_requires_explicit_tag(self):
        self.assertTrue(self.check('1.4.5', None, True))


class ButtonTests(unittest.TestCase):
    def test_canonical_names_and_normalization(self):
        for name, expected in [('left', Button.left), ('right', Button.right), ('middle', Button.middle),
                               (' RIGHT ', Button.right)]:
            self.assertEqual(button_from_string(name), expected)

    def test_invalid_buttons_are_not_left_clicks(self):
        for value in ('rigth', '', '1', 'wheel', None, 1, True, {}):
            with self.subTest(value=value), self.assertRaises(ArgumentError) as caught:
                button_from_string(value)
            self.assertEqual(caught.exception.code, 'invalid_argument')

    def test_coordinate_click_rejects_before_any_movement(self):
        raw = getattr(A.click, '__wrapped__', A.click)
        mouse = Mock()
        with patch('win32gui.WindowFromPoint') as owner, self.assertRaises(ArgumentError):
            raw(button='rigth', controller=mouse, x=100, y=100)
        owner.assert_not_called()
        mouse.click.assert_not_called()
        self.assertNotIn('position', mouse.__dict__)

    def test_all_mouse_primitives_reject_invalid_button(self):
        for name in ('double_click', 'triple_click', 'button_down', 'button_up', 'drag'):
            mouse = Mock()
            raw = getattr(getattr(A, name), '__wrapped__', getattr(A, name))
            kwargs = dict(button='rigth', controller=mouse)
            if name == 'drag':
                kwargs.update(start={'x': 10, 'y': 10}, end={'x': 20, 'y': 20})
            with self.subTest(name=name), self.assertRaises(ArgumentError):
                raw(**kwargs)
            mouse.click.assert_not_called()
            mouse.press.assert_not_called()
            mouse.release.assert_not_called()
            self.assertNotIn('position', mouse.__dict__)

    def test_uia_rejects_before_target_resolution(self):
        raw = getattr(U.ui_click, '__wrapped__', U.ui_click)
        with patch('computer_mcp.pointer_contract.bind_window') as bind, self.assertRaises(ArgumentError):
            raw('Apply', mouse=Mock(), button='rigth')
        bind.assert_not_called()

    def test_template_rejects_before_capture(self):
        raw = getattr(V.click_template, '__wrapped__', V.click_template)
        with patch.object(V, 'match_template') as match, self.assertRaises(ArgumentError):
            raw('button', mouse=Mock(), button='rigth')
        match.assert_not_called()

    def test_batch_rejects_before_moving_the_pointer(self):
        mouse = Mock()
        with self.assertRaises(ArgumentError):
            U._click(mouse, {'x': 100, 'y': 100, 'button': 'rigth'})
        mouse.click.assert_not_called()
        self.assertNotIn('position', mouse.__dict__)

    def test_batch_preflights_later_button_before_earlier_move(self):
        raw = getattr(U.run_batch, '__wrapped__', U.run_batch)
        mouse = Mock()
        with self.assertRaises(ArgumentError):
            raw([{'action': 'move', 'x': 100, 'y': 100},
                 {'action': 'click', 'button': 'rigth'}], mouse, Mock())
        self.assertNotIn('position', mouse.__dict__)

    def test_composed_click_preserves_invalid_argument_code(self):
        from computer_mcp import conveyor
        raw = getattr(conveyor.do_action, '__wrapped__', conveyor.do_action)
        with patch('computer_mcp.execution.check'), self.assertRaises(ArgumentError) as caught:
            raw({'kind': 'click', 'button': 'rigth'}, (0, 0, 100, 100))
        self.assertEqual(caught.exception.code, 'invalid_argument')
