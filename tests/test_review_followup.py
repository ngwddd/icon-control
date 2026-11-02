"""Reproduced IR-10..14 regressions; synthetic fixtures never grant the live host."""
import hashlib
import ast
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock,patch
import numpy as np
from authority_fixture import AuthorityCase,approval
from computer_mcp import capture_daemon,conveyor,launcher,live,panic_watch,permission,permission_bridge

class FollowupTests(AuthorityCase,unittest.TestCase):
    fixture_authorized=True
    fixture_monitoring=True

    def daemon(self):
        daemon=capture_daemon.CaptureDaemon()
        from computer_mcp.agent_session import current
        daemon.owner_session=current()
        daemon._frames.append(capture_daemon.Frame(0,time.time(),np.full((8,8,3),121,dtype=np.uint8),active_window='Fixture'))
        return daemon

    def test_record_export_requires_screen_privacy_even_with_file_approval(self):
        auth=dict(approval(),scopes=['file_write','file_delete'])
        permission_bridge.write_state(True,client='fixture',event='action',authorization=auth)
        with patch.object(live,'_daemon',return_value=self.daemon()),tempfile.TemporaryDirectory() as folder, \
             patch.object(live,'_RECORD_ROOT',folder):
            with self.assertRaises(permission.PermissionDenied):live.tool_record({'action':'stop'})
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_record_export_rejects_another_agents_buffer(self):
        daemon=self.daemon();daemon.owner_session='different-agent'
        with patch.object(live,'_daemon',return_value=daemon),tempfile.TemporaryDirectory() as folder, \
             patch.object(live,'_RECORD_ROOT',folder):
            with self.assertRaises(permission.PermissionDenied):live.tool_record({'action':'stop'})
            self.assertEqual(list(Path(folder).iterdir()),[])

    def test_daemon_status_cannot_disclose_other_agents_window_title(self):
        daemon=self.daemon();daemon.owner_session='different-agent'
        daemon._frames.append(capture_daemon.Frame(1,time.time(),np.zeros((8,8,3),dtype=np.uint8),active_window='Private fixture'))
        self.assertIsNone(daemon.status()['last'])

    def test_native_grant_callback_does_not_claim_a_denied_acknowledgement(self):
        from computer_mcp import consent
        tree=ast.parse(Path(consent.__file__).read_text(encoding='utf-8'))
        handler=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='grant')
        for granted in (False,True):
            status=Mock();desired=[False]
            namespace=dict(desired=desired,agents=Mock(current=lambda:0),options={'screen_read':Mock(get=lambda:True)},
                agent_ids=['fixture'],records=[],applications=Mock(curselection=lambda:[]),launches=[],
                ipc=Mock(return_value={'granted':granted}),status=status)
            exec(compile(ast.Module(body=[handler],type_ignores=[]),consent.__file__,'exec'),namespace)
            namespace['grant']()
            self.assertEqual(desired,[granted])
            self.assertEqual('后端已确认：已授权' in status.set.call_args.args[0],granted)

    def test_panic_callback_survives_broken_stderr(self):
        from computer_mcp import panic,input_guard
        stream=Mock();stream.write.side_effect=BrokenPipeError('closed')
        switch=panic.PanicSwitch(verbose=True)
        with patch('sys.stderr',stream),patch.object(panic.security if hasattr(panic,'security') else
                __import__('computer_mcp.security',fromlist=['security']),'latch_stop'),patch.object(input_guard,'release_all') as release:
            switch._on_press(panic.keyboard.Key.esc);switch._on_release(panic.keyboard.Key.esc)
            switch._on_press(panic.keyboard.Key.esc)
        self.assertTrue(switch.triggered);self.assertTrue(release.called)

    def test_own_recording_still_exports_decodable_pixels(self):
        from PIL import Image
        with patch.object(live,'_daemon',return_value=self.daemon()),tempfile.TemporaryDirectory() as folder, \
             patch.object(live,'_RECORD_ROOT',folder),patch('computer_mcp.retention.sweep',return_value={}):
            result=live.tool_record({'action':'stop'})
            self.assertTrue(result['success']);self.assertEqual(result['frames'],1)
            with Image.open(next(Path(result['dir']).glob('*.jpg'))) as frame:
                self.assertEqual(frame.size,(8,8));self.assertEqual(frame.getpixel((0,0)),(121,121,121))

    def test_stable_is_false_without_any_captured_observation(self):
        wheel=conveyor.FrameWheel((0,0,80,80),conveyor.ThumbRing(),conveyor.EventLog())
        self.assertIsNot(conveyor.check_expect({'kind':'stable','ms':0},wheel,wheel.rect),True)

    def test_capture_failure_cannot_be_verified_by_public_track(self):
        def failed_start(runner):runner.wheel.error='PermissionDenied: synthetic capture failure'
        with patch.object(live,'_win_rect',return_value=(0,0,80,80)),patch.object(live,'_TRAINS',{}), \
             patch.object(live,'_TRAIN_SEQ',[0]),patch.object(conveyor.Runner,'start',failed_start), \
             patch.object(conveyor.Runner,'stop'):
            result=live.tool_track({'action':'run','hwnd':999,'track':{'name':'capture-failed','steps':[
                {'name':'stable proof','timeout_ms':30,'expect':{'kind':'stable','ms':0}}]}})
        self.assertFalse(result['success']);self.assertFalse(result['verified'])
        self.assertEqual(result['steps_verified'],0)

    def test_initialize_default_and_legacy_origins_without_explicit_port(self):
        from computer_mcp.security import data_home
        config=data_home()/'state'/'bridge-config.json'
        with patch.object(launcher.security,'latch_stop'),patch.object(launcher,'__file__',
                str(Path(__file__).resolve().parents[1]/'_patched'/'launcher.py')):
            launcher.initialize()
            self.assertTrue(config.is_file())
            self.assertEqual(json.loads(config.read_text())['origins'],['dsh-app://app'])
            config.write_text(json.dumps({'port':23456,'origins':['dsh-app://','dsh-app://localhost']}))
            launcher.initialize()
        self.assertEqual(json.loads(config.read_text()),{'port':23456,'origins':['dsh-app://app']})

    def test_stability_requires_fresh_real_worker_observations(self):
        from screen_fixture import FakeMss
        wheel=conveyor.FrameWheel((0,0,80,80),conveyor.ThumbRing(),conveyor.EventLog(),fps=30)
        with patch('mss.mss',FakeMss):
            wheel.start()
            deadline=time.monotonic()+3
            while wheel.frames<10 and not wheel.error and time.monotonic()<deadline:time.sleep(.02)
            try:
                self.assertTrue(conveyor.check_expect({'kind':'stable','ms':200},wheel,wheel.rect),wheel.error)
                wheel.stop();wheel.join(timeout=3)
                wheel.last_frame_at=time.time()-10
                self.assertFalse(conveyor.check_expect({'kind':'stable','ms':200},wheel,wheel.rect))
            finally:wheel.stop();wheel.join(timeout=3)

    def test_watchdog_cleanup_survives_strict_gbk_and_broken_stdout(self):
        for stream in [io.TextIOWrapper(io.BytesIO(),encoding='gbk',errors='strict'),Mock()]:
            if isinstance(stream,Mock):stream.write.side_effect=BrokenPipeError('closed')
            victim=Mock(pid=os.getpid()+100000)
            with self.subTest(stream=type(stream).__name__),patch('sys.stdout',stream), \
                 patch.object(panic_watch.panic,'PanicSwitch',return_value=Mock()), \
                 patch.object(panic_watch.security,'latch_stop'),patch.object(panic_watch.time,'sleep'), \
                 patch.object(panic_watch.process_registry,'registered',side_effect=[iter([victim]),iter([])]):
                panic_watch.main()
            victim.terminate.assert_called_once()

