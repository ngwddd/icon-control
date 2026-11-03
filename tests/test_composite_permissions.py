import unittest
from computer_mcp import tool_registry, capabilities


class CompositePermissionTests(unittest.TestCase):
    def test_inline_scroll_needs_no_process_or_write(self):
        spec = tool_registry.get('run_script')
        scopes = capabilities.required(spec, {'ops': [{'op': 'scroll', 'dy': -1}]})
        self.assertIn('input', scopes)
        self.assertFalse(scopes & {'process', 'file_write'}, scopes)

    def test_unselected_branch_is_checked(self):
        spec = tool_registry.get('run_script')
        ops = [{'op': 'if', 'then': [{'op': 'click'}], 'else': [{'op': 'press'}]}]
        self.assertIn('text_entry', capabilities.required(spec, {'ops': ops}))

    def test_unknown_nested_operation_is_rejected(self):
        spec = tool_registry.get('run_script')
        with self.assertRaises(ValueError):
            spec.effects_for({'ops': [{'op': 'until', 'do': [{'op': 'launch'}]}]})
