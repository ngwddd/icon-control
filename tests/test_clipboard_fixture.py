"""Clipboard failure must not erase user data or suppress a failed desktop test."""
import unittest
from unittest.mock import patch
import clipboard_fixture as fixture

class ClipboardFixtureTests(unittest.TestCase):
    def test_unreadable_backup_prevents_test_body_and_clipboard_mutation(self):
        with patch.object(fixture,'snapshot',side_effect=RuntimeError('not rendered')), \
             patch.object(fixture,'restore') as restore,patch.object(fixture.clip,'EmptyClipboard') as empty:
            with self.assertRaises(RuntimeError):
                with fixture.preserve_clipboard():self.fail('Test body ran without a usable backup')
            restore.assert_not_called();empty.assert_not_called()

    def test_original_payload_is_restored_when_test_raises(self):
        saved=[(13,b'x\x00\x00\x00')]
        with patch.object(fixture,'snapshot',return_value=saved),patch.object(fixture,'restore') as restore:
            with self.assertRaisesRegex(RuntimeError,'test failed'):
                with fixture.preserve_clipboard():raise RuntimeError('test failed')
            restore.assert_called_once_with(saved)

if __name__=='__main__':unittest.main()
