"""Native API regressions with fake HWNDs, fake actuators and isolated authority."""
import hashlib
import json
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
        self.assertEqual(result['status'],'timeout')


spec = importlib.util.spec_from_file_location('release_gate',Path(__file__).resolve().parents[1]/'tools'/'release_gate.py')
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)

class ReleaseGateTests(unittest.TestCase):
    def test_missing_desktop_acceptance_blocks(self):
        errors = gate.evaluate({},Path.cwd())
        self.assertTrue(any('B32' in error for error in errors))
        self.assertTrue(any('P0' in error for error in errors))

    def test_tampered_evidence_and_path_escape_block(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root/'evidence.txt').write_text('fixture')
            case = dict(status='passed', elapsed_ms=1, environment='fake unit fixture',
                        application_state='fake state', evidence={'path':'evidence.txt','sha256':'wrong'})
            report = dict(p0_review='passed',clean_windows_install='passed',known_false_success_paths=0,
                          unit_failures=0,unit_errors=0,desktop_tasks=[dict(case,id=f'B{i:02}') for i in range(1,33)])
            self.assertTrue(any('hash mismatch' in error for error in gate.evaluate(report,root)))
            report['desktop_tasks'][0]['evidence']={'path':'../outside','sha256':'wrong'}
            self.assertTrue(any('B01 evidence missing' in error for error in gate.evaluate(report,root)))

    def test_complete_fixture_can_validate_without_claiming_live_acceptance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp);sha='a'*40
            data=json.dumps(dict(source_commit=sha,kind='real_desktop',simulated=False,
                                 note='Validator unit fixture, not release evidence')).encode()
            (root/'fixture').write_bytes(data)
            unit=json.dumps(dict(source_commit=sha,run=1,failures=[],errors=[],skipped=[])).encode()
            (root/'unit.json').write_bytes(unit)
            cases=[dict(id=f'B{i:02}',status='passed',elapsed_ms=1,environment='unit fixture',
                        application_state='fixture',evidence={'path':'fixture','sha256':hashlib.sha256(data).hexdigest()}) for i in range(1,33)]
            report=dict(p0_review='passed',clean_windows_install='passed',known_false_success_paths=0,
                        source_commit=sha,implementer_id='implementation-fixture',unit_skipped=0,
                        independent_review=dict(status='passed',source_commit=sha,reviewer_id='independent-fixture',
                            open_p0=0,open_p1=0,evidence={'path':'fixture','sha256':hashlib.sha256(data).hexdigest()}),
                        unit_evidence={'path':'unit.json','sha256':hashlib.sha256(unit).hexdigest()},
                        unit_failures=0,unit_errors=0,desktop_tasks=cases)
            self.assertEqual(gate.evaluate(report,root,sha),[])
            self.assertTrue(gate.evaluate(report,root,'b'*40),'Different commit must fail')
            report['independent_review']['reviewer_id']='implementation-fixture'
            self.assertTrue(gate.evaluate(report,root,sha),'Self review must fail')
