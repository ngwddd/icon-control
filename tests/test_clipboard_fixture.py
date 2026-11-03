"""Clipboard failure must not erase user data or suppress a failed desktop test."""
import unittest
from contextlib import nullcontext
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
        counter=[1]
        with patch.object(fixture,'snapshot',return_value=(saved,1)),patch.object(fixture,'restore') as restore, \
             patch.object(fixture,'sequence',side_effect=lambda:counter[0]),patch.object(fixture,'opened',return_value=nullcontext()), \
             patch.object(fixture.clip,'GetClipboardData',return_value='test-owned'),patch.object(fixture,'owner_pid',return_value=42):
            with self.assertRaisesRegex(RuntimeError,'test failed'):
                with fixture.preserve_clipboard() as lease:
                    lease.before_copy();counter[0]=2;lease.claim_test_text('test-owned',42)
                    raise RuntimeError('test failed')
            restore.assert_called_once_with(saved,2,42)

    def test_added_ansi_terminator_preserves_payload_but_changed_bytes_fail(self):
        with patch.object(fixture,'opened',return_value=nullcontext()), \
             patch.object(fixture.clip,'EmptyClipboard'),patch.object(fixture.clip,'SetClipboardData'), \
             patch.object(fixture,'sequence',return_value=10), \
             patch.object(fixture,'memory_data',return_value=b'payload\0\0') as read:
            fixture.restore([(1,b'payload\0')],10)
            read.return_value=b'changed\0'
            with self.assertRaisesRegex(RuntimeError,'restoration mismatch'):
                fixture.restore([(1,b'payload\0')],10)

    def test_external_update_after_copy_is_preserved_instead_of_restoring_old_data(self):
        counter=[1]
        with patch.object(fixture,'snapshot',return_value=([(13,b'x\0\0\0')],1)), \
             patch.object(fixture,'opened',return_value=nullcontext()),patch.object(fixture,'sequence',side_effect=lambda:counter[0]), \
             patch.object(fixture.clip,'GetClipboardData',return_value='test-owned'),patch.object(fixture,'owner_pid',return_value=42), \
             patch.object(fixture.clip,'EmptyClipboard') as empty:
            with self.assertRaises(fixture.ClipboardConflict):
                with fixture.preserve_clipboard() as lease:
                    lease.before_copy();counter[0]=2;lease.claim_test_text('test-owned',42)
                    counter[0]=3  # An external application supplies newer data.
            empty.assert_not_called()

    def test_odd_unicode_is_rejected_before_test_or_clear(self):
        with patch.object(fixture,'snapshot',return_value=([(13,b'odd')],1)),patch.object(fixture.clip,'EmptyClipboard') as empty:
            with self.assertRaises(RuntimeError):
                with fixture.preserve_clipboard():self.fail('Malformed data admitted the test')
            with self.assertRaises(RuntimeError):fixture.restore([(13,b'odd')],1)
            empty.assert_not_called()

    def test_clipboard_smoke_rejects_noop_clear_and_paste(self):
        from test_e2e_smoke import TestE2E
        from computer_mcp.actions import keyboard
        case=TestE2E('test_1_clipboard_roundtrip');holder={'text':''};case.observations=[]
        def enter(text):holder['text']=text;return dict(text=text,pid=42)
        with patch.object(case,'enter',side_effect=enter),patch.object(case,'combo'), \
             patch.object(case,'fixture_state',side_effect=lambda:dict(text=holder['text'],pid=42)), \
             patch.object(fixture,'preserve_clipboard',return_value=nullcontext(__import__('unittest.mock',fromlist=['Mock']).Mock())), \
             patch.object(fixture.clip,'OpenClipboard'),patch.object(fixture.clip,'CloseClipboard'), \
             patch.object(fixture.clip,'GetClipboardData',side_effect=lambda _:holder['text']), \
             patch.object(keyboard,'key_press'),patch('time.sleep'):
            with self.assertRaisesRegex(AssertionError,'Clear must actually change'):
                case.test_1_clipboard_roundtrip()
        self.assertEqual(case.observations,[])

if __name__=='__main__':unittest.main()
