"""v1.3.1 安全整改回归：快捷授权身份绑定、剪贴板权限分离、日志脱敏。

对应独立审计 P1-01 / P1-02 / P1-03 与 P2 的界面范围说明。
每个用例先在旧实现上失败，再随修复通过。
"""
import json
import os
import unittest
from unittest.mock import patch

from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, consent, macro_ext, permission, quick_grant


class ClipboardScopeTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def test_scopes_are_declared(self):
        self.assertIn('clipboard_read', capabilities.SCOPES)
        self.assertIn('clipboard_write', capabilities.SCOPES)

    def test_validate_accepts_clipboard_scopes(self):
        auth = dict(agent_session='a' * 48, scopes=['clipboard_read', 'clipboard_write'], applications=[])
        self.assertTrue(capabilities.validate(auth))

    def test_clipboard_write_effect_requires_its_scope(self):
        class Spec:
            def effects_for(self, _args):
                return ('clipboard_write',)
        self.assertIn('clipboard_write', capabilities.required(Spec(), {}))

    def test_reading_the_clipboard_needs_its_own_scope(self):
        self.assertEqual(macro_ext._MACRO_SCOPES['clipboard_get'], ('clipboard_read',))
        self.assertEqual(macro_ext._MACRO_SCOPES['assert_clipboard'], ('clipboard_read',))

    def test_text_entry_alone_cannot_read_the_clipboard(self):
        with patch.object(capabilities, 'has_scope', side_effect=lambda scope: scope == 'text_entry'):
            with self.assertRaises(permission.PermissionDenied):
                macro_ext._check_macro_action('clipboard_get')

    def test_writing_the_clipboard_needs_its_own_scope(self):
        self.assertEqual(macro_ext._MACRO_SCOPES['clipboard_set'], ('clipboard_write',))

    def test_macro_scope_map_has_no_text_entry_clipboard_read(self):
        self.assertNotIn('text_entry', macro_ext._MACRO_SCOPES['clipboard_get'])
        self.assertNotIn('text_entry', macro_ext._MACRO_SCOPES['clipboard_set'])


class ClipboardRedactionTests(unittest.TestCase):
    def test_observation_never_carries_the_value(self):
        entry, sub = macro_ext._clipboard_observation('SECRET-token-42', 'needle')
        blob = json.dumps({'entry': entry, 'sub': sub}, ensure_ascii=False)
        self.assertNotIn('SECRET', blob)
        self.assertNotIn('preview', entry)
        self.assertFalse(sub['ok'])

    def test_success_reports_length_only(self):
        entry, sub = macro_ext._clipboard_observation('SECRET-token-42', 'SECRET')
        self.assertTrue(sub['ok'])
        self.assertEqual(entry['chars'], len('SECRET-token-42'))
        self.assertNotIn('SECRET', json.dumps(entry, ensure_ascii=False))


class ClipboardRestoreTests(unittest.TestCase):
    def test_restores_previous_value_when_unchanged(self):
        with patch.object(macro_ext, '_clipboard_sequence', return_value=7), \
                patch.object(macro_ext, '_write_clipboard') as write:
            self.assertTrue(macro_ext._restore_clipboard('previous', 7))
            write.assert_called_once_with('previous')

    def test_keeps_newer_content_from_other_programs(self):
        with patch.object(macro_ext, '_clipboard_sequence', return_value=9), \
                patch.object(macro_ext, '_write_clipboard') as write:
            self.assertFalse(macro_ext._restore_clipboard('previous', 7))
            write.assert_not_called()

    def test_nothing_to_restore(self):
        with patch.object(macro_ext, '_clipboard_sequence', return_value=7), \
                patch.object(macro_ext, '_write_clipboard') as write:
            self.assertFalse(macro_ext._restore_clipboard(None, 7))
            write.assert_not_called()


class QuickGrantIdentityTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True

    def _write_pref(self, agent, app):
        policy = quick_grant.QuickGrantPolicy()
        policy.path.parent.mkdir(parents=True, exist_ok=True)
        policy.path.write_text(json.dumps(dict(agent=agent, app=app, signature='x')), encoding='utf8')
        return policy

    def test_saved_agent_must_match_even_when_it_is_the_only_one_online(self):
        app = dict(pid=os.getpid(), created=1.0, exe='C:/x.exe')
        policy = self._write_pref('a' * 48, app)
        other = [dict(id='b' * 48, label='另一个 Agent', pid=os.getpid())]
        with patch.object(quick_grant.security, 'authentic', return_value=True), \
                patch.object(quick_grant.agent_session, 'active', return_value=other), \
                patch.object(quick_grant.capabilities, 'process_record', return_value=app):
            result = policy.resolve()
        self.assertNotEqual(result.get('status'), 'ready')
        self.assertNotEqual(result.get('agent_session'), 'b' * 48)

    def test_saved_agent_still_resolves_when_it_is_online(self):
        app = dict(pid=os.getpid(), created=1.0, exe='C:/x.exe')
        policy = self._write_pref('a' * 48, app)
        active = [dict(id='a' * 48, label='保存的 Agent', pid=os.getpid())]
        with patch.object(quick_grant.security, 'authentic', return_value=True), \
                patch.object(quick_grant.agent_session, 'active', return_value=active), \
                patch.object(quick_grant.capabilities, 'process_record', return_value=app):
            result = policy.resolve()
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['agent_session'], 'a' * 48)


class ConsentLabelTests(unittest.TestCase):
    def test_new_scopes_have_human_labels(self):
        for scope in ('clipboard_read', 'clipboard_write'):
            self.assertIn(scope, consent.LABELS)
            self.assertTrue(consent.LABELS[scope].strip())

    def test_screen_read_says_whole_desktop(self):
        self.assertIn('整个桌面', consent.LABELS['screen_read'])

    def test_every_scope_has_a_label(self):
        missing = [scope for scope in capabilities.SCOPES if scope not in consent.LABELS]
        self.assertEqual(missing, [])


class DeclaredEffectTests(unittest.TestCase):
    def test_capture_daemon_no_longer_claims_file_write(self):
        from computer_mcp import tool_registry
        spec = next(item for item in tool_registry.iter_specs() if item.name == 'capture_daemon')
        self.assertNotIn('file_write', spec.effects)
        self.assertIn('screen_read', spec.effects)


if __name__ == '__main__':
    unittest.main()
