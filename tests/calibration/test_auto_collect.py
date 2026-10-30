"""Offline checks for automatic hand-eye teaching and replay."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from auto_collect import (
    AutoCollectionView,
    board_corners,
    capture_after_settling,
    check_path,
    clamp_recorded_route,
    compress_recorded_route,
    inputs,
    inside_window,
    interpolate,
    ensure_can_control,
    make_plan,
    outline,
    run_plan,
    main,
    move_and_watch,
    stream_smooth_route,
    taught_route,
    validate_window,
)


class FakeJoint:
    lower_rad = -2.0
    upper_rad = 2.0


class FakeModel:
    joints = [FakeJoint()] * 7

    def fk(self, q):
        t = np.eye(4)
        t[0, 3] = q[0]
        return t


class AutoCollectionTests(unittest.TestCase):
    def setUp(self):
        self.camera = {
            "serial": "mock-camera",
            "width": 640,
            "height": 480,
            "camera_matrix": [[1000, 0, 320], [0, 1000, 240], [0, 0, 1]],
            "dist_coeffs": [0] * 5,
        }
        self.board = {"squares_x": 4, "squares_y": 5, "square_length_m": 0.02}
        self.manifest = {"camera": self.camera, "board": self.board, "T_flange_tcp": np.eye(4).tolist()}
        self.calibration = {"T_base_camera": np.eye(4).tolist(), "T_tcp_board": self.pose(0.5).tolist()}

    @staticmethod
    def pose(z):
        t = np.eye(4)
        t[2, 3] = z
        return t

    def test_outer_board_projection_and_window(self):
        points = outline(self.pose(0.5), self.camera, board_corners(self.board, {}))
        np.testing.assert_allclose(points[0], [320, 240], atol=1e-6)
        np.testing.assert_allclose(points[2], [480, 440], atol=1e-6)
        self.assertTrue(inside_window(points, [300, 220, 500, 460], 8))
        self.assertFalse(inside_window(points, [300, 220, 470, 460], 8))

    def test_optional_auto_collection_view_shows_sample_result(self):
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        with (
            patch("auto_collect.os.environ", {"DISPLAY": ":1"}),
            patch("auto_collect.cv2.namedWindow"),
            patch("auto_collect.cv2.resizeWindow"),
            patch("auto_collect.cv2.imshow") as imshow,
            patch("auto_collect.cv2.waitKey"),
            patch("auto_collect.cv2.destroyWindow"),
        ):
            view = AutoCollectionView([10, 10, 630, 470], 20)
            view.update(
                frame,
                "ACCEPTED",
                1,
                {"corners": 12, "reprojection_rms_px": 0.12},
                np.array([[100, 100], [200, 100], [200, 200], [100, 200]]),
            )
            view.status("MOVING", 1)
            view.pump()
            view.close()
            self.assertEqual(imshow.call_count, 2)

    def test_joint_path_checks_interpolated_board_visibility(self):
        start = [0.0] * 7
        target = [0.04] + [0.0] * 6
        path = check_path(start, [target], FakeModel(), self.manifest, self.calibration, [300, 220, 600, 470], 1.0, 5.0)
        self.assertGreater(len(path), 2)
        self.assertEqual(path[-1]["capture_sample_index"], 0)
        with self.assertRaisesRegex(ValueError, "Board leaves drawn window"):
            check_path(
                start,
                [[0.08] + [0.0] * 6],
                FakeModel(),
                self.manifest,
                self.calibration,
                [300, 220, 600, 470],
                1.0,
                5.0,
            )
        self.assertEqual(len(interpolate(start, target, 1.0)), 3)

    def test_route_is_one_continuous_motion_after_the_window_is_serviced(self):
        route = [[0.0] * 7, [np.deg2rad(5.0)] + [0.0] * 6, [np.deg2rad(10.0)] + [0.0] * 6]
        order = []
        arm = Mock()
        arm.move_path.side_effect = lambda *args: order.append(("path",) + args)
        stream_smooth_route(arm, route, 20.0, 15.0, pump=lambda: order.append("pump"))
        self.assertEqual(order, ["pump", ("path", route[1:], 20.0, 15.0)])
        arm.move.assert_not_called()
        for invalid in ((route[:1], 20.0, 20.0), (route, 0.0, 20.0), (route, 20.0, float("nan"))):
            with self.assertRaisesRegex(ValueError, "Invalid"):
                stream_smooth_route(arm, *invalid)

    def test_failed_route_is_reported(self):
        arm = Mock()
        arm.move_path.side_effect = RuntimeError("机械臂运动未完成：fault path stream stopped")
        with self.assertRaisesRegex(RuntimeError, "path stream stopped"):
            stream_smooth_route(arm, [[0.0] * 7, [0.1] * 7, [0.2] * 7], 20.0, 20.0)
        arm.move_path.assert_called_once()

    def test_board_window_is_checked_after_the_move_settles(self):
        arm, order = Mock(), []
        arm.state.return_value = {"enabled": True, "fault": False, "moving": False, "position_mode": True}
        arm.speed_deg_s, arm.acc_deg_s2 = 20.0, 15.0
        arm.move_path.side_effect = lambda path, v, a: order.append(("move", path, v, a)) and None
        with patch("auto_collect.live_board", side_effect=lambda *a: order.append("board")):
            move_and_watch(arm, None, None, None, None, None, 0, [0.0] * 7)
            move_and_watch(arm, None, None, None, None, None, 0, [0.0] * 7, watch_board=False)
        self.assertEqual(order, [("move", [[0.0] * 7], 20.0, 15.0), "board", ("move", [[0.0] * 7], 20.0, 15.0)])
        arm.move.assert_not_called()  # Settling never switches to the point (j) mode.

    def test_requested_fast_calibration_settings_are_accepted(self):
        command = [
            "run",
            "--plan",
            "plan.json",
            "--output",
            "automatic",
            "--speed-percent",
            "40",
            "--smooth-speed-deg-s",
            "20",
            "--smooth-acc-deg-s2",
            "20",
            "--show",
        ]
        with patch("auto_collect.run_plan") as run:
            self.assertEqual(main(command), 0)
            run.assert_called_once_with(
                Path("plan.json"),
                Path("automatic"),
                "can0",
                40,
                None,
                20.0,
                20.0,
                True,
                start_home=True,
                home_path=None,
            )
        with self.assertRaisesRegex(ValueError, "1..100%"):
            main(command[:6] + ["101"] + command[7:])

    def test_trace_records_path_and_rejects_lost_board(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            samples = [
                {
                    "time_unix_s": float(i + 1),
                    "joints_rad": [i * 0.01] + [0.0] * 6,
                    "T_camera_board": self.pose(0.5).tolist(),
                    "frame_joint_observations": [{}] * 3,
                }
                for i in range(2)
            ]
            frame = {
                "time_unix_s": 1.5,
                "joints": {"joints_rad": [0.005] + [0.0] * 6},
                "T_camera_board": self.pose(0.5).tolist(),
                "image_width": 640,
                "image_height": 480,
            }
            trace = dataset / "teaching_frames.jsonl"
            trace.write_text(json.dumps(frame) + "\n")
            route, capture, used = taught_route(
                dataset, samples, self.manifest, self.calibration, [300, 220, 500, 460], 5.0
            )
            self.assertEqual(capture, [0, None, 1])
            self.assertEqual(route[1][0], 0.005)
            self.assertEqual(used, trace)
            frame["T_camera_board"] = None
            trace.write_text(json.dumps(frame) + "\n")
            with self.assertRaisesRegex(ValueError, "not detected"):
                taught_route(dataset, samples, self.manifest, self.calibration, [300, 220, 500, 460], 5.0)
            frame["T_camera_board"] = self.pose(0.5).tolist()
            frame["time_unix_s"] = 1.1
            trace.write_text(json.dumps(frame) + "\n")
            samples[1]["time_unix_s"] = 5.0
            with self.assertRaisesRegex(ValueError, "Unrecorded arm movement"):
                taught_route(dataset, samples, self.manifest, self.calibration, [300, 220, 500, 460], 5.0)

    def test_capture_only_route_keeps_samples_without_transition_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp)
            samples = [
                {
                    "time_unix_s": float(i + 1),
                    "joints_rad": [i * 0.01] + [0.0] * 6,
                    "T_camera_board": self.pose(0.5).tolist(),
                    "frame_joint_observations": [{}] * 3,
                }
                for i in range(2)
            ]
            frame = {
                "time_unix_s": 1.5,
                "joints": {"joints_rad": [0.005] + [0.0] * 6},
                "T_camera_board": None,
                "image_width": 640,
                "image_height": 480,
            }
            (dataset / "teaching_frames.jsonl").write_text(json.dumps(frame) + "\n")
            route, capture, _ = taught_route(
                dataset,
                samples,
                self.manifest,
                self.calibration,
                [300, 220, 500, 460],
                5.0,
                capture_only_visibility=True,
            )
            self.assertEqual(capture, [0, None, 1])
            route, capture = compress_recorded_route(route, capture)
            self.assertEqual(capture, [0, 1])
            self.assertEqual(route[-1][0], 0.01)
            samples[1]["T_camera_board"] = self.pose(0.1).tolist()
            with self.assertRaisesRegex(ValueError, "sample 1"):
                taught_route(
                    dataset,
                    samples,
                    self.manifest,
                    self.calibration,
                    [300, 220, 500, 460],
                    5.0,
                    capture_only_visibility=True,
                )

    def test_recorded_limit_overshoot_is_bounded_and_reported(self):
        route, correction = clamp_recorded_route([[2.001] + [0.0] * 6], FakeModel())
        self.assertLess(route[0][0], 2.0)
        self.assertGreater(correction, 0.05)
        with self.assertRaisesRegex(ValueError, "exceeds SDK joint limit"):
            clamp_recorded_route([[2.02] + [0.0] * 6], FakeModel())

    def test_replay_requires_can_position_mode_and_never_switches_it(self):
        arm = Mock()
        arm.state.return_value = {"enabled": True, "fault": False, "moving": False, "position_mode": True}
        ensure_can_control(arm)
        for change, message in (
            ({"position_mode": False}, "CAN"),
            ({"moving": True}, "moving"),
            ({"enabled": False}, "enabled"),
            ({"fault": True}, "enabled"),
        ):
            arm.state.return_value = {"enabled": True, "fault": False, "moving": False, "position_mode": True, **change}
            with self.assertRaisesRegex(RuntimeError, message):
                ensure_can_control(arm)
        arm.move.assert_not_called()

    def test_capture_retries_only_when_arm_is_still_settling(self):
        accepted = ("sample", "image", "preview")
        with patch(
            "auto_collect.capture_sample",
            side_effect=[ValueError("Arm moved during capture; sample rejected"), accepted],
        ) as capture:
            self.assertEqual(capture_after_settling(Mock(), Mock(), Mock(), None), accepted)
            self.assertEqual(capture.call_count, 2)
        with patch("auto_collect.capture_sample", side_effect=ValueError("Board missing")) as capture:
            with self.assertRaisesRegex(ValueError, "Board missing"):
                capture_after_settling(Mock(), Mock(), Mock(), None)
            capture.assert_called_once()

    def test_window_must_match_camera_and_board(self):
        data = {"camera": self.camera, "board": self.board, "window_xyxy": [0, 0, 640, 480]}
        self.assertEqual(validate_window(data, self.manifest), data["window_xyxy"])
        with self.assertRaisesRegex(ValueError, "window"):
            validate_window({**data, "window_xyxy": [0, 0, 641, 480]}, self.manifest)

    def make_taught_session(self, root):
        source = root / "taught"
        source.mkdir()
        manifest = {**self.manifest, "schema": 1, "mode": "eye_to_hand"}
        (source / "manifest.json").write_text(json.dumps(manifest))
        calibration = {
            **self.calibration,
            "camera": self.camera,
            "T_flange_tcp": np.eye(4).tolist(),
            "quality_passed": True,
        }
        calibration_path = root / "calibration.json"
        calibration_path.write_text(json.dumps(calibration))
        (source / "board_window.json").write_text(
            json.dumps({"window_xyxy": [300, 220, 640, 470], "camera": self.camera, "board": self.board})
        )
        frames = []
        for i in range(8):
            sample = {
                "T_base_flange": np.eye(4).tolist(),
                "T_base_tcp": np.eye(4).tolist(),
                "T_camera_board": self.pose(0.5).tolist(),
                "time_unix_s": float(i + 1),
                "joints_rad": [i * 0.01] + [0.0] * 6,
                "frame_joint_observations": [{}] * 3,
            }
            (source / f"sample_{i:04d}.json").write_text(json.dumps(sample))
            if i:
                frames.append(
                    {
                        "time_unix_s": i + 0.5,
                        "joints": {"joints_rad": [(i - 0.5) * 0.01] + [0.0] * 6},
                        "T_camera_board": self.pose(0.5).tolist(),
                        "image_width": 640,
                        "image_height": 480,
                    }
                )
        (source / "teaching_frames.jsonl").write_text("".join(json.dumps(row) + "\n" for row in frames))
        return source, calibration_path

    def test_plan_then_mock_run_writes_all_samples_without_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, calibration = self.make_taught_session(root)
            source_manifest_path = source / "manifest.json"
            source_manifest = json.loads(source_manifest_path.read_text())
            source_manifest["opencv_version"] = "teaching-runtime-version"
            source_manifest_path.write_text(json.dumps(source_manifest))
            source_manifest_bytes = source_manifest_path.read_bytes()
            plan_path, output = root / "plan.json", root / "automatic"
            with patch("auto_collect.load_model", return_value=FakeModel()):
                plan = make_plan(source, calibration, plan_path, margin_px=5.0)
            self.assertEqual(plan["path_source"], "per_frame_teaching_trace")
            self.assertEqual(sum(w["capture_sample_index"] is not None for w in plan["waypoints"]), 8)
            camera, arm, detector = Mock(), Mock(), Mock()
            camera.info = self.camera
            arm.read_joints.return_value = {"joints_rad": [0.0] * 7}
            frame = np.zeros((10, 10, 3), dtype=np.uint8)
            sample = {
                "T_base_flange": np.eye(4).tolist(),
                "T_camera_board": self.pose(0.5).tolist(),
                "quality": {"corners": 12, "reprojection_rms_px": 0.1},
            }
            with (
                patch("auto_collect.RealSenseCamera", return_value=camera),
                patch("auto_collect.NeroFeedback", return_value=arm),
                patch("auto_collect.CharucoDetector", return_value=detector),
                patch("auto_collect.load_model", return_value=FakeModel()),
                patch("auto_collect.ensure_can_control"),
                patch("auto_collect.live_board"),
                patch("auto_collect.move_and_watch") as move,
                patch("auto_collect.capture_sample", return_value=(sample, frame, frame)),
            ):
                self.assertEqual(run_plan(plan_path, output, "can0", 10), 8)
            self.assertGreater(move.call_count, 8)
            self.assertEqual(len(list(output.glob("sample_*.json"))), 8)
            self.assertFalse((output / "AUTO_INCOMPLETE.json").exists())
            collected_manifest = json.loads((output / "manifest.json").read_text())
            self.assertEqual(collected_manifest["opencv_version"], cv2.__version__)
            self.assertEqual(collected_manifest["source_opencv_version"], "teaching-runtime-version")
            self.assertEqual(source_manifest_path.read_bytes(), source_manifest_bytes)
            arm.close.assert_called_once()
            camera.close.assert_called_once()
            (source / "teaching_frames.jsonl").write_text("changed\n")
            with self.assertRaisesRegex(ValueError, "changed after planning"):
                run_plan(plan_path, root / "another", "can0", 10)

    def test_capture_only_plan_retraces_from_last_pose_and_samples_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, calibration = self.make_taught_session(root)
            solved = json.loads(calibration.read_text())
            solved["quality_passed"] = False
            calibration.write_text(json.dumps(solved))
            trace_path = source / "teaching_frames.jsonl"
            rows = [json.loads(line) for line in trace_path.read_text().splitlines()]
            rows[0]["T_camera_board"] = None
            trace_path.write_text("".join(json.dumps(row) + "\n" for row in rows))
            plan_path, output = root / "plan.json", root / "automatic"
            with patch("auto_collect.load_model", return_value=FakeModel()):
                plan = make_plan(
                    source, calibration, plan_path, margin_px=5.0, allow_provisional=True, capture_only_visibility=True
                )
            self.assertEqual(plan["visibility_policy"], "capture_only")
            self.assertEqual(sum(w["capture_sample_index"] is not None for w in plan["waypoints"]), 8)
            camera, arm, detector = Mock(), Mock(), Mock()
            camera.info = self.camera
            arm.read_joints.return_value = {"joints_rad": [0.07] + [0.0] * 6}
            frame = np.zeros((10, 10, 3), dtype=np.uint8)
            sample = {
                "T_base_flange": np.eye(4).tolist(),
                "T_camera_board": self.pose(0.5).tolist(),
                "quality": {"corners": 12, "reprojection_rms_px": 0.1},
            }
            with (
                patch("auto_collect.RealSenseCamera", return_value=camera),
                patch("auto_collect.NeroFeedback", return_value=arm),
                patch("auto_collect.CharucoDetector", return_value=detector),
                patch("auto_collect.load_model", return_value=FakeModel()),
                patch("auto_collect.ensure_can_control"),
                patch("auto_collect.live_board"),
                patch("auto_collect.move_and_watch") as move,
                patch("auto_collect.stream_smooth_route") as stream,
                patch("auto_collect.AutoCollectionView") as view_factory,
                patch("auto_collect.capture_sample", return_value=(sample, frame, frame)),
            ):
                self.assertEqual(run_plan(plan_path, output, "can0", 10, show=True), 8)
            self.assertEqual(move.call_count, 8)
            self.assertEqual(stream.call_count, 8)
            self.assertEqual(view_factory.return_value.status.call_count, 8)
            self.assertEqual(view_factory.return_value.update.call_count, 9)
            view_factory.return_value.close.assert_called_once()
            self.assertTrue(all(call.kwargs["watch_board"] is False for call in move.call_args_list))
            self.assertEqual(len(list(output.glob("sample_*.json"))), 8)

    def test_home_start_precedes_capture_and_failure_aborts_sampling(self):
        for home_failed in (False, True):
            with self.subTest(home_failed=home_failed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source, calibration = self.make_taught_session(root)
                plan_path, output = root / "plan.json", root / "automatic"
                with patch("auto_collect.load_model", return_value=FakeModel()):
                    make_plan(source, calibration, plan_path, capture_only_visibility=True)
                home_path = root / "home.json"
                home_path.write_text(json.dumps({"joints_rad": [0.0] * 7}))
                camera, arm = Mock(), Mock()
                camera.info = self.camera
                # Starting far from every taught waypoint used to reject this run.
                arm.read_joints.return_value = {"joints_rad": [0.5] + [0.0] * 6}
                frame = np.zeros((10, 10, 3), dtype=np.uint8)
                sample = {
                    "T_base_flange": np.eye(4).tolist(),
                    "T_camera_board": self.pose(0.5).tolist(),
                    "quality": {"corners": 12, "reprojection_rms_px": 0.1},
                }
                events = []

                def home(*args):
                    events.append("HOME")
                    if home_failed:
                        raise RuntimeError("HOME failed")
                    arm.read_joints.return_value = {"joints_rad": [0.0] * 7}
                    return [0.0] * 7

                def capture(*args, **kwargs):
                    self.assertEqual(events[0], "HOME")
                    events.append("capture")
                    return sample, frame, frame

                with (
                    patch("auto_collect.RealSenseCamera", return_value=camera),
                    patch("auto_collect.NeroFeedback", return_value=arm),
                    patch("auto_collect.CharucoDetector"),
                    patch("auto_collect.load_model", return_value=FakeModel()),
                    patch("auto_collect.ensure_can_control"),
                    patch("auto_collect.live_board"),
                    patch("auto_collect.move_and_watch"),
                    patch("auto_collect.stream_smooth_route"),
                    patch("home_start.move_home", side_effect=home),
                    patch("auto_collect.capture_sample", side_effect=capture),
                ):
                    if home_failed:
                        with self.assertRaisesRegex(RuntimeError, "HOME failed"):
                            run_plan(plan_path, output, "can0", 10, start_home=True, home_path=home_path)
                        self.assertEqual(events, ["HOME"])
                        self.assertTrue((output / "AUTO_INCOMPLETE.json").exists())
                    else:
                        self.assertEqual(
                            run_plan(plan_path, output, "can0", 10, start_home=True, home_path=home_path), 8
                        )
                        self.assertTrue((output / "home_start.json").exists())
                arm.close.assert_called_once()
                camera.close.assert_called_once()

    def test_replay_fps_override_keeps_teaching_geometry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, calibration = self.make_taught_session(root)
            taught = json.loads((source / "manifest.json").read_text())
            taught["camera"]["fps"] = 15
            taught["board"]["image_profile"] = {"color_resolution": [640, 480], "fps": 15}
            (source / "manifest.json").write_text(json.dumps(taught))
            solved = json.loads(calibration.read_text())
            solved["camera"]["fps"] = 15
            calibration.write_text(json.dumps(solved))
            window = json.loads((source / "board_window.json").read_text())
            window["camera"]["fps"] = 15
            window["board"] = taught["board"]
            (source / "board_window.json").write_text(json.dumps(window))
            with patch("auto_collect.load_model", return_value=FakeModel()):
                make_plan(source, calibration, root / "plan.json", margin_px=5.0)
            camera = Mock()
            camera.info = dict(self.camera, fps=6)
            with (
                patch("auto_collect.RealSenseCamera", return_value=camera) as open_camera,
                patch("auto_collect.NeroFeedback", side_effect=RuntimeError("mock stop")),
            ):
                with self.assertRaisesRegex(RuntimeError, "mock stop"):
                    run_plan(root / "plan.json", root / "automatic", "can0", 10, fps=6)
            self.assertEqual(open_camera.call_args.kwargs["image_profile"]["fps"], 6)
            camera.close.assert_called_once()
            self.assertEqual(json.loads((source / "manifest.json").read_text())["camera"]["fps"], 15)

    def test_old_dataset_reports_all_missing_replay_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, calibration = self.make_taught_session(root)
            (source / "board_window.json").unlink()
            (source / "teaching_frames.jsonl").unlink()
            sample_path = source / "sample_0000.json"
            sample = json.loads(sample_path.read_text())
            del sample["frame_joint_observations"]
            sample_path.write_text(json.dumps(sample))
            with self.assertRaisesRegex(ValueError, "Teaching dataset cannot be replayed") as caught:
                inputs(source, calibration)
            self.assertIn("board_window.json", str(caught.exception))
            self.assertIn("teaching_frames.jsonl", str(caught.exception))
            self.assertIn("frame_joint_observations", str(caught.exception))

    def test_calibration_fps_may_differ_but_geometry_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source, calibration = self.make_taught_session(root)
            solved = json.loads(calibration.read_text())
            solved["camera"]["fps"] = 15
            calibration.write_text(json.dumps(solved))
            self.assertEqual(inputs(source, calibration)[3], [300, 220, 640, 470])
            solved["camera"]["camera_matrix"][0][0] += 1
            calibration.write_text(json.dumps(solved))
            with self.assertRaisesRegex(ValueError, "camera/intrinsics differ"):
                inputs(source, calibration)


if __name__ == "__main__":
    unittest.main()
