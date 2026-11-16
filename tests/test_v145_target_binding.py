import unittest
from unittest.mock import Mock, patch
from computer_mcp import pointer_contract as P, ui_ext as U


class DefaultWindowBindingTests(unittest.TestCase):
    def test_foreground_is_bound_before_name_resolution(self):
        binding = P.WindowBinding(42, {'pid': 123}, (0, 0, 800, 600))
        mouse = Mock()
        order = []
        def bind(hwnd):
            order.append('bind')
            self.assertIsNone(hwnd)
            return binding
        def resolve(hwnd, *args):
            order.append('resolve')
            self.assertEqual(hwnd, 42)
            return dict(name='Apply', type='Button', cx=120, cy=240), {}
        raw = getattr(U.ui_click, '__wrapped__', U.ui_click)
        with patch.object(P, 'bind_window', side_effect=bind), \
                patch.object(U, '_resolve', side_effect=resolve), \
                patch('computer_mcp.winutil.point_owner', return_value=42), \
                patch.object(P, 'click_at', return_value={'outcome': 'executed_unverified'}) as click:
            raw('Apply', mouse=mouse)
        self.assertEqual(order, ['bind', 'resolve'])
        self.assertIs(click.call_args.kwargs['binding'], binding)
