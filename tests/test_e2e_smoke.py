"""Real product smoke tests against the dedicated fixture, with human approval."""
import base64
from io import BytesIO
import json
import os
from pathlib import Path
import time
import unittest
from PIL import Image

@unittest.skipUnless(os.environ.get('DSH_E2E')=='1','Real desktop: human must approve the dedicated acceptance session')
class TestE2E(unittest.TestCase):
    observations=[]
    def fixture_state(self):
        path=Path(os.environ['ICON_CONTROL_E2E_STATE'])
        for _ in range(20):
            try:
                self.assertLess(time.time()-path.stat().st_mtime,3,'Fixture state is stale')
                return json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError,ValueError):time.sleep(.05)
        self.fail('Fixture state could not be read')

    def setUp(self):
        from computer_mcp import permission,control,appkit,ui_ext
        import win32gui
        self.assertTrue(permission.status().get('granted'),'A human must approve this exact test process')
        windows=[]
        win32gui.EnumWindows(lambda hwnd,_:windows.append(hwnd) if
            win32gui.GetWindowText(hwnd)=='Icon Control rc2 acceptance' else None,None)
        self.assertEqual(len(windows),1,'Exactly one dedicated fixture is required')
        self.hwnd=windows[0]
        deadline=time.monotonic()+15
        while not control.claim('Real desktop smoke').get('ok') and time.monotonic()<deadline:time.sleep(.2)
        self.assertEqual(control.status()['owner'],'ai')
        self.assertTrue(appkit.activate(self.hwnd).get('ok'))
        self.assertTrue(ui_ext.ui_click('Input',hwnd=self.hwnd,exact=True,
            mouse=__import__('computer_mcp')._default_mouse_controller).get('ok'))
        self.assertEqual(win32gui.GetForegroundWindow(),self.hwnd)

    def combo(self,key):
        from computer_mcp.actions import keyboard
        from computer_mcp import _default_keyboard_controller as controller
        keyboard.key_down('ctrl',controller=controller)
        try: keyboard.key_press(key,controller=controller)
        finally: keyboard.key_up('ctrl',controller=controller)

    def enter(self,text):
        from computer_mcp.actions import keyboard
        from computer_mcp import _default_keyboard_controller as controller
        self.combo('a')
        result=keyboard.type_text(text,controller=controller)
        self.assertTrue(result.get('success'))
        deadline=time.monotonic()+3
        while self.fixture_state()['text']!=text and time.monotonic()<deadline:time.sleep(.1)
        self.assertEqual(self.fixture_state()['text'],text)
        return self.fixture_state()

    def test_1_clipboard_roundtrip(self):
        import win32clipboard
        from clipboard_fixture import preserve_clipboard
        text='IconControl-clipboard-'+str(time.time_ns())
        with preserve_clipboard() as preserved:
            state=self.enter(text)
            self.combo('a');preserved.before_copy();self.combo('c');time.sleep(.3)
            win32clipboard.OpenClipboard()
            try: copied=win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
            finally: win32clipboard.CloseClipboard()
            self.assertEqual(copied,text)
            preserved.claim_test_text(text,self.fixture_state()['pid'])
            self.combo('a')
            from computer_mcp.actions import keyboard
            keyboard.key_press('backspace')
            for _ in range(30):
                cleared=self.fixture_state()
                if cleared['text']=='':break
                time.sleep(.1)
            self.assertEqual(cleared['text'],'','Clear must actually change the fixture before testing paste')
            self.combo('v')
            for _ in range(30):
                pasted=self.fixture_state()
                if pasted['text']==text:break
                time.sleep(.1)
            self.assertEqual(pasted['text'],text)
            self.observations.append(dict(test=self.id(),application_state=pasted,
                state_before_clear=state,state_after_clear=cleared,clipboard_matches=True,pasted_text_matches=True))

    def test_2_window_enumeration(self):
        import win32gui
        from computer_mcp import execution
        from computer_mcp.actions import window
        from computer_mcp.core.screenshot import capture_screenshot
        windows=window.list_windows()
        self.assertIn(self.hwnd,[item['hwnd'] for item in windows.get('windows',[])])
        with execution.operation('screenshot'):
            left,top,right,bottom=win32gui.GetWindowRect(self.hwnd)
            shot=capture_screenshot(dict(x=left,y=top,w=right-left,h=bottom-top))
        encoded=shot.get('data') or shot.get('image') or shot.get('base64')
        self.assertIsInstance(encoded,str)
        with Image.open(BytesIO(base64.b64decode(encoded))) as image:
            self.assertGreater(image.width,0);self.assertGreater(image.height,0)
            self.assertTrue(any(low!=high for low,high in image.convert('RGB').getextrema()))
        self.observations.append(dict(test=self.id(),application_state=self.fixture_state(),
                                      capture_width=shot.get('width'),capture_height=shot.get('height')))

    def test_3_TextEditor_typing(self):
        text='Icon Control 中文与符号验证：你好，世界！123 [] {} @#$%\\n第二行 ✓'
        state=self.enter(text)
        self.observations.append(dict(test=self.id(),application_state=state,exact_text_matches=True))

if __name__=='__main__':unittest.main(verbosity=2)
