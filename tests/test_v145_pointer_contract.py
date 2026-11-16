"""Constrained input failures must not produce a second click."""
import unittest
from unittest.mock import patch
from computer_mcp import pointer_contract as P
from computer_mcp.input_guard import MouseController


class FakeMouse(MouseController):
    def __init__(self, error=None):
        self.point = (0, 0)
        self.error = error
        self.calls = []
        self.held = set()
        self.cleaned = False

    @property
    def position(self):
        return self.point

    @position.setter
    def position(self, value):
        self.point = value

    def click(self, button, count=1, **constraints):
        self.calls.append((button, count, constraints))
        if self.error:
            raise self.error

    def cleanup(self):
        self.cleaned = True


class PointerContractTests(unittest.TestCase):
    def setUp(self):
        self.binding = P.WindowBinding(42, {'pid': 123, 'created': 10, 'exe': 'fixture.exe'},
                                       (0, 0, 800, 600))

    def run_click(self, mouse):
        with patch.object(P, '_validate'), patch.object(P.execution, 'sleep'):
            return P.click_at(mouse, (120, 240), 'left', binding=self.binding)

    def test_type_error_after_entry_does_not_retry(self):
        mouse = FakeMouse(TypeError('raised inside the implementation'))
        result = self.run_click(mouse)
        self.assertEqual(len(mouse.calls), 1)
        self.assertIsNone(result['action_executed'])
        self.assertFalse(result['retry_safe'])
        self.assertEqual(result['outcome'], 'failed')
        self.assertTrue(mouse.cleaned)

    def test_unsupported_signature_refuses_before_movement(self):
        class Legacy(FakeMouse):
            def click(self, button, count=1):
                self.calls.append(button)
        mouse = Legacy()
        result = self.run_click(mouse)
        self.assertEqual(result['outcome'], 'refused')
        self.assertEqual(mouse.point, (0, 0))
        self.assertEqual(mouse.calls, [])

    def test_every_click_receives_point_hwnd_and_process(self):
        mouse = FakeMouse()
        result = self.run_click(mouse)
        self.assertEqual(mouse.calls[0][2], dict(expected_point=(120, 240),
                         expected_hwnd=42, expected_target=self.binding.process))
        self.assertEqual(result['outcome'], 'executed_unverified')
        self.assertFalse(result['verified'])

    def test_target_change_prevents_click(self):
        from computer_mcp.core.argument_error import ArgumentError
        mouse = FakeMouse()
        with patch.object(P, '_validate', side_effect=ArgumentError('changed', code='target_changed')):
            result = P.click_at(mouse, (120, 240), 'left', binding=self.binding)
        self.assertEqual(mouse.calls, [])
        self.assertFalse(result['action_executed'])

    def test_cancelled_settle_preserves_completed_click(self):
        from computer_mcp.permission import PermissionDenied
        mouse = FakeMouse()
        with patch.object(P, '_validate'), patch.object(P.execution, 'sleep',
                side_effect=[None, PermissionDenied('stopped')]):
            result = P.click_at(mouse, (120, 240), 'left', binding=self.binding, settle_ms=100)
        self.assertTrue(result['action_executed'])
        self.assertEqual(result['outcome'], 'cancelled')
        self.assertEqual(len(mouse.calls), 1)
