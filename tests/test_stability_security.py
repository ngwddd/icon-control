"""S1 regressions. All authority and input backends are isolated test fixtures."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, Mock
from http.server import ThreadingHTTPServer

from computer_mcp import permission as P, permission_bridge as B, security as S
from computer_mcp import control as C, execution as E, tool_registry as R, panic
from computer_mcp.input_guard import KeyboardController

class SecurityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, ICON_CONTROL_HOME=self.temp.name,
                              DSH_MOUSE_GATE='off', DSH_CONTROL='on')
        self.env.start()
        state = Path(self.temp.name)/'state'; state.mkdir()
        self.paths = patch.multiple(B, STATE_DIR=str(state), STATE_PATH=str(state/'permission.json'),
                                    LOG_PATH=str(state/'bridge.log'), CLIENTS={}, _last_action=None, _revision=0)
        self.paths.start()
        self.pstate = patch.object(P, 'STATE_PATH', B.STATE_PATH); self.pstate.start()
        self.token = S.provision_token()
        C.STATE.update(owner='idle', since=time.time(), last_user=0, last_inject=0, takeovers=0, reason='')
        self.emergency = Mock(triggered=False, ready=True)
        self.panic_patch = patch.object(panic, 'default', return_value=self.emergency); self.panic_patch.start()
        self.watch = patch.object(C, 'ensure_watcher', return_value=True); self.watch.start()

    def tearDown(self):
        self.watch.stop(); self.panic_patch.stop(); self.pstate.stop(); self.paths.stop(); self.env.stop(); self.temp.cleanup()

    def grant(self):
        B.write_state(True, client='human', event='action')

    def request(self, token='', origin=None, body=None):
        server = ThreadingHTTPServer(('127.0.0.1',0), B.Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        try:
            client = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
            headers = {'Origin':origin} if origin else {}
            client.request('POST' if body is not None else 'GET', '/state?k='+token,
                           body=json.dumps(body) if body is not None else None, headers=headers)
            response=client.getresponse(); result=(response.status,response.read()); client.close(); return result
        finally:
            server.shutdown(); server.server_close(); thread.join()

    def test_missing_token_from_first_request_denied(self):
        self.assertEqual(self.request()[0],403)

    def test_wrong_token_denied(self):
        self.assertEqual(self.request('wrong')[0],403)

    def test_missing_server_secret_denied(self):
        S.token_path().unlink()
        self.assertEqual(self.request(self.token)[0],403)

    def test_hostname_suffix_origin_denied(self):
        for source in ('http://localhost.evil.test','http://127.0.0.1.evil.test','https://example.test'):
            with self.subTest(source=source): self.assertEqual(self.request(self.token,source)[0],403)

    def test_authenticated_read(self):
        self.assertEqual(self.request(self.token)[0],200)

    def test_string_boolean_cannot_grant(self):
        self.assertEqual(self.request(self.token,body={'granted':'false'})[0],400)
        self.assertFalse(P.status()['granted'])

    def test_heartbeat_never_creates_authority(self):
        B.write_state(True,client='human',event='hb')
        self.assertFalse(P.status()['granted'])

    def test_user_action_grants(self):
        self.grant(); self.assertTrue(P.status()['granted'])

    def test_revoke_survives_heartbeats(self):
        self.grant(); B.write_state(False,client='other',event='action')
        B.write_state(True,client='human',event='hb')
        B.write_state(True,client='other',event='hb')
        self.assertFalse(P.status()['granted'])

    def test_grant_survives_own_heartbeat_and_unrelated_window(self):
        self.grant(); B.write_state(True,client='human',event='hb')
        B.write_state(False,client='other',event='hb')
        self.assertTrue(P.status()['granted'])

    def test_unsigned_file_rejected_even_with_env_disabled(self):
        Path(P.STATE_PATH).write_text(json.dumps(dict(granted=True,source='bridge',checked_at_ts=time.time())))
        self.assertFalse(P.status()['granted'])

    def test_expired_signed_file_rejected(self):
        self.grant(); data=B.read_state();data['checked_at_ts']=time.time()-100
        data['signature']=S.signature(data,self.token)
        Path(P.STATE_PATH).write_text(json.dumps(data))
        self.assertFalse(P.status()['granted'])

    def test_tampered_signed_state_denied(self):
        self.grant();data=B.read_state();data['revision']+=1
        Path(P.STATE_PATH).write_text(json.dumps(data));self.assertFalse(P.status()['granted'])

    def test_unknown_internal_tool_denied(self):
        self.assertIsNotNone(P.check_tool('unregistered_mutator'))

    def test_window_mutation_requires_authority(self):
        for name in ('close_window','move_window','switch_virtual_desktop','set_config','macro_save'):
            with self.subTest(name=name): self.assertIsNotNone(P.check_tool(name))

    def test_alias_cannot_bypass_deny(self):
        self.grant()
        with patch.dict(os.environ,DSH_TOOLS_DENY='win_close'):
            self.assertIsNotNone(P.check_tool('close_window'))
            self.assertIsNotNone(P.check_tool('win_close'))

    def test_claim_cannot_override_takeover(self):
        self.grant(); C.note_physical('human')
        self.assertFalse(C.claim()['ok']);self.assertEqual(C.STATE['owner'],'user')

    def test_claim_requires_listener_startup(self):
        self.grant()
        with patch.object(C,'ensure_watcher',return_value=False): self.assertFalse(C.claim()['ok'])

    def test_physical_input_not_hidden_by_quiet_window(self):
        C.STATE['owner']='ai'; C.quiet(); C.note_physical('physical')
        self.assertEqual(C.STATE['owner'],'user')

    def test_control_exception_fails_closed(self):
        self.grant()
        with patch.object(C,'blocking_reason',side_effect=RuntimeError('offline')):
            self.assertIsNotNone(P.check_tool('click'))

    def test_panic_stops_input(self):
        self.grant(); self.emergency.triggered=True
        self.assertIsNotNone(P.check_tool('click'))

    def test_listener_failure_stops_input(self):
        self.grant();self.emergency.ready=False
        self.assertIsNotNone(P.check_tool('click'))

    def test_typing_rechecks_each_character_and_releases_key(self):
        self.grant(); raw=Mock()
        def pressed(key): B.write_state(False,client='human',event='action')
        raw.press.side_effect=pressed
        keyboard=KeyboardController(raw)
        with self.assertRaises(P.PermissionDenied):
            with E.operation('type'): keyboard.type('abc')
        raw.press.assert_called_once_with('a');raw.release.assert_called_once_with('a')

    def test_regrant_does_not_resume_cancelled_task(self):
        self.grant()
        with E.operation('batch'):
            B.write_state(False,client='human',event='action');self.grant()
            with self.assertRaises(P.PermissionDenied): E.check('click')

    def test_dispatch_direct_readonly_deny(self):
        from computer_mcp.zones.dispatch import dispatch
        with patch.dict(os.environ,DSH_TOOLS_DENY='list_windows'):
            with self.assertRaises(P.PermissionDenied):
                dispatch('win_list',{},computer_state=Mock(),mouse_controller=Mock(),keyboard_controller=Mock())

    def test_all_registered_tools_have_effects(self):
        self.assertEqual(len(R.TOOLS),89)
        for spec in R.iter_specs(): self.assertTrue(spec.effects,spec.name)

    def test_double_escape_requires_two_physical_presses(self):
        from pynput.keyboard import Key
        switch=panic.PanicSwitch(verbose=False)
        switch._on_press(Key.esc);switch._on_press(Key.esc)
        self.assertFalse(switch.triggered)
        switch._on_release(Key.esc);switch._on_press(Key.esc)
        self.assertTrue(switch.triggered)

if __name__=='__main__': unittest.main()