class RawDesktopEvidenceTests(unittest.TestCase):
    def test_passed_summary_cannot_hide_failed_empty_or_missing_raw_case(self):
        spec=importlib.util.spec_from_file_location('gate_followup',Path(__file__).resolve().parents[1]/'tools/release_gate.py')
        gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);sha='a'*40
            for payload in [dict(run=0,failures=[],skipped=[]),dict(results=[]),
                dict(case_id='B01',status='failed'),dict(results=[{'id':'B01','status':'failed'}]),
                dict(results=[{'id':'B02','status':'passed'}]),
                dict(case_id='B01',status='passed',error='failure'),
                dict(case_id='B01',status='passed',run=0),
                dict(case_id='B01',status='passed',skipped=['not executed'])]:
                data=json.dumps(dict(source_commit=sha,kind='real_desktop',simulated=False,**payload)).encode()
                (root/'raw.json').write_bytes(data)
                case=dict(id='B01',status='passed',elapsed_ms=1,environment={'fixture':'unit'},
                    application_state={'before':0,'after':1},evidence={'path':'raw.json','sha256':hashlib.sha256(data).hexdigest()})
                errors=gate.evaluate({'source_commit':sha,'desktop_tasks':[case]},root,sha)
                with self.subTest(payload=payload):
                    self.assertTrue(any('B01 raw evidence' in error for error in errors),errors)

if __name__=='__main__':unittest.main()
