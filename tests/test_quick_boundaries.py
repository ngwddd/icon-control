"""Security boundary regressions using isolated stores and fake controls."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from authority_fixture import AuthorityCase
from computer_mcp import agent_session, capabilities, live, ocr_ext, permission, retention, ui_ext, workspace
from computer_mcp.dataset import writer, export


class BoundaryTests(AuthorityCase, unittest.TestCase):
    fixture_authorized = True
    fixture_monitoring = True

    def test_capture_initialization_failure_is_terminal(self):
        daemon=Mock()
        daemon.start.return_value={'ok':False}
        with patch.object(live,'_daemon',return_value=daemon):
            result=live.tool_capture({'action':'start'})
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['success'])

    def test_running_is_accepted_but_not_verified(self):
        result=live._track_state({'steps_done':1,'steps_verified':1,'status':'done'},True,1)
        self.assertTrue(result['accepted'])
        self.assertFalse(result['success'])
        self.assertEqual(result['status'],'running')

    def test_no_pixels_without_screen_read(self):
        with patch.object(permission,'require',side_effect=permission.PermissionDenied('screen_read')), patch('win32gui.GetWindowDC') as dc:
            with self.assertRaises(permission.PermissionDenied):ocr_ext._print_window(999)
            dc.assert_not_called()

    def test_no_implicit_sweep_on_capture_start(self):
        from computer_mcp.capture_daemon import CaptureDaemon
        d=CaptureDaemon()
        with patch.object(d,'_loop'),patch.object(retention,'sweep_all') as sweep:
            d.start()
        sweep.assert_not_called()

    def test_delete_scope_at_cleanup(self):
        with patch.object(capabilities,'has_scope',return_value=False):
            with self.assertRaises(permission.PermissionDenied):retention.sweep_temp()

    def test_read_boundary_and_size(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name in ('../outside',str(root.parent/'other')):
                with self.assertRaises(ValueError):workspace.read_text(name,root)
            (root/'large').write_bytes(b'x'*1048577)
            with self.assertRaises(ValueError):workspace.read_text('large',root)
            with patch.object(capabilities,'has_scope',return_value=False):
                with self.assertRaises(permission.PermissionDenied):workspace.readable_path('large',root)

    def test_uia_rejects_control_from_other_window(self):
        c=Mock(ProcessId=100)
        c.GetTopLevelControl.return_value.NativeWindowHandle=8
        with patch('win32gui.GetAncestor',return_value=9):
            with self.assertRaises(permission.PermissionDenied):ui_ext._check_control(c,9)

    def test_agent_cannot_export_foreign_or_unowned_rows(self):
        with tempfile.TemporaryDirectory() as folder, patch.multiple(writer,ROOT=Path(folder),DATA=Path(folder)/'raw'):
            path=writer.append_episode({'id':'only-A','args':{}})
            with path.open('a') as out:out.write('{"id":"legacy"}\n')
            with agent_session.bind('b'*48):
                self.assertEqual(list(writer._iter_episodes()),[])
                self.assertEqual(export.export(tag='B')['episodes'],0)
            self.assertEqual([r['id'] for r in writer._iter_episodes()],['only-A'])
