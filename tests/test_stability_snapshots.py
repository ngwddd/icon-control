import unittest
from unittest.mock import patch,Mock
from computer_mcp import snapshots as S, ui_ext as U, execution as E

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        target=patch('computer_mcp.capabilities.check_target',return_value=None)
        target.start();self.addCleanup(target.stop)
        S._snapshots.clear()
        self.identity=(11,21,123.0,'Fixture',(0,0,300,200),144)
        self.window=patch.object(S,'window_identity',return_value=self.identity);self.ident=self.window.start()
        self.pixels=patch.object(S,'screen_fingerprint',return_value='same');self.digest=self.pixels.start()
        self.node=dict(x=10,y=10,w=40,h=20,name='Button',element_id='unique')

    def tearDown(self):self.pixels.stop();self.window.stop();S._snapshots.clear()

    def ref(self):return S.attach(11,[self.node])['candidates'][0]['ref']

    def test_fresh_reference_resolves(self):
        self.assertEqual(S.resolve(self.ref(),11)['name'],'Button')

    def test_wrong_window_is_rejected(self):
        ref=self.ref()
        with self.assertRaises(S.StaleReference):S.resolve(ref,12)

    def test_expired_reference_is_rejected(self):
        ref=self.ref()
        for item in S._snapshots.values():item['created']-=6
        with self.assertRaises(S.StaleReference):S.resolve(ref)

    def test_content_change_is_rejected(self):
        ref=self.ref();self.digest.return_value='changed'
        with self.assertRaises(S.StaleReference):S.resolve(ref)

    def test_handle_reuse_is_rejected(self):
        ref=self.ref();self.ident.return_value=(11,22,124.0,*self.identity[3:])
        with self.assertRaises(S.StaleReference):S.resolve(ref)

    def test_dpi_change_is_rejected(self):
        ref=self.ref();self.ident.return_value=(*self.identity[:-1],192)
        with self.assertRaises(S.StaleReference):S.resolve(ref)

    def test_moved_window_is_rejected(self):
        ref=self.ref();self.ident.return_value=(*self.identity[:4],(20,20,320,220),144)
        with self.assertRaises(S.StaleReference):S.resolve(ref)

    def test_negative_index_is_rejected(self):
        ref=self.ref().split(':')[0]+':-1'
        with self.assertRaises(S.StaleReference):S.resolve(ref)

    def test_invalid_ref_is_rejected(self):
        with self.assertRaises(S.StaleReference):S.resolve('not-an-element')

    def test_nodes_are_not_mutable_through_results(self):
        result=S.attach(11,[self.node]);ref=result['candidates'][0]['ref']
        result['candidates'][0]['x']=2000
        self.assertEqual(S.resolve(ref)['x'],10)

    def test_store_is_bounded(self):
        for _ in range(70):S.attach(11,[self.node])
        self.assertEqual(len(S._snapshots),S.MAX_SNAPSHOTS)

    def test_stale_click_produces_no_input(self):
        ref=self.ref();self.digest.return_value='changed';mouse=Mock()
        with patch.object(E,'check'),self.assertRaises(S.StaleReference):
            U.ui_click('',hwnd=11,mouse=mouse,ref=ref)
        mouse.click.assert_not_called()

    def test_obscured_click_produces_no_input(self):
        ref=self.ref();mouse=Mock()
        with patch.object(E,'check'),patch('computer_mcp.winutil.point_owner',return_value=12):
            result=U.ui_click('',hwnd=11,mouse=mouse,ref=ref)
        self.assertFalse(result['ok']);mouse.click.assert_not_called()

    def test_negative_legacy_index_is_rejected(self):
        target,result=U._resolve(11,'Button',False,-1)
        self.assertIsNone(target);self.assertIn('error',result)

if __name__=='__main__':unittest.main()
