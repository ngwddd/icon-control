import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock
from PIL import Image
from computer_mcp import program as P, tasks as T, execution as E, train
from computer_mcp.permission import PermissionDenied

class TaskTests(unittest.TestCase):
    def setUp(self):
        self.guard=patch.object(E,'check');self.guard.start()
        self.action=patch.object(train,'do_action',return_value={'ok':True});self.do=self.action.start()
        self.expect=patch.object(train,'check_expect',return_value=True);self.condition=self.expect.start()

    def tearDown(self):
        self.expect.stop();self.action.stop();self.guard.stop()

    def run_task(self,steps,**kwargs):
        return P._run_with_wheel(steps,{},rect=(0,0,10,10),**kwargs)

    def test_then_branch_really_executes(self):
        result=self.run_task([{'op':'branch','if':{'kind':'text','query':'yes'},
                               'then':[{'op':'click','at':[.2,.2],'expect':{'kind':'changed'}}],
                               'else':[{'op':'wait'}]}])
        self.assertTrue(result['verified']);self.assertEqual(self.do.call_args.args[0]['kind'],'click')

    def test_false_branch_really_executes_else(self):
        self.condition.side_effect=[False,True]
        result=self.run_task([{'op':'branch','if':{'kind':'text'},
            'then':[{'op':'wait'}],'else':[{'op':'click','expect':{'kind':'changed'}}]}])
        self.assertTrue(result['ok']);self.assertEqual(self.do.call_count,1)

    def test_unknown_condition_does_not_choose_else(self):
        self.condition.return_value=None
        result=self.run_task([{'op':'branch','if':{'kind':'text'},'else':[{'op':'click'}]}])
        self.assertFalse(result['ok']);self.do.assert_not_called()

    def test_branch_failure_propagates(self):
        self.do.return_value={'ok':False,'detail':'blocked'}
        result=self.run_task([{'op':'branch','if':{'kind':'text'},'then':[{'op':'click'}]}])
        self.assertFalse(result['ok']);self.assertEqual(result['done'],0)

    def test_photo_creates_readable_artifact(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(T.security,'data_home',return_value=Path(folder)), \
             patch('computer_mcp.core.screenshot._grab',return_value=(Image.new('RGB',(10,10)),10,10)):
            result=self.run_task([{'op':'photo','name':'evidence'}])
            self.assertTrue(result['ok'])
            artifact=result['artifacts'][0]
            self.assertTrue(Path(artifact['path']).is_file());self.assertEqual(len(artifact['sha256']),64)

    def test_failed_photo_is_not_completed(self):
        with patch.object(T,'photo',side_effect=RuntimeError('capture failed')):
            result=self.run_task([{'op':'photo','name':'evidence'}])
        self.assertFalse(result['ok']);self.assertEqual(result['done'],0)

    def test_photo_rejects_path_traversal(self):
        with self.assertRaises(ValueError): T.photo('../escape',(0,0,10,10))

    def test_unknown_op_does_not_succeed(self):
        result=self.run_task([{'op':'not_implemented'}]);self.assertFalse(result['ok']);self.assertEqual(result['done'],0)

    def test_missing_focus_target_is_failure(self):
        with patch.object(train,'_find_window',return_value=None):
            result=self.run_task([{'op':'focus','title':'missing'}])
        self.assertFalse(result['ok']);self.assertEqual(result['done'],0)

    def test_failed_action_is_not_counted_with_continue(self):
        self.do.return_value={'ok':False}
        result=self.run_task([{'op':'click','on_fail':'continue'}],stop_on_fail=False)
        self.assertFalse(result['ok']);self.assertEqual(result['done'],0)

    def test_no_postcondition_is_unverified(self):
        result=self.run_task([{'op':'click'}])
        self.assertFalse(result['ok']);self.assertFalse(result['verified'])
        self.assertEqual(result['state'],'executed_unverified')

    def test_final_assert_verifies_sequence(self):
        result=self.run_task([{'op':'click'},{'op':'assert','expect':{'kind':'text','query':'changed'}}])
        self.assertTrue(result['ok']);self.assertTrue(result['steps'][0]['verified'])

    def test_failed_postcondition_does_not_count_action_done(self):
        self.condition.return_value=False
        result=self.run_task([{'op':'click','expect':{'kind':'text'},'timeout_ms':0}])
        self.assertFalse(result['ok']);self.assertEqual(result['done'],0)

    def test_cancelled_task_never_continues(self):
        self.do.side_effect=PermissionDenied('revoked')
        result=self.run_task([{'op':'click','on_fail':'continue'},{'op':'click'}],stop_on_fail=False)
        self.assertEqual(result['state'],'cancelled');self.assertEqual(self.do.call_count,1)

    def test_unresolved_reference_stops(self):
        result=self.run_task([{'op':'click','at':'@undefined'}]);self.assertFalse(result['ok']);self.do.assert_not_called()

    def test_branch_depth_is_bounded(self):
        instructions=[{'op':'photo'}]
        for _ in range(18):instructions=[{'op':'branch','if':{'kind':'text'},'then':instructions}]
        result=self.run_task(instructions);self.assertFalse(result['ok'])

    def test_batch_timeout_is_not_success(self):
        from computer_mcp import ui_ext
        with patch('computer_mcp.core.screenshot.wait_for_change',return_value={'changed':False}):
            result=ui_ext.run_batch([{'action':'wait_change'}],mouse=Mock(),keyboard=Mock(),default_sleep_ms=0)
        self.assertFalse(result['ok'])

if __name__=='__main__':unittest.main()
