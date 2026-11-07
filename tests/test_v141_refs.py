"""v1.4.1 element references: UIA references re-resolve, visual ones stay strict."""
import unittest
from unittest.mock import Mock, patch

from computer_mcp import snapshots as S
from computer_mcp import ui_ext as U


class FakeControl:
    def __init__(self, name, ctype, rect, children=()):
        self.Name = name
        self.ControlTypeName = ctype
        self._rect = rect
        self._children = list(children)

    @property
    def BoundingRectangle(self):
        left, top, right, bottom = self._rect
        return Mock(left=left, top=top, width=lambda: right - left, height=lambda: bottom - top)

    def GetChildren(self):
        return self._children


class PathTests(unittest.TestCase):
    def test_walk_records_the_child_index_chain(self):
        child = FakeControl('OK', 'ButtonControl', (10, 10, 50, 30))
        middle = FakeControl('Pane', 'PaneControl', (0, 0, 100, 100), [child])
        root = FakeControl('Win', 'WindowControl', (0, 0, 300, 200), [middle])
        out = []
        U._walk(root, 3, out, 50, only_named=True, prefix='')
        self.assertEqual([node['path'] for node in out], ['0', '0/0'])
        self.assertEqual(out[1]['name'], 'OK')

    def test_control_at_path_walks_children_by_index(self):
        child = FakeControl('OK', 'ButtonControl', (10, 10, 50, 30))
        middle = FakeControl('Pane', 'PaneControl', (0, 0, 100, 100), [child])
        root = FakeControl('Win', 'WindowControl', (0, 0, 300, 200), [middle])
        with patch.object(U, '_control_from', return_value=root), patch.object(U, '_UIA_OK', True):
            self.assertEqual(U.control_at_path(11, '0/0')['name'], 'OK')
            self.assertIsNone(U.control_at_path(11, '0/9'))


class ReferenceTests(unittest.TestCase):
    identity = (11, 21, 123.0, 'Fixture', (0, 0, 300, 200), 144)

    def setUp(self):
        S._snapshots.clear()
        self.ident = patch.object(S, 'window_identity', return_value=self.identity).start()
        self.addCleanup(patch.stopall)
        self.node = dict(x=10, y=10, w=40, h=20, name='Button', type='ButtonControl',
                         path='0/1', element_id='unique')

    def uia_ref(self):
        result = S.attach(11, [self.node])
        self.assertTrue(result['resolvable'])
        self.assertEqual(result['expires_in_s'], S.REF_TTL_UIA)
        return result['candidates'][0]['ref']

    def test_uia_attach_does_not_capture_pixels(self):
        with patch.object(S, 'screen_fingerprint') as grab:
            S.attach(11, [self.node])
        grab.assert_not_called()

    def test_moved_window_still_resolves_with_fresh_coordinates(self):
        ref = self.uia_ref()
        self.ident.return_value = (*self.identity[:4], (500, 400, 800, 600), 144)
        with patch.object(U, 'control_at_path', return_value=dict(
                name='Button', type='ButtonControl', x=510, y=410, w=40, h=20, path='0/1')):
            target = S.resolve(ref, 11)
        self.assertEqual((target['x'], target['y']), (510, 410))
        self.assertEqual((target['cx'], target['cy']), (530, 420))

    def test_uia_reference_outlives_the_old_five_second_window(self):
        ref = self.uia_ref()
        for item in S._snapshots.values():
            item['created'] -= 30
        with patch.object(U, 'control_at_path', return_value=dict(
                name='Button', type='ButtonControl', x=10, y=10, w=40, h=20, path='0/1')):
            self.assertEqual(S.resolve(ref, 11)['name'], 'Button')

    def test_changed_identity_at_the_path_is_stale(self):
        ref = self.uia_ref()
        with patch.object(U, 'control_at_path', return_value=dict(
                name='Cancel', type='ButtonControl', x=10, y=10, w=40, h=20, path='0/1')):
            with self.assertRaises(S.StaleReference):
                S.resolve(ref, 11)

    def test_missing_element_at_the_path_is_stale(self):
        ref = self.uia_ref()
        with patch.object(U, 'control_at_path', return_value=None):
            with self.assertRaises(S.StaleReference):
                S.resolve(ref, 11)

    def test_process_change_is_still_stale(self):
        ref = self.uia_ref()
        self.ident.return_value = (11, 99, 999.0, 'Fixture', (0, 0, 300, 200), 144)
        with self.assertRaises(S.StaleReference):
            S.resolve(ref, 11)

    def test_visual_references_keep_the_short_ttl(self):
        node = dict(self.node)
        node.pop('path')
        with patch.object(S, 'screen_fingerprint', return_value='same'):
            result = S.attach(11, [node])
        self.assertFalse(result['resolvable'])
        self.assertEqual(result['expires_in_s'], S.REF_TTL_VISUAL)
        for item in S._snapshots.values():
            item['created'] -= 6
        with self.assertRaises(S.StaleReference):
            S.resolve(result['candidates'][0]['ref'], 11)


if __name__ == '__main__':
    unittest.main()
