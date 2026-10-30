import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import numpy as np
from pose_teaching import export_poses
from sensors import NeroFeedback


class TeachingTest(unittest.TestCase):
    def test_missing_old_samples_are_not_fabricated(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / "manifest.json").write_text(json.dumps(dict(camera={}, board={})))
            sample = dict(T_base_flange=np.eye(4).tolist(), time_unix_s=1)
            (p / "sample_0000.json").write_text(json.dumps(sample))
            sample["joints_rad"] = [0.1] * 7
            (p / "sample_0001.json").write_text(json.dumps(sample))
            r = export_poses(p)
            self.assertEqual(r["missing_joint_samples"], ["sample_0000.json"])
            self.assertEqual(len(r["poses"]), 1)
            self.assertFalse(r["execution_validated"])
            self.assertEqual(json.loads((p / "teaching_poses.json").read_text()), r)

    def test_requires_new_joint_feedback(self):
        reader = NeroFeedback.__new__(NeroFeedback)
        reader.device = Mock()
        reader.last_sample = 1
        def state(i, q):
            return {"arm_sample_id": i, "joints_rad": q, "source_time_s": float(i)}

        reader.device.state.side_effect = [state(1, [0] * 7), state(2, [0.1] * 7)]
        r = reader.read_joints()
        self.assertEqual(r["joints_rad"], [0.1] * 7)
        self.assertEqual(r["sdk_timestamp"], 2.0)
        reader.device.state.side_effect = None
        reader.device.state.return_value = state(2, [0] * 7)
        with patch("sensors.time.monotonic", side_effect=[0, 0.1, 2]), patch("sensors.time.sleep"):
            with self.assertRaisesRegex(ValueError, "No fresh"):
                reader.read_joints()


class ResumeRoiTest(unittest.TestCase):
    def test_only_detection_roi_may_change(self):
        from calibrate import same_board_for_resume

        old = dict(
            square_length_m=0.0215,
            image_profile={"color_resolution": [1280, 720]},
            image_roi_xyxy=[0, 0, 960, 440],
            max_reprojection_px=1,
        )
        new = dict(old, image_roi_xyxy=[0, 0, 960, 720])
        self.assertTrue(same_board_for_resume(old, new))
        for changed in (
            dict(new, square_length_m=0.022),
            dict(new, max_reprojection_px=2),
            dict(new, image_profile={"color_resolution": [640, 480]}),
        ):
            self.assertFalse(same_board_for_resume(old, changed))
