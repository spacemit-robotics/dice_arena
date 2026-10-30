import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from core import inverse, pose_matrix
from reference_board import DIRECTION, register, restore, summarize


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.bc = pose_matrix([0.12, -0.3, 0.65, 0.2, -0.1, 0.7])
        self.bb = pose_matrix([0.31, -0.12, 0.02, 0.0, 0.0, 0.3])
        self.camera = {"backend": "realsense", "serial": "test", "frame": "color_optical"}
        self.calibration = {
            "schema": 1,
            "mode": "eye_to_hand",
            "direction": DIRECTION,
            "quality_passed": False,
            "T_base_camera": self.bc.tolist(),
            "T_flange_tcp": np.eye(4).tolist(),
            "camera": self.camera,
            "all_sample_errors_m_deg": [[0.0123, 3.645]],
        }
        self.board = {
            "type": "charuco",
            "dictionary": "4x4_50",
            "squares_x": 4,
            "squares_y": 5,
            "square_length_m": 0.0215,
            "marker_length_m": 0.015,
            "legacy_pattern": False,
            "image_roi_xyxy": [10, 10, 300, 400],
        }

    def observation(self, bc):
        cb = inverse(bc) @ self.bb
        return {
            "schema": 1,
            "mode": "reference_observation",
            "reference_id": "table",
            "opencv_version": "same",
            "camera": copy.deepcopy(self.camera),
            "board": copy.deepcopy(self.board),
            "T_camera_board": cb.tolist(),
            "records": [
                {"T_camera_board": cb.tolist(), "quality": {"corners": 12, "reprojection_rms_px": 0.15}}
                for _ in range(10)
            ],
        }

    def test_known_transform_and_moved_camera_recovery(self):
        obs = self.observation(self.bc)
        original = copy.deepcopy(self.calibration)
        reg = register(self.calibration, obs, True)
        np.testing.assert_allclose(reg["T_base_board"], self.bb, atol=1e-10)
        moved = pose_matrix([-0.25, 0.14, 0.72, -0.3, 0.5, -0.6])
        obs2 = self.observation(moved)
        obs2["board"]["image_roi_xyxy"] = [200, 100, 600, 470]
        result = restore(reg, obs2, True)
        np.testing.assert_allclose(result["T_base_camera"], moved, atol=1e-10)
        self.assertFalse(result["quality_passed"])
        self.assertFalse(result["independent_accuracy_verified"])
        self.assertEqual(result["all_sample_errors_m_deg"], original["all_sample_errors_m_deg"])
        self.assertEqual(self.calibration, original)
        np.testing.assert_allclose(restore(reg, obs, True)["T_base_camera"], self.bc, atol=1e-10)

    def test_failed_calibration_requires_opt_in_at_both_steps(self):
        obs = self.observation(self.bc)
        with self.assertRaisesRegex(ValueError, "allow-provisional"):
            register(self.calibration, obs)
        reg = register(self.calibration, obs, True)
        with self.assertRaisesRegex(ValueError, "allow-provisional"):
            restore(reg, obs)
        reg["quality_passed"] = True
        self.assertFalse(restore(reg, obs, True)["quality_passed"])

    def test_passed_calibration_retains_default_without_opt_in(self):
        self.calibration["quality_passed"] = True
        obs = self.observation(self.bc)
        self.assertTrue(restore(register(self.calibration, obs), obs)["quality_passed"])

    def test_fps_change_preserves_registration_but_intrinsic_change_does_not(self):
        self.calibration["camera"]["fps"] = 15
        self.calibration["camera"]["camera_matrix"] = [[900, 0, 420], [0, 900, 360], [0, 0, 1]]
        obs = self.observation(self.bc)
        obs["camera"] = copy.deepcopy(self.calibration["camera"])
        obs["camera"]["fps"] = 6
        reg = register(self.calibration, obs, True)
        moved = self.observation(self.bc)
        moved["camera"] = copy.deepcopy(obs["camera"])
        moved["camera"]["fps"] = 15
        self.assertEqual(restore(reg, moved, True)["camera"]["fps"], 15)
        moved["camera"]["camera_matrix"][0][0] = 901
        with self.assertRaisesRegex(ValueError, "intrinsics"):
            restore(reg, moved, True)

    def test_reject_mismatched_camera_board_or_version(self):
        obs = self.observation(self.bc)
        reg = register(self.calibration, obs, True)
        changes = [
            ("camera", "serial", "other"),
            ("board", "square_length_m", 0.022),
            (None, "reference_id", "other"),
            (None, "opencv_version", "different"),
        ]
        for group, key, value in changes:
            with self.subTest(key=key):
                changed = copy.deepcopy(obs)
                (changed[group] if group else changed)[key] = value
                with self.assertRaises(ValueError):
                    restore(reg, changed, True)
        changed = copy.deepcopy(obs)
        changed["camera"]["serial"] = "other"
        with self.assertRaises(ValueError):
            register(self.calibration, changed, True)

    def test_reject_incomplete_noisy_or_unstable_observations(self):
        records = self.observation(self.bc)["records"]
        with self.assertRaises(ValueError):
            summarize(records[:9])
        for key, value in [("corners", 11), ("reprojection_rms_px", float("nan")), ("reprojection_rms_px", 0.6)]:
            changed = copy.deepcopy(records)
            changed[0]["quality"][key] = value
            with self.assertRaises(ValueError):
                summarize(changed)
        changed = copy.deepcopy(records)
        changed[0]["T_camera_board"][0][3] += 0.01
        with self.assertRaisesRegex(ValueError, "unstable"):
            summarize(changed)

    def observe_with(self, misses, frames=10):
        """observe() on a fake camera whose detector misses the board on the given frame indices."""
        from reference_board import observe

        cb = inverse(self.bc) @ self.bb
        calls = []

        class Camera:
            K, D, info = np.eye(3), np.zeros(5), {"serial": "test"}

            def __init__(self, *args, **kwargs):
                pass

            def capture(self):
                return np.zeros((8, 8, 3), np.uint8)

            def close(self):
                pass

        class Detector:
            def __init__(self, cfg):
                pass

            def detect(self, image, K, D):
                calls.append(len(calls))
                if calls[-1] in misses:
                    raise ValueError("Too few ChArUco corners: 角点不足（10/12）")
                return cb, {"corners": 12, "reprojection_rms_px": 0.15}, image

        with tempfile.TemporaryDirectory() as tmp:
            board = Path(tmp) / "board.json"
            board.write_text(json.dumps(self.board))
            with patch("sensors.RealSenseCamera", Camera), patch("sensors.CharucoDetector", Detector):
                return observe(board, "test", "table", Path(tmp) / "out", frames)

    def test_occasional_missed_frame_is_skipped_not_fatal(self):
        record = self.observe_with({2, 7})
        self.assertEqual(len(record["records"]), 10)
        self.assertEqual([r["frame_index"] for r in record["quality"]["rejected_frames"]], [2, 7])
        self.assertNotIn(2, [r["frame_index"] for r in record["records"]])
        with self.assertRaisesRegex(ValueError, "未能完整识别固定板"):
            self.observe_with(set(range(0, 40, 2)))  # Every other frame missed: not a stable view.

    def test_reject_forged_mean(self):
        obs = self.observation(self.bc)
        obs["T_camera_board"][0][3] += 0.01
        with self.assertRaisesRegex(ValueError, "mean disagrees"):
            register(self.calibration, obs, True)


if __name__ == "__main__":
    unittest.main()
