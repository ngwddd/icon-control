"""User-requested one-second physical movement policy; no real input sinks."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch,Mock
from authority_fixture import AuthorityCase
from computer_mcp import control as C,execution,permission
from computer_mcp.input_guard import MouseController,Button

class MouseTakeoverDelayTests(AuthorityCase,unittest.TestCase):
    fixture_authorized=True
    fixture_monitoring=True

    def setUp(self):
        super().setUp()
        self.motion=patch.object(C,'_mouse_motion',{'started':None,'last':None,'point':None})
        self.motion.start();self.addCleanup(self.motion.stop)
        self.generation=patch.object(C,'_generation',0)
        self.generation.start();self.addCleanup(self.generation.stop)
        C.STATE.update(owner='ai',takeovers=0)

    def move_at(self,seconds,point):
        with patch.object(C.time,'monotonic',return_value=seconds):
            return C.note_mouse_move(*point)

    def test_brief_motion_does_not_cancel_or_release_input(self):
        with patch('computer_mcp.input_guard.release_all') as release:
            for index,t in enumerate((0,.1,.3,.55,.8,.99)):
                self.assertFalse(self.move_at(t,(index,10)))
        self.assertEqual(C.STATE['owner'],'ai')
        self.assertEqual(C._generation,0)
        release.assert_not_called()

    def test_one_second_continuous_motion_takes_over(self):
        for index,t in enumerate((0,.2,.4,.6,.8)):
            self.assertFalse(self.move_at(t,(index,10)))
        self.assertTrue(self.move_at(1.001,(6,10)))
        self.assertEqual(C.STATE['owner'],'user')
        self.assertEqual(C.STATE['takeovers'],1)

    def test_separate_brief_gestures_do_not_accumulate(self):
        for index,t in enumerate((0,.2,.4,.9,1.1,1.3,1.8,2.0)):
            self.assertFalse(self.move_at(t,(index,10)))
        self.assertEqual(C.STATE['owner'],'ai')

    def test_a_single_move_never_arms_a_delayed_stop(self):
        self.move_at(0,(10,10))
        with patch.object(C.time,'monotonic',return_value=2):
            state=C.status()
        self.assertEqual(state['owner'],'ai')
        self.assertEqual(state['mouse_move_pending_s'],0)
        self.assertFalse(self.move_at(2.1,(11,10)))

    def test_duplicate_coordinates_are_not_continuous_motion(self):
        for t in (0,.2,.4,.6,.8,1.2):
            self.assertFalse(self.move_at(t,(10,10)))
        self.assertEqual(C.STATE['owner'],'ai')

    def test_keyboard_and_click_takeover_still_immediate(self):
        for reason in ('keyboard input','mouse click','mouse scroll'):
            with self.subTest(reason=reason):
                C.STATE['owner']='ai'
                self.move_at(0,(1,1))
                C.note_physical(reason)
                self.assertEqual(C.STATE['owner'],'user')
                self.assertIsNone(C._mouse_motion['started'])

    def test_confirmed_motion_releases_own_held_button(self):
        raw=Mock();mouse=MouseController(raw);mouse.press(Button.left)
        for index,t in enumerate((0,.2,.4,.6,.8,1.01)):
            self.move_at(t,(index,1))
        self.assertFalse(mouse.held)
        raw.release.assert_called_once_with(Button.left)

    def test_qualifying_motion_cancels_the_existing_operation(self):
        clock=[0.0]
        with patch.object(C.time,'monotonic',side_effect=lambda:clock[0]),execution.operation('run_script'):
            for index,t in enumerate((0,.2,.4,.6,.8)):
                clock[0]=t;C.note_mouse_move(index,1)
            execution.check('run_script')
            clock[0]=1.01;C.note_mouse_move(6,1)
            with self.assertRaises(permission.PermissionDenied):execution.check('run_script')

    def test_listener_uses_delay_only_for_physical_motion(self):
        with patch.object(C,'_started',False),patch.object(C,'_watchers',{'mouse':None,'keyboard':None}),patch('pynput.mouse.Listener') as mouse,patch('pynput.keyboard.Listener') as keyboard:
            mouse.return_value.is_alive.return_value=True
            keyboard.return_value.is_alive.return_value=True
            self.assertTrue(C._ensure_watcher_locked())
            callbacks=mouse.call_args.kwargs
            self.assertFalse(callbacks['win32_event_filter'](0,SimpleNamespace(flags=1)))
            self.assertTrue(callbacks['win32_event_filter'](0,SimpleNamespace(flags=0)))
            with patch.object(C.time,'monotonic',return_value=0):callbacks['on_move'](10,10)
            self.assertEqual(C.STATE['owner'],'ai')
            callbacks['on_click'](10,10,Button.left,True)
            self.assertEqual(C.STATE['owner'],'user')
