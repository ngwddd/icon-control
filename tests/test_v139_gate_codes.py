"""v1.3.9-alpha: gate failures are classified, not all reported as "not authorized"."""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _bootstrap  # noqa: F401

from computer_mcp import mcp, permission


class GateClassificationTests(unittest.TestCase):
    def test_permission_denied_stays_permission_denied(self):
        code, message = mcp.classify_gate_exception(
            permission.PermissionDenied('denied by fixture'))
        self.assertEqual(code, 'permission_denied')
        self.assertIn('权限', message)

    def test_value_error_is_invalid_argument(self):
        code, message = mcp.classify_gate_exception(ValueError('unknown key name: ctrl+f'))
        self.assertEqual(code, 'invalid_argument')
        self.assertIn('ValueError', message)

    def test_type_and_key_errors_are_invalid_argument(self):
        for exc in (TypeError('bad type'), KeyError('missing')):
            code, _ = mcp.classify_gate_exception(exc)
            self.assertEqual(code, 'invalid_argument')

    def test_os_and_timeout_errors_are_authority_unavailable(self):
        for exc in (OSError('pipe down'), TimeoutError('deadline'), ConnectionError('refused')):
            code, _ = mcp.classify_gate_exception(exc)
            self.assertEqual(code, 'authority_unavailable')

    def test_unknown_exception_is_internal_error(self):
        code, _ = mcp.classify_gate_exception(RuntimeError('boom'))
        self.assertEqual(code, 'internal_error')

    def test_argument_values_are_not_echoed(self):
        secret = 'TOKEN-SHOULD-NOT-LEAK'
        _, message = mcp.classify_gate_exception(ValueError(f'bad argument {secret}'))
        self.assertNotIn(secret, message)

    def test_every_code_is_declared(self):
        codes = set()
        for exc in (permission.PermissionDenied('x'), ValueError('y'), OSError('z'),
                    RuntimeError('w')):
            codes.add(mcp.classify_gate_exception(exc)[0])
        self.assertTrue(codes <= permission.ERROR_CODES)


if __name__ == '__main__':
    unittest.main()
