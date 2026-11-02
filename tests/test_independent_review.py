"""Regressions for the independent review of commit 3300df5."""
import os
import time
import unittest
import tempfile
import subprocess
import sys
from pathlib import Path
import psutil
from unittest.mock import patch,Mock
from authority_fixture import AuthorityCase,approval
from computer_mcp import permission_bridge as bridge,permission,capabilities,agent_session,live,panic_watch
from computer_mcp import consent_ipc,capture_daemon,execution,conveyor
import numpy as np
REAL_TARGET=capabilities.check_target

class ReviewTests(AuthorityCase,unittest.TestCase):
    fixture_authorized=True
    fixture_monitoring=True

    def test_positive_heartbeat_cannot_revive_expired_grant(self):
        previous=bridge.read_state()['revision']
        with patch('time.time',return_value=time.time()+31):
            self.assertFalse(bridge.effective_state()[0])
            bridge.write_state(True,client='fixture',event='hb')
            self.assertFalse(bridge.effective_state()[0])
            self.assertGreater(bridge.read_state()['revision'],previous)

    def test_template_delete_is_not_a_readonly_operation(self):
        bridge.write_state(False,client='fixture',event='action')
        self.assertIsNotNone(permission.check_tool('vision_list',{'delete':'marker'}))
        self.assertIsNone(permission.check_tool('vision_list',{}))

    def test_watchdog_still_terminates_owned_process_after_disk_failure(self):
        victim=Mock(pid=os.getpid()+100000)
        with patch.object(panic_watch.panic,'PanicSwitch',return_value=Mock()), \
             patch.object(panic_watch.security,'latch_stop',side_effect=OSError('disk full')), \
             patch.object(panic_watch.process_registry,'registered',side_effect=[iter([victim]),iter([])]), \
             patch.object(panic_watch.time,'sleep'):
            panic_watch.main()
        victim.terminate.assert_called_once()

    def test_native_module_name_without_broker_instance_cannot_grant(self):
        process=Mock()
        process.cmdline.return_value=['pythonw.exe','-m','computer_mcp.consent']
        process.exe.return_value=__import__('sys').executable
        with patch('psutil.Process',return_value=process),patch.object(consent_ipc,'_native_instances',{}):
            self.assertFalse(consent_ipc._native_client(123,'copied-nonce'))

    def test_real_shadow_module_process_cannot_impersonate_native_ui(self):
        with tempfile.TemporaryDirectory() as folder:
            package=Path(folder)/'computer_mcp';package.mkdir()
            (package/'__init__.py').write_text('')
            (package/'consent.py').write_text(
                "import os,time,pathlib\npathlib.Path('ready').write_text(str(os.getpid()))\ntime.sleep(15)\n")
            process=subprocess.Popen([sys.executable,'-m','computer_mcp.consent'],cwd=folder,
                env=dict(os.environ,PYTHONPATH=''),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                deadline=time.monotonic()+3
                while not (Path(folder)/'ready').exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue((Path(folder)/'ready').exists())
                peer=int((Path(folder)/'ready').read_text())
                self.assertFalse(consent_ipc._native_client(peer))
            finally:
                children=psutil.Process(process.pid).children(recursive=True)
                for child in children:child.terminate()
                process.terminate();process.wait(timeout=3);psutil.wait_procs(children,timeout=3)

    def test_only_owned_isolated_instance_with_matching_nonce_is_accepted(self):
        nonce='test-only-instance-nonce'
        root=Mock(pid=100);root.is_running.return_value=True
        peer=Mock(pid=101);peer.ppid.return_value=100
        executable=Path(getattr(sys,'_base_executable',sys.executable)).with_name('pythonw.exe')
        peer.exe.return_value=str(executable)
        peer.cmdline.return_value=[str(executable),'-I','-m','computer_mcp.consent','--broker-session',nonce]
        with patch('psutil.Process',return_value=peer),patch.object(consent_ipc,'_native_instances',{nonce:{'process':root}}):
            self.assertTrue(consent_ipc._native_client(101,nonce))
            self.assertFalse(consent_ipc._native_client(101,'wrong'))
            peer.ppid.return_value=102
            self.assertFalse(consent_ipc._native_client(101,nonce))

    def test_private_title_detected_after_capture_discards_pixels(self):
        from screen_fixture import FakeMss
        daemon=capture_daemon.CaptureDaemon(scale=1)
        class OneFrame(FakeMss):
            def grab(self,box):
                daemon._stop.set()
                return super().grab(box)
        with patch('mss.mss',OneFrame),patch.object(capture_daemon,'_active_window_title',side_effect=['Fixture','Password manager']):
            daemon._loop()
        self.assertEqual(len(daemon._frames),0)
        self.assertEqual(daemon.frames_skipped,1)

    def test_other_agent_cannot_read_originators_trace(self):
        secret='private ordinary words'
        live._session_runs()['last']={'trace':secret}
        with agent_session.bind('d'*48):
            with self.assertRaises(permission.PermissionDenied):live.tool_trace({})
            self.assertEqual(live._session_runs()['last'],{})

    def test_executable_launch_approval_does_not_authorize_unselected_pid(self):
        import win32gui,win32process
        auth=dict(approval(),applications=[],launches=[{'exe':'app.exe','arguments':'--allowed','sha256':'x'}])
        process=Mock();process.cmdline.return_value=['app.exe','--unrelated']
        with patch.object(win32gui,'GetWindowText',return_value='User app'), \
             patch.object(win32gui,'GetAncestor',return_value=12), \
             patch.object(win32process,'GetWindowThreadProcessId',return_value=(1,42)), \
             patch('psutil.Process',return_value=process), \
             patch.object(capabilities,'process_record',return_value={'pid':42,'created':3,'exe':'app.exe'}):
            self.assertIsNotNone(REAL_TARGET({'authorization':auth},hwnd=12))

    def test_capture_worker_retains_the_http_agents_context(self):
        from screen_fixture import FakeMss
        seen=[]
        with agent_session.bind('e'*48):
            wheel=conveyor.FrameWheel((0,0,80,80),conveyor.ThumbRing(),conveyor.EventLog())
        class OneFrame(FakeMss):
            def grab(self,box):
                wheel.stop()
                return super().grab(box)
        def require(tool,*args):
            seen.append(agent_session.current())
            if agent_session.current()!='e'*48:raise permission.PermissionDenied('Wrong HTTP Agent')
        with patch('mss.mss',OneFrame),patch.object(permission,'require',side_effect=require):
            wheel.start();wheel.join(timeout=3)
        self.assertFalse(wheel.is_alive())
        self.assertGreater(len(wheel.ring),0,wheel.error)
        self.assertTrue(seen)
        self.assertEqual(set(seen),{'e'*48})

    def test_retained_trace_removes_raw_input_content(self):
        from computer_mcp import micro
        secret='private ordinary typed phrase'
        runner=Mock()
        runner.result.return_value=dict(steps=1,seconds=0,stopped=False,stop_reason='',trace=[{'key':secret,'text':secret}])
        with patch.object(live,'_ensure_frame',return_value=True),patch.object(live,'_daemon'), \
             patch.object(live,'_controllers',return_value=(Mock(),Mock())),patch.object(micro,'Runner',return_value=runner):
            live.tool_run_script({'ops':[{'op':'log','text':secret}]})
        self.assertNotIn(secret,__import__('json').dumps(live.tool_trace({})))

    def _track_with_condition(self,condition):
        with patch.object(live,'_win_rect',return_value=(0,0,80,80)), \
             patch.object(live,'_TRAINS',{}),patch.object(live,'_TRAIN_SEQ',[0]), \
             patch.object(conveyor.Runner,'start'),patch.object(conveyor.Runner,'stop'), \
             patch.object(conveyor,'check_expect',return_value=condition):
            return live.tool_track({'action':'run','hwnd':999,'track':{'name':'isolated','steps':[
                {'name':'required check','timeout_ms':5,'on_fail':'continue',
                 'expect':{'kind':'text','query':'never true'}}]}})

    def test_continued_timeout_cannot_be_verified_by_public_track_wrapper(self):
        result=self._track_with_condition(False)
        self.assertFalse(result['success'])
        self.assertFalse(result['verified'])
        self.assertEqual(result['steps_done'],0)
        self.assertEqual(result['steps_verified'],0)
        self.assertEqual(result['failed_steps'],[1])

    def test_true_postcondition_is_still_verified_by_public_track_wrapper(self):
        result=self._track_with_condition(True)
        self.assertTrue(result['success'])
        self.assertTrue(result['verified'])
        self.assertEqual(result['steps_verified'],1)

if __name__=='__main__':unittest.main()
