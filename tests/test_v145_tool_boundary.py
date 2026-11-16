import unittest
from unittest.mock import patch
from computer_mcp import tool_registry as R
from computer_mcp.result_outcome import normalize
from test_v144_final_audit import call_tool


class ToolBoundaryTests(unittest.TestCase):
    def test_client_default_generation_cannot_synthesize_index_zero(self):
        properties = R.get('click_text').schema['properties']
        self.assertNotIn('default', properties['index'])
        generated = {key: value['default'] for key, value in properties.items() if 'default' in value}
        self.assertNotIn('index', generated)

    def test_omitted_and_explicit_zero_remain_distinct_at_dispatch(self):
        from computer_mcp import ocr_ext
        for supplied, expected in [({}, None), ({'index': 0}, 0)]:
            with patch.object(ocr_ext, 'click_text', return_value={'ok': True}) as click:
                call_tool('click_text', {'query': 'Apply', **supplied})
            self.assertEqual(click.call_args.kwargs['index'], expected)

    def test_input_success_is_unverified(self):
        result = normalize({'ok': True}, 'ui_click', {'name': 'Apply'})
        self.assertEqual(result['outcome'], 'executed_unverified')
        self.assertFalse(result['verified'])

    def test_refusal_is_shared_by_old_and_new_flags(self):
        for payload in [{'success': False, 'blocked': True},
                        {'ok': False, 'code': 'ambiguous_target'}]:
            self.assertEqual(normalize(payload)['outcome'], 'refused')
