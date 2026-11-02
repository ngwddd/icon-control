"""rc2 regressions: native flags, policy faults and explicit capabilities.

All input sinks here are fake. The manual acceptance harness uses the real
signed human grant and must never reuse these isolated authority fixtures.
"""
import asyncio
import ctypes
import unittest
import subprocess
from pathlib import Path
from unittest.mock import patch,Mock
from authority_fixture import AuthorityCase
from computer_mcp import native_mouse,permission,tool_registry,execution,micro
from computer_mcp.input_guard import InjectedMouse,MouseController
from computer_mcp.tool_spec import ToolSpec

class NativeMovementTests(unittest.TestCase):
    def test_windows_input_layout(self):
        self.assertEqual(ctypes.sizeof(native_mouse.INPUT),40 if ctypes.sizeof(ctypes.c_void_p)==8 else 28)

    def test_absolute_packets_land_inside_destination_pixels(self):
        desktop=(-1920,-200,4480,1640)
        for x,y in [(-1920,-200),(-1919,-199),(0,0),(723,329),(2559,1439)]:
            packet=native_mouse.absolute_packet(x,y,desktop).u.mi
            self.assertEqual(desktop[0]+packet.dx*desktop[2]//65536,x)
            self.assertEqual(desktop[1]+packet.dy*desktop[3]//65536,y)
            self.assertEqual(packet.dwFlags,native_mouse.MOVE|native_mouse.ABSOLUTE|native_mouse.VIRTUALDESK)

    def test_outside_and_nonfinite_positions_are_rejected(self):
        for x,y in [(100,1),(-1,1),(1,float('nan'))]:
            with self.assertRaises(ValueError):native_mouse.absolute_packet(x,y,(0,0,100,100))

    def test_absolute_and_relative_use_injected_backend(self):
        controller=InjectedMouse()
        with patch('computer_mcp.native_mouse.move_absolute') as move, patch.object(InjectedMouse,'_position_get',return_value=(10,20)):
            controller.position=(30,40)
            controller.move(5,-3)
        self.assertEqual(move.call_args_list[0].args,(30,40))
        self.assertEqual(move.call_args_list[1].args,(15,17))

    def test_sendinput_failure_raises_without_cursor_fallback(self):
        api=Mock()
        api.GetSystemMetrics.side_effect=[0,0,100,100]
        api.SendInput.return_value=0
        with patch('ctypes.WinDLL',return_value=api):
            with self.assertRaises(OSError):native_mouse.move_absolute(10,10)
        api.SendInput.assert_called_once()

    def test_physical_dpi_context_is_restored_on_input_failure(self):
        api=Mock();api.SetThreadDpiAwarenessContext.return_value=1234
        api.GetSystemMetrics.side_effect=[0,0,2560,1440];api.SendInput.return_value=0
        with patch('ctypes.WinDLL',return_value=api):
            with self.assertRaises(OSError):native_mouse.move_absolute(2400,300)
        self.assertEqual(api.SetThreadDpiAwarenessContext.call_args_list[-1].args,(1234,))

    def test_relative_position_reads_physical_cursor_coordinates(self):
        from ctypes import wintypes
        api=Mock()
        def position(pointer):
            point=ctypes.cast(pointer,ctypes.POINTER(wintypes.POINT)).contents
            point.x,point.y=2400,300
            return 1
        api.GetPhysicalCursorPos.side_effect=position
        with patch('ctypes.WinDLL',return_value=api):
            self.assertEqual(InjectedMouse().position,(2400,300))

class PolicyFaultTests(unittest.TestCase):
    def test_client_factory_reload_replaces_legacy_heartbeat(self):
        root=Path(__file__).resolve().parents[1]
        result=subprocess.run(['node',str(root/'tests/manual/client_protocol_test.cjs')],
                              cwd=root,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('client protocol and hot reload passed',result.stdout)
    def test_every_mcp_policy_exception_blocks_composite_dispatch(self):
        from computer_mcp import mcp
        state=Mock(config={'observe_mouse_position':False,'observe_mouse_button_states':False,'observe_keyboard_key_states':False})
        for name in ('run_script','track','macro_run','housekeeping','list_windows'):
            with self.subTest(name=name), patch.object(mcp,'computer_state',state), patch.object(permission,'check_tool',side_effect=RuntimeError('fixture failure')), patch.object(mcp,'_dispatch') as dispatch, patch.object(mcp,'format_response',side_effect=lambda result,*a,**kw:result):
                result=asyncio.run(mcp._call_tool_impl(name,{}))
            self.assertTrue(result['blocked'])
            dispatch.assert_not_called()

    def test_effects_are_required_and_validated(self):
        with self.assertRaises(TypeError):ToolSpec(name='new',zone='Z2',description='',schema={})
        for effects in [(),('unknown',)]:
            with self.assertRaises(ValueError):ToolSpec(name='new',zone='Z2',description='',schema={},effects=effects)

    def test_parameter_effects_never_relax_unknown_actions(self):
        for name,args in [('housekeeping',{'action':'status'}),('capture_config',{}),('glyph',{'action':'list'}),('layout_mem',{'action':'resolve'})]:
            spec=tool_registry.get(name)
            self.assertFalse(spec.needs_authority(args))
            self.assertTrue(spec.needs_authority())
            self.assertTrue(spec.needs_authority({'action':'future_mutating_action','scale':1}))

class GuardedInputTests(AuthorityCase,unittest.TestCase):
    fixture_authorized=True
    fixture_monitoring=True

    def test_micro_scroll_uses_guarded_existing_tool(self):
        raw=Mock();runner=micro.Runner(Mock(),Mock(),raw,1)
        runner.run([{'op':'scroll','dx':0,'dy':-3}])
        raw.scroll.assert_called_once_with(0,-3)

    def test_revocation_blocks_cursor_before_injection(self):
        from computer_mcp import permission_bridge
        raw=Mock();controller=MouseController(raw)
        permission_bridge.write_state(False,client='fixture',event='action')
        with self.assertRaises(permission.PermissionDenied):controller.move(3,0)
        raw.move.assert_not_called()

    def test_parameter_policy_applies_to_direct_entry(self):
        from computer_mcp import permission_bridge,live
        permission_bridge.write_state(False,client='fixture',event='action')
        self.assertIsNone(permission.check_tool('housekeeping',{'action':'status'}))
        self.assertIsNotNone(permission.check_tool('housekeeping',{'action':'sweep'}))
        with self.assertRaises(permission.PermissionDenied):live.tool_housekeeping({'action':'sweep'})
