"""v1.4.1: scroll_into_view finds a row in a long list, or says it did not."""
import unittest
from unittest.mock import PropertyMock, patch

from authority_fixture import AuthorityCase
from computer_mcp.input_guard import KeyboardController, MouseController
from computer_mcp.zones.dispatch import ComputerState, dispatch

WINDOW = (0, 0, 400, 300)


def tree(*nodes):
    return dict(ok=True, nodes=list(nodes))


def node(name, y, x=10, w=200, h=24):
    return dict(name=name, type='ListItemControl', x=x, y=y, w=w, h=h, path=f'0/{y}')


class ScrollIntoViewTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def setUp(self):
        super().setUp()
        guard = patch('computer_mcp.control.blocking_reason', return_value=None)
        guard.start()
        self.addCleanup(guard.stop)
        self.rect = patch('win32gui.GetWindowRect', return_value=WINDOW)
        self.rect.start()
        self.addCleanup(self.rect.stop)
        self.scroll = patch.object(MouseController, 'scroll', autospec=True)
        self.moved = self.scroll.start()
        self.addCleanup(self.scroll.stop)
        self.position = patch.object(MouseController, 'position',
                                     new_callable=PropertyMock, create=True)
        self.position.start()
        self.addCleanup(self.position.stop)

    def run_tool(self, **arguments):
        return dispatch('scroll_into_view', arguments, computer_state=ComputerState(),
                        mouse_controller=MouseController(),
                        keyboard_controller=KeyboardController()).get('result')

    def test_already_visible_does_not_scroll(self):
        with patch('computer_mcp.ui_ext.ui_tree', return_value=tree(node('目标行', 100))):
            result = self.run_tool(query='目标行')
        self.assertTrue(result['found'])
        self.assertEqual(result['scrolls'], 0)
        self.moved.assert_not_called()

    def test_scrolls_until_the_row_appears(self):
        trees = [tree(node('别的行', 100)),
                 tree(node('别的行', 100)),
                 tree(node('目标行', 120))]
        with patch('computer_mcp.ui_ext.ui_tree', side_effect=trees):
            result = self.run_tool(query='目标行', settle_ms=0)
        self.assertTrue(result['found'])
        self.assertEqual(result['scrolls'], 2)
        self.assertEqual(result['bounds']['y'], 120)

    def test_gives_up_and_explains(self):
        with patch('computer_mcp.ui_ext.ui_tree', return_value=tree(node('别的行', 100))):
            result = self.run_tool(query='不存在的行', max_scrolls=3, settle_ms=0)
        self.assertFalse(result['found'])
        self.assertIn('没有出现', result['note'])
        self.assertEqual(result['scrolls'], 3)

    def test_offscreen_match_asks_the_control_to_scroll_first(self):
        outside = dict(name='目标行', type='ListItemControl', x=10, y=900, w=200, h=24, path='0/9')
        inside = dict(name='目标行', type='ListItemControl', x=10, y=120, w=200, h=24, path='0/9')
        with patch('computer_mcp.ui_ext.ui_tree', side_effect=[tree(outside), tree(inside)]), \
                patch('computer_mcp.element_ops.perform',
                      return_value=dict(ok=True, action='scroll_into_view')) as perform:
            result = self.run_tool(query='目标行', settle_ms=0)
        args = perform.call_args[0]
        self.assertEqual(args[1:], ('0/9', 'scroll_into_view'))
        self.assertTrue(result['found'])


if __name__ == '__main__':
    unittest.main()
