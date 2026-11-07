"""v1.4.1 find_element: fuse sources instead of returning the first hit."""
import unittest
from unittest.mock import patch

from computer_mcp.zones import sense_fallback as SF


def cand(source, score, x, y, w=40, h=20, label='Button'):
    return dict(x=x, y=y, w=w, h=h, cx=x + w // 2, cy=y + h // 2,
                source=source, label=label, score=score)


class FusionTests(unittest.TestCase):
    def test_single_confident_uia_hit_does_not_pay_for_ocr(self):
        with patch.object(SF, '_try_uia', return_value=[cand('uia', 0.95, 10, 10)]), \
                patch.object(SF, '_try_ocr') as ocr, \
                patch.object(SF, '_try_template') as template:
            result = SF.find_element('OK')
        ocr.assert_not_called()
        template.assert_not_called()
        self.assertTrue(result['ok'])
        self.assertFalse(result['ambiguous'])
        self.assertEqual(result['candidates'][0]['source'], 'uia')

    def test_missing_uia_falls_through_to_ocr(self):
        with patch.object(SF, '_try_uia', return_value=[]), \
                patch.object(SF, '_try_ocr', return_value=[cand('ocr', 0.82, 100, 200, label='发送')]), \
                patch.object(SF, '_try_template', return_value=[]):
            result = SF.find_element('发送')
        self.assertEqual(result['source'], 'ocr')
        self.assertEqual(result['candidates'][0]['label'], '发送')

    def test_two_close_candidates_mark_the_result_ambiguous(self):
        with patch.object(SF, '_try_uia', return_value=[cand('uia', 0.85, 10, 10),
                                                        cand('uia', 0.80, 300, 10)]), \
                patch.object(SF, '_try_ocr', return_value=[]), \
                patch.object(SF, '_try_template', return_value=[]):
            result = SF.find_element('确定')
        self.assertTrue(result['ambiguous'])
        self.assertEqual(len(result['candidates']), 2)

    def test_two_sources_both_match_and_the_better_score_wins(self):
        with patch.object(SF, '_try_uia', return_value=[cand('uia', 0.70, 10, 10)]), \
                patch.object(SF, '_try_ocr', return_value=[cand('ocr', 0.91, 200, 300)]), \
                patch.object(SF, '_try_template', return_value=[]):
            result = SF.find_element('确定')
        self.assertEqual(result['source'], 'ocr')
        self.assertEqual(result['confidence'], 0.91)
        self.assertFalse(result['ambiguous'])

    def test_min_confidence_filters_weak_matches(self):
        with patch.object(SF, '_try_uia', return_value=[cand('uia', 0.50, 10, 10)]), \
                patch.object(SF, '_try_ocr', return_value=[]), \
                patch.object(SF, '_try_template', return_value=[]):
            result = SF.find_element('确定', min_confidence=0.8)
        self.assertFalse(result['ok'])
        self.assertEqual(result['candidates'], [])

    def test_uia_name_match_is_calibrated(self):
        exact = SF._uia_confidence('OK', 'OK')
        prefix = SF._uia_confidence('OK', 'OK Cancel')
        contains = SF._uia_confidence('Cancel', 'OK Cancel')
        self.assertGreater(exact, prefix)
        self.assertGreater(prefix, contains)
        self.assertLess(SF._uia_confidence('OK', 'Cancel'), 0.7)

    def test_sources_can_be_restricted(self):
        with patch.object(SF, '_try_uia', return_value=[]), \
                patch.object(SF, '_try_ocr') as ocr:
            result = SF.find_element('x', sources=('uia',))
        ocr.assert_not_called()
        self.assertFalse(result['ok'])


if __name__ == '__main__':
    unittest.main()
