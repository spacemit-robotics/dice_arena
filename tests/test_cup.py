# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""C++ business gates and actual C++ Mock execution through the Python bridge."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT.parents[2]
# The installed Mock configuration; tests replace its @...@ paths.
MOCK = ROOT / "config/mock.install.json.in"
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(SDK / "components/control/manipulation/bindings/python"))
from cup_shake.policy import CupPolicy  # noqa: E402 - source-tree test paths
from cup_shake import CupApplication  # noqa: E402 - source-tree test paths
from cup_shake.planners import make_planner  # noqa: E402 - source-tree test paths


class ApplicationLayoutTests(unittest.TestCase):
    def test_one_application_package_and_component_example(self):
        self.assertFalse((ROOT.parent / "cup_shake").exists())
        self.assertFalse((ROOT.parent / "manipulation_point_demo").exists())
        package = ET.parse(ROOT / "package.xml").getroot()
        self.assertEqual(package.findtext("name"), "dice_arena")
        self.assertEqual([item.text for item in package.findall("depend")], ["manipulation"])
        dependencies = [item.text for item in package.findall("system_depend")]
        self.assertEqual(len(dependencies), len(set(dependencies)))
        self.assertTrue(
            {
                "python3-numpy",
                "python3-opencv",
                "python3-scipy",
                "python3-spacemit-ort",
                "spacemit-onnxruntime",
            }
            <= set(dependencies)
        )
        self.assertTrue(
            (
                SDK / "components/control/manipulation/examples/point_sequence/point_sequence.yaml"
            ).is_file()
        )
        for resource in ("algorithms", "calibration", "game", "python/cup_shake"):
            self.assertTrue((ROOT / resource).is_dir(), resource)


class SiteConfigurationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dice site configuration ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.prefix = self.root / "install"
        self.source = self.root / "algorithms"
        self.destination = self.root / "cup_application.json"
        self.marker = self.prefix / "bin/validated"
        (self.prefix / "bin").mkdir(parents=True)
        (self.prefix / ".spacemit-manipulation.json").write_text(
            json.dumps(dict(bindir="bin", libdir="lib")), encoding="utf-8"
        )
        self.validator = self.prefix / "bin/manipulation-device"
        self.validator.write_text(
            "#!/usr/bin/env python3\nfrom pathlib import Path\n"
            "Path(__file__).with_name('validated').touch()\nprint('valid')\n",
            encoding="utf-8",
        )
        self.validator.chmod(0o755)
        package = self.source / "cup_grasp_demo/flow"
        package.mkdir(parents=True)
        (package.parent / "__init__.py").touch()
        (package / "__init__.py").touch()
        (package / "green_pipeline.py").write_text(
            "import json\nfrom pathlib import Path\n"
            "def load_config(path):\n    return json.loads(Path(path).read_text())\n"
            "def validate(config):\n    return config['green_cup']\n",
            encoding="utf-8",
        )
        (self.root / "green_cup.json").write_text(
            json.dumps(
                dict(green_cup=dict(open_targets_0_100=[0] * 6, grip_targets_0_100=[10] * 6))
            ),
            encoding="utf-8",
        )
        (self.root / "device.yaml").write_text("mock fixture\n", encoding="utf-8")

    def configure(self):
        return subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/configure_site.py"),
                str(self.prefix),
                str(self.root / "device.yaml"),
                str(self.source),
                str(self.root / "green_cup.json"),
                str(self.root / "runtime"),
                str(self.destination),
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        )

    def assert_existing_kept(self, result):
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("existing file kept", result.stderr)
        self.assertIn(str(self.destination), result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_new_configuration_keeps_relative_paths_and_no_hand_copy(self):
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(self.marker.is_file())
        config = json.loads(self.destination.read_text())
        self.assertEqual(config["schema_version"], 3)
        for key in ("executable", "device_plan", "policy_library", "state_file"):
            self.assertFalse(Path(config[key]).is_absolute())
        self.assertEqual(config["planner"]["config"], "green_cup.json")
        # Hand poses are read from green_cup.json when the application connects, never copied.
        for key in ("open_positions", "grip_positions", "duration_s", "gestures"):
            self.assertNotIn(key, config)

    def test_existing_configuration_preserved_before_loading_dependencies(self):
        original = b'{"grip_confirmation": "operator", "site_parameter": 42}\n'
        self.destination.write_bytes(original)
        self.destination.chmod(0o600)
        before = self.destination.stat()
        (self.prefix / ".spacemit-manipulation.json").unlink()
        self.assert_existing_kept(self.configure())
        self.assertEqual(self.destination.read_bytes(), original)
        self.assertEqual(self.destination.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertEqual(self.destination.stat().st_mode, before.st_mode)
        self.assertFalse(self.marker.exists())

    def test_existing_symlink_preserves_link_and_target(self):
        target = self.root / "operator.json"
        target.write_bytes(b"operator configuration\n")
        self.destination.symlink_to(target.name)
        self.assert_existing_kept(self.configure())
        self.assertEqual(os.readlink(self.destination), target.name)
        self.assertEqual(target.read_bytes(), b"operator configuration\n")
        self.assertFalse(self.marker.exists())

    def test_dangling_symlink_does_not_create_target(self):
        target = self.root / "missing.json"
        self.destination.symlink_to(target.name)
        self.assert_existing_kept(self.configure())
        self.assertEqual(os.readlink(self.destination), target.name)
        self.assertFalse(target.exists())
        self.assertFalse(self.marker.exists())

    def test_existing_directory_is_rejected_cleanly(self):
        self.destination.mkdir()
        self.assert_existing_kept(self.configure())
        self.assertTrue(self.destination.is_dir())
        self.assertFalse(self.marker.exists())

    def test_file_created_during_validation_is_not_overwritten(self):
        self.validator.write_text(
            "#!/usr/bin/env python3\nfrom pathlib import Path\n"
            f"Path({str(self.destination)!r}).write_text('created concurrently')\n",
            encoding="utf-8",
        )
        self.assert_existing_kept(self.configure())
        self.assertEqual(self.destination.read_text(), "created concurrently")


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.policy = CupPolicy(os.environ["CUP_TASK_LIBRARY"])
        self.addCleanup(self.policy.close)

    def complete(self, phase):
        self.policy.step(phase, 0)
        self.policy.step(phase, 1)

    def test_order_grip_gate_and_no_unsafe_home_open(self):
        with self.assertRaises(RuntimeError):
            self.complete("lift")
        for name in ("home", "approach", "grip"):
            self.complete(name)
        with self.assertRaises(RuntimeError):
            self.complete("lift")
        with self.assertRaises(RuntimeError):
            self.complete("home")
        self.policy.confirm_grip()
        self.complete("lift")
        with self.assertRaises(RuntimeError):
            self.complete("open")
        for name in ("shake", "lower", "open", "return_home"):
            self.complete(name)
        self.assertEqual(self.policy.state, "ready")

    def test_abandoned_phase_keeps_the_state(self):
        self.complete("home")
        self.policy.step("approach", 0)
        self.policy.abandon("approach")
        self.assertEqual((self.policy.state, self.policy.active), ("ready", ""))
        self.complete("approach")  # The same phase may begin again.
        with self.assertRaises(RuntimeError):
            self.policy.abandon("grip")  # Only the active phase can be abandoned.

    def test_fault_never_recovers_implicitly(self):
        self.policy.step("failure", 2)
        self.assertEqual(self.policy.state, "fault")
        for name in ("home", "approach", "grip", "return_home", "gesture"):
            with self.assertRaises(RuntimeError):
                self.complete(name)

    def test_older_configuration_and_misplaced_hand_poses_are_refused(self):
        from cup_shake.runtime import CupApplication

        with tempfile.TemporaryDirectory(prefix="dice schema ") as temporary:
            config = json.loads(MOCK.read_text(encoding="utf-8"))
            path = Path(temporary) / "cup_application.json"
            for change, message in (
                (dict(schema_version=2), "schema_version 3"),
                # A green cup planner reads its hand poses from green_cup.json.
                (dict(planner=dict(type="green_cup")), "remove duration_s, gestures"),
            ):
                path.write_text(json.dumps(dict(config, **change)), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, message):
                    CupApplication(path)
            fixture = {k: v for k, v in config.items() if k != "grip_positions"}
            path.write_text(json.dumps(fixture), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "fixture planner needs"):
                CupApplication(path)

    def test_visual_paths_resolve_from_application_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "site"
            config = dict(
                type="green_cup",
                source_root="../assets",
                config="../assets/config.json",
                session_directory="runtime/sessions",
            )
            with patch("cup_shake.green_cup.GreenCupPlanner") as planner:
                make_planner(config, lambda: None, "agx_nero_revo2", base)
                actual = planner.call_args.args[0]
                self.assertEqual(Path(actual["source_root"]), Path(temporary) / "assets")
                self.assertEqual(Path(actual["config"]), Path(temporary) / "assets/config.json")
                self.assertEqual(Path(actual["session_directory"]), base / "runtime/sessions")

    @unittest.skipUnless(os.environ.get("MANIPULATION_DEVICE"), "device executable not supplied")
    def test_mock_full_application_and_cancel_latch(self):
        with tempfile.TemporaryDirectory(prefix="cup-application-") as temporary:
            config = json.loads(MOCK.read_text())
            state_file = Path(temporary) / "runtime/task_state.json"
            config.update(
                executable=os.environ["MANIPULATION_DEVICE"],
                device_plan=str(SDK / "components/control/manipulation/examples/mock_device.yaml"),
                policy_library=os.environ["CUP_TASK_LIBRARY"],
                state_file=str(state_file),
            )
            filename = Path(temporary) / "app.json"
            filename.write_text(json.dumps(config))
            open_loop = Path(temporary) / "open_loop.yaml"
            open_loop.write_text(
                (SDK / "components/control/manipulation/examples/mock_device.yaml")
                .read_text()
                .replace("    effector:\n", "    effector:\n        feedback: none\n")
            )
            loop_config = dict(config, device_plan=str(open_loop))
            (Path(temporary) / "loop.json").write_text(json.dumps(loop_config))
            app = CupApplication(Path(temporary) / "loop.json", allow_motion=True)
            # Open-loop hand: the cycle completes on unverified hand moves, grip stays unverified.
            try:
                # An unmeasured hand is opened before the first grasp, even at HOME.
                self.assertFalse(app.command("query_pose")["at_home"])
                events = []
                self.assertEqual(
                    app.command("grasp_cup", on_event=events.append)["status"], "completed"
                )
                self.assertIn("home", [event.get("phase") for event in events])
                for command in ("shake_dice", "settle_dice"):
                    self.assertEqual(app.command(command)["status"], "completed")
                for command in ("grasp_cup", "shake_dice", "settle_dice"):
                    result = app.command(command)
                    self.assertEqual(result["status"], "completed", result)
                    self.assertFalse(result["physical_grip_verified"])
                self.assertTrue(app.command("query_pose")["at_home"])
            finally:
                app.close()
            app = CupApplication(filename, allow_motion=True)
            try:
                for command in ("grasp_cup", "shake_dice", "settle_dice"):
                    result = app.command(command)
                    self.assertEqual(result["status"], "completed", result)
                self.assertTrue(app.command("query_pose")["at_home"])
                self.assertEqual(app.command("gesture:win")["status"], "completed")
                self.assertTrue(app.command("query_pose")["at_home"])
                for command in ("reset_home", "ensure_home"):  # The original home action moves.
                    result = app.command(command)
                    self.assertEqual(
                        (result["status"], result["at_home"]), ("completed", True), result
                    )
                # Cancelled before anything moved: nothing to inspect, the task stays idle.
                result = app.command("grasp_cup", is_cancelled=lambda: True)
                self.assertEqual((result["status"], app.policy.state), ("failed", "ready"))
                self.assertFalse(state_file.exists())
                # Cancelled once the arm moves: the task latches and the state is recorded.
                calls = iter([False] * 6 + [True] * 1000)
                result = app.command("grasp_cup", is_cancelled=lambda: next(calls))
                self.assertEqual((result["status"], app.policy.state), ("failed", "fault"))
                self.assertEqual(app.command("grasp_cup")["status"], "failed")
                self.assertEqual(
                    app.command("reset_home")["status"], "failed"
                )  # Never after a fault.
            finally:
                app.close()
            # The record outlives the process until the operator resets it.
            self.assertEqual(json.loads(state_file.read_text())["state"], "fault")
            app = CupApplication(filename, allow_motion=True)
            try:
                result = app.command("reset_home")
                self.assertEqual(result["status"], "failed")
                self.assertIn("dice-arena reset", result["reason"])
            finally:
                app.close()
            self.assertEqual(CupApplication(filename).reset()["state"], "fault")
            self.assertFalse(state_file.exists())
            app = CupApplication(filename, allow_motion=True)
            try:
                self.assertEqual(app.command("reset_home")["status"], "completed")
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
