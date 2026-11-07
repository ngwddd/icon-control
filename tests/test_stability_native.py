"""Native API regressions with fake HWNDs, fake actuators and isolated authority."""
import hashlib
import json
import sys
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PIL import Image
from authority_fixture import AuthorityCase
from computer_mcp import permission_bridge, execution, micro, ocr_ext, live
from computer_mcp.actions import keyboard, window


class NativeTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def setUp(self):
        super().setUp()
        # Fake HWNDs must have a complete, stable owner identity. Keep the real
        # _MessageKeyboard validation and only replace OS process discovery.
        self.owner = dict(pid=987654, created=1234.5, exe='C:/fixtures/editor.exe')
        patches = [
            patch.object(keyboard, '_window_controllers', {}),
            patch('win32process.GetWindowThreadProcessId', return_value=(5678, self.owner['pid'])),
            patch('computer_mcp.capabilities.process_record', return_value=self.owner),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def test_unicode_window_text_is_not_silently_skipped(self):
        posted = []
        with patch('win32gui.IsWindow', return_value=True), patch('win32gui.PostMessage', side_effect=lambda *a: posted.append(a)):
            result = keyboard.type_text_to_window('中😀', 123)
        self.assertTrue(result['success'])
        self.assertEqual([p[2] for p in posted], [0x4e2d, 0xd83d, 0xde00])

    def test_revoke_mid_window_text_stops_remaining_characters(self):
        posted = []
        def post(*args):
            posted.append(args)
            permission_bridge.write_state(False, client='fixture', event='action')
        with patch('win32gui.IsWindow', return_value=True), patch('win32gui.PostMessage', side_effect=post):
            result = keyboard.type_text_to_window('abcd', 124)
        self.assertIn('error', result)
        self.assertEqual(len(posted), 1)

    def test_replaced_process_blocks_next_window_character(self):
        from computer_mcp import capabilities
        posted = []
        def post(*args):
            posted.append(args)
            # Same PID/HWND, different creation time: no ownership inheritance.
            self.owner = dict(self.owner, created=self.owner['created'] + 1)
        with patch('win32gui.IsWindow', return_value=True), patch('win32gui.PostMessage', side_effect=post), patch.object(capabilities, 'process_record', side_effect=lambda pid: dict(self.owner)):
            result = keyboard.type_text_to_window('ab', 123)
        self.assertIn('error', result)
        self.assertEqual(len(posted), 1)
        self.assertIn('target process changed', result['error'])

    def test_changed_window_thread_blocks_message_release(self):
        from pynput.keyboard import KeyCode
        with patch('win32gui.IsWindow', return_value=True), patch('win32gui.PostMessage') as post:
            raw = keyboard._MessageKeyboard(123)
            with patch('win32process.GetWindowThreadProcessId', return_value=(9999, self.owner['pid'])):
                from computer_mcp.permission import PermissionDenied
                with self.assertRaises(PermissionDenied):
                    raw.release(KeyCode.from_vk(86))
        post.assert_not_called()

    def test_window_screenshot_never_focuses(self):
        with patch.object(ocr_ext, '_print_window', return_value=(Image.new('RGB',(12,8)),0,0)), patch('win32gui.ShowWindow') as show, patch('win32gui.SetForegroundWindow') as focus:
            result = window.screenshot_window(125)
        self.assertTrue(result['success'])
        self.assertEqual((result['width'], result['height']), (12,8))
        show.assert_not_called(); focus.assert_not_called()

    def test_ocr_region_never_focuses(self):
        with patch('win32gui.GetWindowRect', return_value=(10,20,50,80)), patch('win32gui.ShowWindow') as show, patch('win32gui.SetForegroundWindow') as focus:
            self.assertEqual(ocr_ext._region_for(None,126),dict(x=10,y=20,w=40,h=60))
        show.assert_not_called(); focus.assert_not_called()

    def test_unknown_micro_op_fails_and_stops_following_input(self):
        raw = Mock(); daemon = Mock()
        runner = micro.Runner(daemon, raw, Mock(), 1)
        runner.run([{'op':'nonexistent'}, {'op':'key','key':'x'}])
        self.assertTrue(runner.stopped)
        raw.press.assert_not_called()

    def test_until_timeout_fails_instead_of_completing(self):
        runner = micro.Runner(Mock(), Mock(), Mock(), 1)
        runner.run([{'op':'until','timeout_ms':0,'cond':{'unknown':True}}])
        self.assertTrue(runner.stopped)
        self.assertIn('until',runner.stop_reason)

    def test_unverified_micro_execution_is_not_reported_successful(self):
        runner = Mock()
        runner.result.return_value = dict(steps=1,seconds=0,stopped=False,stop_reason='')
        with patch.object(live,'_ensure_frame',return_value=True), patch.object(live,'_daemon'), patch.object(live,'_controllers',return_value=(Mock(),Mock())), patch.object(micro,'Runner',return_value=runner):
            result = live.tool_run_script({'ops':[{'op':'log','text':'fixture'}]})
        self.assertTrue(result['executed'])
        self.assertFalse(result['success'])
        self.assertEqual(result['status'],'executed_unverified')

    def test_cancelled_micro_execution_is_not_reported_successful(self):
        runner = Mock()
        runner.result.return_value = dict(steps=1,seconds=0,stopped=True,stop_reason='fixture stop')
        with patch.object(live,'_ensure_frame',return_value=True), patch.object(live,'_daemon'), patch.object(live,'_controllers',return_value=(Mock(),Mock())), patch.object(micro,'Runner',return_value=runner):
            result = live.tool_run_script({'ops':[{'op':'log','text':'fixture'}]})
        self.assertFalse(result['executed'])
        self.assertFalse(result['success'])
        self.assertEqual(result['status'],'cancelled')

    def _track_result(self,status):
        from computer_mcp import train
        runner=Mock(); runner.result={'status':status}
        with patch.object(live,'_win_rect',return_value=(0,0,100,100)), patch.object(live,'_TRAINS',{}), patch.object(live,'_TRAIN_SEQ',[0]), patch.object(train,'Runner',return_value=runner):
            return live.tool_track({'action':'run','hwnd':999,'track':{'name':'fixture','steps':[{'name':'wait','action':{'kind':'wait'}}]}})

    def test_unverified_track_completion_is_not_success(self):
        result=self._track_result('done')
        self.assertFalse(result['success'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['status'],'executed_unverified')

    def test_track_timeout_is_not_success(self):
        result=self._track_result('timeout')
        self.assertFalse(result['success'])
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['engine_status'],'timeout')


spec = importlib.util.spec_from_file_location('release_gate',Path(__file__).resolve().parents[1]/'tools'/'release_gate.py')
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)

