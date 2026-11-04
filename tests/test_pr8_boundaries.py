"""PR8 audit counterexamples; fake windows and observations only."""
import json
import unittest
from unittest.mock import Mock, patch
from authority_fixture import AuthorityCase
from computer_mcp import macro_ext, verify_flow, input_guard, permission, tool_manifest, tool_registry
from computer_mcp.actions import mouse


def window():
    return dict(hwnd=123, x=0, y=0, w=100, h=100,
                rect_x=0, rect_y=0, rect_w=100, rect_h=100)


def step():
    return dict(action='guarded_click', rel=[10, 20],
                before=[dict(kind='text', query='main')],
                after=[dict(kind='text', query='moments')])


class PageEvidenceTests(unittest.TestCase):
    def test_guard_rejects_weak_or_invalid_thresholds_before_reading_or_clicking(self):
        for threshold in (0, -1, 0.6, True, '1', None, float('nan'), float('inf')):
            candidate = step()
            candidate['before'][0]['min_lcs_share'] = threshold
            with self.subTest(threshold=threshold), patch.object(verify_flow, 'run') as read, patch.object(mouse, 'click') as click:
                with self.assertRaises(ValueError):
                    macro_ext._guarded_click(candidate, window(), Mock())
                read.assert_not_called()
                click.assert_not_called()

    def test_stability_or_absence_alone_cannot_identify_a_page(self):
        for checks in ([dict(kind='stable')], [dict(kind='baseline', name='page')],
                       [dict(kind='text', query='other page', absent=True)]):
            candidate = step()
            candidate['after'] = checks
            with self.subTest(checks=checks), patch.object(verify_flow, 'run') as read:
                with self.assertRaises(ValueError):
                    macro_ext._guarded_click(candidate, window(), Mock())
                read.assert_not_called()

    def test_empty_and_nonmatching_ocr_do_not_satisfy_positive_identity(self):
        for lines in ([], [{'text':'another page'}], [{'text':'mainly'}]):
            with self.subTest(lines=lines), patch('computer_mcp.ocr_ext.ocr_read', return_value={'lines':lines}):
                result = verify_flow._check_text(dict(query='main page', min_lcs_share=1, require_evidence=True))
                self.assertFalse(result['ok'])

    def test_empty_ocr_is_not_evidence_for_guarded_absence(self):
        with patch('computer_mcp.ocr_ext.ocr_read', return_value={'lines':[]}):
            self.assertFalse(verify_flow._check_text(dict(query='video', absent=True, require_evidence=True))['ok'])

    def test_generic_text_check_rejects_zero_and_nonfinite_thresholds(self):
        for threshold in (0, float('nan'), float('inf'), -0.1):
            with self.subTest(threshold=threshold), patch('computer_mcp.ocr_ext.ocr_read') as read:
                self.assertFalse(verify_flow._check_text(dict(query='page', min_lcs_share=threshold))['ok'])
                read.assert_not_called()

    def test_same_pid_covering_window_blocks_guarded_click(self):
        with patch('win32gui.GetAncestor', side_effect=lambda hwnd, mode: hwnd), patch('win32gui.WindowFromPoint', return_value=456), patch('win32process.GetWindowThreadProcessId', return_value=(1, 11)), patch('computer_mcp.capabilities.process_record', return_value=dict(pid=11, created=1, exe='fixture.exe')), patch.object(verify_flow, 'run', return_value={'ok':True}), patch.object(mouse, 'click') as click:
            with self.assertRaises(permission.PermissionDenied):
                macro_ext._guarded_click(step(), window(), Mock())
        click.assert_not_called()

    def test_multiple_matching_windows_require_explicit_selection(self):
        def enumerate_windows(callback, extra):
            callback(123, extra)
            callback(456, extra)
        with patch('win32gui.EnumWindows', side_effect=enumerate_windows), patch('win32gui.IsWindowVisible', return_value=True), patch('win32gui.GetAncestor', side_effect=lambda hwnd, mode: hwnd), patch('win32gui.GetWindowText', return_value='WeChat'):
            with self.assertRaisesRegex(ValueError, 'explicit'):
                macro_ext._find_window({'title_contains':'WeChat'})


class InjectionAndScrollTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def test_window_occlusion_is_rechecked_at_actual_button_down(self):
        raw = Mock(position=(10, 20))
        controller = input_guard.MouseController(raw)
        expected = dict(pid=11, created=1, exe='fixture.exe')
        with patch('win32gui.WindowFromPoint', return_value=456), patch('win32gui.GetAncestor', return_value=456), patch('win32process.GetWindowThreadProcessId', return_value=(1, 11)), patch('computer_mcp.capabilities.process_record', return_value=expected), patch.object(input_guard, '_retain'):
            with self.assertRaises(permission.PermissionDenied):
                controller.press(input_guard.Button.left, expected_target=expected,
                                 expected_point=(10, 20), expected_hwnd=123)
        raw.press.assert_not_called()
        self.assertFalse(controller.held)

    def test_scroll_only_allowlist_permits_positioning_and_wheel(self):
        import os
        raw = Mock(position=(10, 20))
        controller = input_guard.MouseController(raw)
        with patch.dict(os.environ, {'DSH_TOOLS_ALLOW':'scroll', 'DSH_TOOLS_DENY':'mouse_move'}), patch('win32gui.WindowFromPoint', return_value=123), patch('win32process.GetWindowThreadProcessId', return_value=(1, 11)), patch('computer_mcp.capabilities.process_record', return_value=dict(pid=11)):
            result = mouse.scroll(dy=-3, x=10, y=20, controller=controller)
        raw.scroll.assert_called_once_with(0, -3)
        self.assertFalse(result['verified'])

    def test_denied_scroll_does_not_inject(self):
        import os
        raw = Mock(position=(10, 20))
        with patch.dict(os.environ, {'DSH_TOOLS_DENY':'scroll'}):
            with self.assertRaises(permission.PermissionDenied):
                input_guard.MouseController(raw).scroll(0, -3)
        raw.scroll.assert_not_called()

    def test_missing_required_macro_parameters_stop_before_resolving_window(self):
        from pathlib import Path
        folder = Path(self.authority.temp.name) / 'macros'
        folder.mkdir()
        spec = dict(name='fixture', defaults={'main_query':''}, required_params=['main_query'],
                    steps=[dict(action='guarded_click')])
        (folder / 'fixture.json').write_text(json.dumps(spec), encoding='utf-8')
        for params in ({}, {'main_query':'   '}, {'main_query':None}):
            with self.subTest(params=params), patch.object(macro_ext, 'MACRO_DIR', str(folder)), patch.object(macro_ext, '_find_window') as resolve:
                result = macro_ext.run_macro('fixture', params=params)
            self.assertIn('error', result)
            self.assertIn('main_query', result['missing_params'])
            resolve.assert_not_called()


class ToolManifestTests(unittest.TestCase):
    def test_registry_matches_packaged_name_contract(self):
        self.assertEqual(set(tool_manifest.validate_registry()), set(tool_registry.TOOLS))

    def test_incomplete_registry_does_not_pass_by_matching_only_a_count(self):
        with patch.object(tool_registry, 'TOOLS', {'unexpected': Mock()}):
            with self.assertRaises(RuntimeError):
                tool_manifest.validate_registry()
