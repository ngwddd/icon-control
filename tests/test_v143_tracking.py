"""v1.4.3 R2: template tracking must refuse an uncertain lock."""
import unittest
from unittest.mock import patch

import numpy as np

from computer_mcp import vision_state as VS


def canvas(width=400, height=300, seed=7):
    rng = np.random.default_rng(seed)
    return (rng.random((height, width)) * 255).astype(np.uint8)


def stamp(image, patch, x, y):
    image[y:y + patch.shape[0], x:x + patch.shape[1]] = patch
    return image


def patch_image(seed=3, size=(24, 32)):
    rng = np.random.default_rng(seed)
    return (rng.random(size) * 255).astype(np.uint8)


class TrackingTests(unittest.TestCase):
    def setUp(self):
        self.template = patch_image()
        self.base = canvas()
        stamp(self.base, self.template, 120, 90)
        self.load = patch.object(VS, "_load_template", return_value=(self.template, {}))
        self.load.start()
        self.addCleanup(patch.stopall)

    def run_match(self, image, **kwargs):
        # _gray must crop like the real one, otherwise region offsets are fiction.
        def fake_gray(region, hwnd=None):
            if not region:
                return image
            x, y = int(region["x"]), int(region["y"])
            return image[y:y + int(region["h"]), x:x + int(region["w"])]

        with patch.object(VS, "_gray", side_effect=fake_gray), \
                patch.object(VS, "_screen_rect",
                             return_value={"x": 0, "y": 0, "w": image.shape[1], "h": image.shape[0]}):
            return VS.match_template("fixture", **kwargs)

    def test_finds_the_target_and_reports_its_centre(self):
        result = self.run_match(self.base)
        self.assertTrue(result["found"])
        self.assertGreaterEqual(result["score"], 0.8)
        self.assertEqual(result["center"], [120 + 16, 90 + 12])

    def test_previous_limits_the_search_and_reports_movement(self):
        moved = canvas()
        stamp(moved, self.template, 150, 100)
        result = self.run_match(moved, previous=[136, 102], radius=120)
        self.assertTrue(result["found"])
        self.assertEqual(result["search_rect"][0], 16)
        self.assertEqual(result["center"], [150 + 16, 100 + 12])
        self.assertEqual(result["moved_by"], [30, 10])

    def test_target_outside_the_radius_is_not_claimed(self):
        moved = canvas()
        stamp(moved, self.template, 300, 250)
        result = self.run_match(moved, previous=[136, 102], radius=60)
        self.assertFalse(result["found"])
        self.assertEqual(result["reason"], "below_threshold")

    def test_missing_target_is_not_found(self):
        blank = canvas(seed=11)
        result = self.run_match(blank)
        self.assertFalse(result["found"])
        self.assertIn(result.get("reason"), {"below_threshold", "ambiguous"})

    def test_two_identical_targets_are_ambiguous(self):
        doubled = canvas()
        stamp(doubled, self.template, 60, 40)
        stamp(doubled, self.template, 260, 200)
        result = self.run_match(doubled)
        self.assertFalse(result["found"], "two identical matches must not be a lock")
        self.assertEqual(result["reason"], "ambiguous")
        self.assertGreaterEqual(result["peaks"], 2)
        self.assertLess(result["score"] - result["second_score"], 0.05)

    def test_search_region_is_reported_and_clipped(self):
        result = self.run_match(self.base, search_region={"x": 100, "y": 80, "w": 120, "h": 90})
        self.assertTrue(result["found"])
        self.assertEqual(result["search_rect"], [100, 80, 120, 90])
        self.assertEqual(result["center"], [136, 102])

    def test_tracking_box_outside_the_window_is_refused(self):
        result = self.run_match(self.base, previous=(5000, 5000), radius=50)
        self.assertFalse(result["success"])
        self.assertIn("没有交集", result["error"])

    def test_region_smaller_than_the_template_is_an_error(self):
        result = self.run_match(self.base, search_region={"x": 0, "y": 0, "w": 5, "h": 5})
        self.assertFalse(result["success"])
        self.assertIn("比模板还小", result["error"])


class WaitTemplateCompatibilityTests(unittest.TestCase):
    def test_wait_template_still_works_through_the_new_signature(self):
        template = patch_image()
        image = stamp(canvas(), template, 30, 30)
        with patch.object(VS, "_load_template", return_value=(template, {})), \
                patch.object(VS, "_gray", return_value=image), \
                patch.object(VS, "_screen_rect",
                             return_value={"x": 0, "y": 0, "w": 400, "h": 300}), \
                patch.object(VS, "_execution"):
            result = VS.wait_template("fixture", timeout_ms=200)
        self.assertTrue(result["success"])
        self.assertTrue(result["matched"])


if __name__ == "__main__":
    unittest.main()