class ReleaseGateTests(AuthorityCase, unittest.TestCase):
    """The v1.4 gate checks commit binding, the suite and both transports.

    The old 32-case approval benchmark was removed with the approval flow, so
    these tests build a minimal .runtime layout instead of desktop evidence.
    """

    commit = 'a' * 40

    def _layout(self, home: Path, *, commit: str = None, version: str = '1.4.0',
                tools: int = None, failures=None, dirty: bool = False,
                http_status: int = 401, report: bool = True, protocol: bool = True):
        commit = commit or self.commit
        tools = gate.expected_tools() if tools is None else tools
        (home / '.runtime' / 'protocol').mkdir(parents=True, exist_ok=True)
        (home / 'VERSION').write_text(version + chr(10), encoding='utf-8')
        (home / 'pyproject.toml').write_text('version = "' + version + '"' + chr(10), encoding='utf-8')
        (home / '_patched').mkdir(exist_ok=True)
        (home / '_patched' / '__init__.py').write_text(
            '__version__ = "' + version + '"' + chr(10), encoding='utf-8')
        if report:
            (home / '.runtime' / 'test-results.json').write_text(json.dumps(dict(
                source_commit=commit, source_dirty=dirty, scope='full_suite',
                pattern='test_*.py', run=10, failures=failures or [], errors=[],
                skipped=[])), encoding='utf-8')
        if protocol:
            (home / '.runtime' / 'protocol' / 'protocol-smoke.json').write_text(json.dumps(dict(
                stdio=dict(tools=tools, server_version=version),
                http=dict(tools=tools, server_version=version),
                http_unauthenticated_status=http_status)), encoding='utf-8')

    def _run(self, home: Path, commit: str = None) -> tuple:
        import io
        from contextlib import redirect_stdout
        buffer = io.StringIO()
        argv = ['release_gate.py', '--expected-commit', commit or self.commit]
        with patch.object(gate, 'ROOT', home), patch.object(sys, 'argv', argv):
            with redirect_stdout(buffer):
                code = gate.main()
        return code, buffer.getvalue()

    def test_consistent_tree_passes(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home)
            code, output = self._run(home)
        self.assertEqual(code, 0, output)
        self.assertIn('PASS', output)

    def test_missing_regression_report_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home, report=False)
            code, output = self._run(home)
        self.assertEqual(code, 1)
        self.assertIn('regression report missing', output)

    def test_wrong_commit_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home)
            code, output = self._run(home, commit='b' * 40)
        self.assertEqual(code, 1)
        self.assertIn('different commit', output)

    def test_dirty_tree_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home, dirty=True)
            code, output = self._run(home)
        self.assertEqual(code, 1)
        self.assertIn('dirty tree', output)

    def test_tool_count_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home, tools=gate.expected_tools() - 1)
            code, output = self._run(home)
        self.assertEqual(code, 1)
        self.assertIn('tools, got', output)

    def test_http_without_credentials_must_be_401(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home, http_status=200)
            code, output = self._run(home)
        self.assertEqual(code, 1)
        self.assertIn('401', output)

    def test_version_mismatch_blocks(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            self._layout(home)
            (home / 'pyproject.toml').write_text('version = "9.9.9"' + chr(10), encoding='utf-8')
            code, output = self._run(home)
        self.assertEqual(code, 1)
        self.assertIn('version', output)
