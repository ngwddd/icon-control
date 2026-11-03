"""Real Windows pipes, process identity and singleton tests; never grant input."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import psutil
from unittest.mock import patch
from computer_mcp import consent_ipc, security

class NativeIpcTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        cls.environment=patch.dict(os.environ,ICON_CONTROL_HOME=cls.temp.name)
        cls.environment.start();security.provision_token()
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));cls.port=listener.getsockname()[1]
        cls.log=open(Path(cls.temp.name)/'bridge-test.log','w',encoding='utf-8')
        cls.child=subprocess.Popen([sys.executable,'-m','computer_mcp.permission_bridge','--port',str(cls.port)],
            env=dict(os.environ),stdout=cls.log,stderr=cls.log,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(60):
            if cls.child.poll() is not None: break
            try:
                consent_ipc.request('authority',agent_session='a'*48,session='',revision=0)
                return
            except Exception: time.sleep(.05)
        cls.log.flush()
        raise RuntimeError('Native IPC startup failed: '+(Path(cls.temp.name)/'bridge-test.log').read_text())

    @classmethod
    def tearDownClass(cls):
        children=psutil.Process(cls.child.pid).children(recursive=True)
        for child in children: child.terminate()
        cls.child.terminate();cls.child.wait(timeout=5)
        psutil.wait_procs(children,timeout=5);cls.log.close()
        print((Path(cls.temp.name)/'state'/'bridge.log').read_text(encoding='utf-8'))
        cls.environment.stop();cls.temp.cleanup()

    def test_real_pipe_cannot_be_used_to_self_grant(self):
        with self.assertRaises(PermissionError):
            consent_ipc.request('grant',agent_session='a'*48,scopes=['input'],applications=[])

    def test_real_pipe_authority_is_false_without_human_approval(self):
        self.assertFalse(consent_ipc.request('authority',agent_session='a'*48,session='',revision=0)['granted'])

    def test_concurrent_authority_queries_do_not_fail_on_pipe_connect_race(self):
        from concurrent.futures import ThreadPoolExecutor
        def query(_):
            return consent_ipc.request('authority',timeout_ms=80,agent_session='a'*48,session='',revision=0)
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses=list(pool.map(query,range(80)))
        self.assertEqual(len(responses),80)
        self.assertTrue(all(result=={'granted':False} for result in responses))

    def test_permanently_busy_connection_keeps_the_original_deadline_and_releases_lock(self):
        import pywintypes,win32file,win32pipe
        started=time.monotonic()
        with patch.object(win32pipe,'WaitNamedPipe'),patch.object(win32file,'CreateFile',
                side_effect=pywintypes.error(231,'CreateFile','busy')) as create:
            with self.assertRaises(TimeoutError):consent_ipc.request('authority',timeout_ms=20)
            self.assertGreater(create.call_count,1)
        self.assertLess(time.monotonic()-started,.5)
        self.assertFalse(consent_ipc.request('authority',agent_session='a'*48,session='',revision=0)['granted'])

    def test_access_denied_is_not_retried_as_a_connection_race(self):
        import pywintypes,win32file,win32pipe
        with patch.object(win32pipe,'WaitNamedPipe'),patch.object(win32file,'CreateFile',
                side_effect=pywintypes.error(5,'CreateFile','denied')) as create:
            with self.assertRaises(pywintypes.error):consent_ipc.request('authority')
            self.assertEqual(create.call_count,1)

    def test_second_bridge_different_port_cannot_replace_authority(self):
        with socket.socket() as listener:
            listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
        before=(Path(self.temp.name)/'state'/'mouse-permission.json').read_bytes()
        result=subprocess.run([sys.executable,'-m','computer_mcp.permission_bridge','--port',str(port)],
            env=dict(os.environ),capture_output=True,timeout=8,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(before,(Path(self.temp.name)/'state'/'mouse-permission.json').read_bytes())

    def test_stalled_pipe_peer_times_out_without_wedging_authority(self):
        import win32file, win32con, win32pipe
        win32pipe.WaitNamedPipe(consent_ipc.pipe_name(),1000)
        pipe=win32file.CreateFile(consent_ipc.pipe_name(),win32con.GENERIC_READ|win32con.GENERIC_WRITE,
            0,None,win32con.OPEN_EXISTING,0,None)
        try:
            time.sleep(.6)
        finally: win32file.CloseHandle(pipe)
        self.assertFalse(consent_ipc.request('authority',agent_session='a'*48,session='',revision=0)['granted'])

if __name__=='__main__':unittest.main()
