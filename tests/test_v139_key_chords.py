"""v1.3.9-alpha: accelerator chords (ctrl+f) and honest batch validation.

`key` used to reject "ctrl+f" with ValueError, which the gate then reported as a
permission failure. Chords are now parsed once, injected in the right order, and
the unsupported places say so explicitly.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from authority_fixture import AuthorityCase
from computer_mcp.actions import keyboard as keyboard_actions
from computer_mcp.core.utils import split_chord
from computer_mcp import ui_ext


class SplitChordTests(unittest.TestCase):
    def test_plain_key_is_unchanged(self):
        self.assertEqual(split_chord('f'), ([], 'f'))
        self.assertEqual(split_chord('ctrl'), ([], 'ctrl'))
        self.assertEqual(split_chord(''), ([], ''))

    def test_single_modifier_chord(self):
        self.assertEqual(split_chord('ctrl+f'), (['ctrl'], 'f'))

    def test_multi_modifier_chord(self):
        self.assertEqual(split_chord('ctrl+shift+f'), (['ctrl', 'shift'], 'f'))

    def test_aliases_are_kept_for_the_press_step(self):
        self.assertEqual(split_chord('control+alt+delete'), (['control', 'alt'], 'delete'))

    def test_unknown_modifier_is_rejected(self):
        with self.assertRaises(ValueError):
            split_chord('hyper+f')

    def test_modifier_only_chord_is_rejected(self):
        with self.assertRaises(ValueError):
            split_chord('ctrl+shift')

    def test_empty_side_is_rejected(self):
        with self.assertRaises(ValueError):
            split_chord('ctrl+')


class FakeController:
    def __init__(self):
        self.events = []

    def press(self, key):
        self.events.append(('press', str(key)))

    def release(self, key):
        self.events.append(('release', str(key)))

    def type(self, text):
        return len(text)


class KeyPressChordTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_chord_presses_modifiers_first_and_releases_in_reverse(self):
        controller = FakeController()
        result = keyboard_actions.key_press('ctrl+shift+f', controller=controller)
        self.assertTrue(result['chord'])
        self.assertEqual([verb for verb, _ in controller.events],
                         ['press', 'press', 'press', 'release', 'release', 'release'])
        names = [name for _, name in controller.events]
        self.assertEqual(names[0], names[-1])      # first modifier released last
        self.assertEqual(result['modifiers'], ['ctrl', 'shift'])
        self.assertEqual(result['base'], 'f')

    def test_plain_key_still_presses_and_releases_once(self):
        controller = FakeController()
        result = keyboard_actions.key_press('f', controller=controller)
        self.assertNotIn('chord', result)
        self.assertEqual([verb for verb, _ in controller.events], ['press', 'release'])

    def test_key_down_rejects_chords(self):
        controller = FakeController()
        with self.assertRaises(ValueError):
            keyboard_actions.key_down('ctrl+f', controller=controller)
        self.assertEqual(controller.events, [])

    def test_key_up_rejects_chords(self):
        controller = FakeController()
        with self.assertRaises(ValueError):
            keyboard_actions.key_up('ctrl+f', controller=controller)
        self.assertEqual(controller.events, [])


class BatchValidationTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def _run(self, steps, controller=None):
        with patch('computer_mcp.ui_ext._execution.sleep', lambda *a, **k: None):
            return ui_ext.run_batch(steps, mouse=object(),
                                    keyboard=controller or FakeController())

    def test_key_down_step_is_rejected_with_a_clear_message(self):
        result = self._run([{"action": "key_down", "key": "ctrl"}])
        self.assertFalse(result['ok'])
        self.assertEqual(result['failed'], 1)
        self.assertIn('key_down', result['log'][0]['error'])
        self.assertIn('top-level', result['log'][0]['error'])

    def test_key_up_step_is_rejected(self):
        result = self._run([{"action": "key_up", "key": "ctrl"}])
        self.assertFalse(result['ok'])
        self.assertIn('key_up', result['log'][0]['error'])

    def test_chord_key_step_runs(self):
        controller = FakeController()
        result = self._run([{"action": "key", "key": "ctrl+f"}], controller)
        self.assertTrue(result['ok'])
        self.assertTrue(result['log'][0]['chord'])
        self.assertEqual(len(controller.events), 4)

    def test_unknown_action_is_rejected_by_the_gate(self):
        """Unknown kinds fail in tool_spec before any input is injected."""
        with self.assertRaises(ValueError) as caught:
            self._run([{"action": "teleport"}])
        self.assertIn('Unknown step', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
