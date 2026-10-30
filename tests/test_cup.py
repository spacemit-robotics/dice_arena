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
            {"python3-numpy", "python3-opencv", "python3-scipy", "python3-spacemit-ort", "spacemit-onnxruntime"}
            <= set(dependencies)
        )
        self.assertTrue((SDK / "components/control/manipulation/examples/point_sequence/point_sequence.yaml").is_file())
        for resource in ("algorithms", "calibration", "game", "python/cup_shake"):
            self.assertTrue((ROOT / resource).is_dir(), resource)

    @unittest.skipUnless(os.environ.get("DICE_COMPATIBILITY_SCRIPT"), "install script not supplied")
    def test_resource_alias_preserves_existing_installations(self):
        script = os.environ["DICE_COMPATIBILITY_SCRIPT"]
        environment = dict(os.environ)
        environment.pop("DESTDIR", None)
        with tempfile.TemporaryDirectory(prefix="dice install upgrade ") as temporary:
            prefix = Path(temporary)
            resources = prefix / os.environ["DICE_DATADIR"]
            resources.mkdir(parents=True)
            canonical = resources / "dice_arena"
            canonical.mkdir()
            legacy = resources / "cup_shake"

            def install_alias(expected=0):
                result = subprocess.run(
                    ["cmake", "-DCMAKE_INSTALL_PREFIX=" + str(prefix), "-P", script],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

            install_alias()
            self.assertEqual(os.readlink(legacy), "dice_arena")
            self.assertTrue(legacy.samefile(canonical))
            install_alias()  # Repeated installation keeps the same relative link.
            legacy.unlink()
            legacy.mkdir()
            saved = legacy / "site-resource.json"
            saved.write_text('{"preserve": true}\n')
            install_alias()
            self.assertFalse(legacy.is_symlink())
            self.assertEqual(saved.read_text(), '{"preserve": true}\n')
            saved.unlink()
            legacy.rmdir()
            legacy.symlink_to("operator-resource", target_is_directory=True)
            install_alias(expected=1)
            self.assertEqual(os.readlink(legacy), "operator-resource")


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

    def test_fault_never_recovers_implicitly(self):
        self.policy.step("failure", 2)
        self.assertEqual(self.policy.state, "fault")
        for name in ("home", "approach", "grip", "return_home", "gesture"):
            with self.assertRaises(RuntimeError):
                self.complete(name)

    def test_visual_paths_resolve_from_application_configuration(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "site"
            config = dict(
                type="legacy_green",
                source_root="../assets",
                config="../assets/config.json",
                session_directory="runtime/sessions",
            )
            with patch("cup_shake.legacy_green.LegacyGreenPlanner") as planner:
                make_planner(config, lambda: None, "agx_nero_revo2", base)
                actual = planner.call_args.args[0]
                self.assertEqual(Path(actual["source_root"]), Path(temporary) / "assets")
                self.assertEqual(Path(actual["config"]), Path(temporary) / "assets/config.json")
                self.assertEqual(Path(actual["session_directory"]), base / "runtime/sessions")

    @unittest.skipUnless(os.environ.get("MANIPULATION_DEVICE"), "device executable not supplied")
    def test_mock_full_application_and_cancel_latch(self):
        with tempfile.TemporaryDirectory(prefix="cup-application-") as temporary:
            config = json.loads((ROOT / "config/mock.json").read_text())
            config.update(
                executable=os.environ["MANIPULATION_DEVICE"],
                device_plan=str(SDK / "components/control/manipulation/examples/mock_device.yaml"),
                policy_library=os.environ["CUP_TASK_LIBRARY"],
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
            try:  # Open-loop hand: the cycle completes on unverified hand moves, grip stays unverified.
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
                    self.assertEqual((result["status"], result["at_home"]), ("completed", True), result)
                result = app.command("grasp_cup", is_cancelled=lambda: True)
                self.assertEqual(result["status"], "failed")
                self.assertEqual(app.policy.state, "fault")
                self.assertEqual(app.command("grasp_cup")["status"], "failed")
                self.assertEqual(app.command("reset_home")["status"], "failed")  # Never after a fault.
            finally:
                app.close()


if __name__ == "__main__":
    unittest.main()
