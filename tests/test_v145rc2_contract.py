import unittest
from unittest.mock import Mock, patch
from jsonschema import Draft202012Validator
from computer_mcp import ocr_ext as O, vision_state as V, pointer_contract as P
from computer_mcp import tool_registry
from computer_mcp.result_outcome import normalize
from test_v144_final_audit import call_tool


class ContractTests(unittest.TestCase):
    def test_uncontextualized_success_is_never_verified(self):
        self.assertEqual(normalize({'success': True})['outcome'], 'executed_unverified')

    def test_set_config_is_a_mutation_without_postcondition(self):
        result = normalize({'success': True}, 'set_config', {'observe_screen': False})
        self.assertEqual(result['outcome'], 'executed_unverified')
        self.assertEqual(result['action_category'], 'mutation')

    def test_read_completion_is_observed_not_verified(self):
        result = normalize({'ok': True}, 'ui_find', {'name': 'Apply'})
        self.assertEqual(result['outcome'], 'observed')

    def test_explicit_success_without_proof_is_not_trusted(self):
        result = normalize({'success': True, 'outcome': 'verified_success'}, 'ui_click', {})
        self.assertEqual(result['outcome'], 'executed_unverified')

    def test_cancellation_after_input_is_not_downgraded_to_failure(self):
        result = normalize({'ok': False, 'outcome': 'cancelled', 'action_executed': True})
        self.assertEqual(result['outcome'], 'cancelled')
        self.assertTrue(result['action_executed'])

    def test_template_schema_accepts_complete_or_absent_region_only(self):
        validator = Draft202012Validator(tool_registry.get('click_template').schema)
        self.assertTrue(validator.is_valid({'name': 'btn'}))
        self.assertTrue(validator.is_valid(dict(name='btn', x=0, y=0, w=10, h=10)))
        for missing in ('x', 'y', 'w', 'h'):
            payload = dict(name='btn', x=0, y=0, w=10, h=10)
            del payload[missing]
            self.assertFalse(validator.is_valid(payload))

    def test_partial_template_region_is_rejected_before_recognition(self):
        with patch.object(V, 'click_template') as click:
            result = call_tool('click_template', {'name': 'btn', 'x': 0, 'y': 0, 'w': 10})
        self.assertEqual(result['code'], 'invalid_argument')
        click.assert_not_called()

    def test_click_executor_never_creates_a_late_binding(self):
        from test_v145_pointer_contract import FakeMouse
        with patch.object(P, 'bind_window') as bind:
            result = P.click_at(FakeMouse(), (10, 10), 'left')
        bind.assert_not_called()
        self.assertEqual(result['code'], 'target_unverified')

    def test_default_ocr_target_is_bound_before_recognition(self):
        raw = getattr(O.click_text, '__wrapped__', O.click_text)
        binding = P.WindowBinding(42, {'pid': 1}, (0, 0, 800, 600))
        order = []
        def bind(hwnd):
            order.append('bind')
            return binding
        def find(*args, **kwargs):
            order.append('find')
            self.assertEqual(kwargs['hwnd'], 42)
            return {'ok': True, 'matches': []}
        with patch.object(P, 'bind_window', side_effect=bind), patch.object(O, 'find_text', side_effect=find):
            raw('Apply', mouse=Mock())
        self.assertEqual(order, ['bind', 'find'])

    def test_default_template_target_is_bound_before_recognition(self):
        raw = getattr(V.click_template, '__wrapped__', V.click_template)
        order = []
        def bind(hwnd):
            order.append('bind')
            return P.WindowBinding(42, {'pid': 1}, (0, 0, 800, 600))
        def match(*args, **kwargs):
            order.append('match')
            self.assertEqual(kwargs['hwnd'], 42)
            return {'success': True, 'found': False}
        with patch.object(P, 'bind_window', side_effect=bind), patch.object(V, 'match_template', side_effect=match):
            raw('btn', mouse=Mock())
        self.assertEqual(order, ['bind', 'match'])
