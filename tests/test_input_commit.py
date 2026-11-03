"""Authority failures between target validation and key-down must send no input."""
import unittest
from unittest.mock import Mock, patch
from authority_fixture import AuthorityCase
from computer_mcp import input_guard as I, permission, execution, control


class InputCommitTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def test_lost_authority_at_retention_sends_neither_down_nor_up(self):
        for cls in (I.KeyboardController, I.MouseController):
            with self.subTest(controller=cls.__name__):
                raw = Mock(position=(1, 1))
                controller = cls(raw)
                with patch.object(I, 'check'), patch('computer_mcp.capabilities.require_target'), \
                        patch.object(permission, 'status', return_value={'granted': False}):
                    try:
                        with self.assertRaises(permission.PermissionDenied):
                            controller.press('test-key')
                    finally:
                        controller.cleanup()
                raw.press.assert_not_called()
                raw.release.assert_not_called()
                self.assertFalse(controller.held)

    def test_failed_retention_does_not_release_unowned_key(self):
        raw = Mock()
        controller = I.KeyboardController(raw)
        with patch.object(I, 'check'), patch('computer_mcp.capabilities.require_target'), \
                patch.object(permission, 'status', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                controller.press('test-key')
            controller.cleanup()
        raw.press.assert_not_called()
        raw.release.assert_not_called()

    def test_changed_authority_at_retention_cancels_operation(self):
        raw = Mock()
        controller = I.KeyboardController(raw)
        with execution.operation('type'):
            state = permission.status()
            state['revision'] += 1
            with patch.object(I, 'check'), patch('computer_mcp.capabilities.require_target'), \
                    patch.object(permission, 'status', return_value=state):
                try:
                    with self.assertRaises(permission.PermissionDenied):
                        controller.press('test-key')
                finally:
                    controller.cleanup()
        raw.press.assert_not_called()
        raw.release.assert_not_called()

    def test_scope_removed_at_retention_sends_no_input(self):
        state = permission.status()
        state['authorization'] = dict(state['authorization'], scopes=['screen_read'])
        raw = Mock()
        controller = I.KeyboardController(raw)
        with patch.object(I, 'check'), patch('computer_mcp.capabilities.require_target'), \
                patch.object(permission, 'status', return_value=state):
            try:
                with self.assertRaises(permission.PermissionDenied):
                    controller.press('test-key')
            finally:
                controller.cleanup()
        raw.press.assert_not_called()
        raw.release.assert_not_called()

    def test_takeover_at_retention_cancels_operation(self):
        raw = Mock()
        controller = I.KeyboardController(raw)
        with execution.operation('type'):
            state = control.status()
            state['generation'] += 1
            with patch.object(I, 'check'), patch('computer_mcp.capabilities.require_target'), \
                    patch.object(control, 'status', return_value=state):
                with self.assertRaises(permission.PermissionDenied):
                    controller.press('test-key')
        raw.press.assert_not_called()
        raw.release.assert_not_called()

    def test_final_target_rejection_sends_no_input(self):
        raw = Mock()
        controller = I.KeyboardController(raw)
        with patch.object(I, 'check'), patch('computer_mcp.capabilities.require_target'), \
                patch('computer_mcp.capabilities.check_target', return_value='Target changed'):
            with self.assertRaises(permission.PermissionDenied):
                controller.press('test-key')
        raw.press.assert_not_called()
        raw.release.assert_not_called()

    def test_native_failure_still_releases_possibly_pressed_key(self):
        raw = Mock()
        raw.press.side_effect = OSError('native partial failure')
        controller = I.KeyboardController(raw)
        with self.assertRaises(OSError), execution.operation('type'):
            controller.press('test-key')
        raw.press.assert_called_once_with('test-key')
        raw.release.assert_called_once_with('test-key')
