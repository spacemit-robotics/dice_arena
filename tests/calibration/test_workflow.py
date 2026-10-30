"""Workflow orchestration tests: no camera, CAN or robot motion."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workflow


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.cfg = copy.deepcopy(workflow.read(workflow.CONFIG))
        self.cfg.update(
            output_root=str(self.root / "runs"),
            state_file=str(self.root / "state.json"),
            allow_provisional=False,
            dataset=None,
            result=None,
            plan=None,
            registration=None,
        )
        self.path = self.root / "config.json"
        self.write()

    def write(self):
        self.path.write_text(json.dumps(self.cfg))

    def test_invalid_motion_fails_before_subprocess(self):
        self.cfg["motion"]["speed_deg_s"] = 21  # Above the framework's 20°/s streaming ceiling.
        self.write()
        with self.assertRaisesRegex(ValueError, "speed_deg_s"):
            workflow.Workflow(self.path)
        self.cfg["motion"]["speed_deg_s"] = float("nan")
        self.write()
        with patch("workflow.subprocess.run") as run:
            with self.assertRaisesRegex(ValueError, "speed_deg_s"):
                workflow.Workflow(self.path)
            run.assert_not_called()

    def test_thresholds_reach_both_solvers_and_legacy_defaults_remain(self):
        for measurement in (None, {"width_mm": 86.5, "height_mm": 108}):
            for thresholds, expected in ((None, (5.0, 2.0)), ({"position_mm": 15, "angle_deg": 5}, (15, 5))):
                self.cfg["measurement"] = measurement
                self.cfg.pop("quality_thresholds", None)
                if thresholds is not None:
                    self.cfg["quality_thresholds"] = thresholds
                self.write()
                w = workflow.Workflow(self.path, True)
                with patch.object(w, "call") as call:
                    w.solve("/unused")
                args = call.call_args.args
                self.assertEqual(args[args.index("--max-position-mm") + 1], expected[0])
                self.assertEqual(args[args.index("--max-angle-deg") + 1], expected[1])

    def test_invalid_thresholds_fail_before_work_starts(self):
        for value in (0, -1, float("nan"), float("inf"), True, 1000):
            self.cfg["quality_thresholds"] = {"position_mm": value, "angle_deg": 5}
            self.write()
            with self.assertRaisesRegex(ValueError, "quality_thresholds"):
                workflow.Workflow(self.path)

    def test_dry_run_auto_never_changes_files_or_calls_hardware(self):
        self.cfg["plan"] = "some_plan.json"
        self.write()
        w = workflow.Workflow(self.path, True)
        with patch("workflow.subprocess.run") as run:
            w.run("auto")
            run.assert_not_called()
        self.assertFalse(w.state_path.exists())
        self.assertFalse((self.root / "runs").exists())

    def test_execute_opt_in_is_gone(self):
        # Motion steps run directly; only --dry-run previews them.
        with self.assertRaises(SystemExit):
            workflow.main(["auto", "--execute", "--config", str(self.path)])

    def test_failed_collection_does_not_solve_or_advance_state(self):
        self.cfg.update(plan=str(self.root / "plan.json"), allow_provisional=True)
        self.write()
        result = self.root / "result.json"
        result.write_text('{"quality_passed":true}')
        (self.root / "plan.json").write_text(json.dumps({"calibration": str(result)}))
        w = workflow.Workflow(self.path)
        with patch("workflow.require_idle"), patch("workflow.subprocess.run") as run:
            run.return_value.returncode = 1
            with self.assertRaises(RuntimeError):
                w.run("auto")
            self.assertEqual(run.call_count, 1)
            self.assertIn("--start-from", run.call_args.args[0])
        self.assertFalse(w.state_path.exists())

    def test_generated_state_is_used_and_explicit_config_overrides(self):
        w = workflow.Workflow(self.path)
        w.save(plan="/generated/plan.json", dataset="/generated/data")
        self.assertEqual(w.selected("plan"), Path("/generated/plan.json"))
        self.cfg["plan"] = "/explicit/plan.json"
        self.write()
        self.assertEqual(workflow.Workflow(self.path).selected("plan"), Path("/explicit/plan.json"))

    def test_restore_routes_home_and_all_motion_config(self):
        self.cfg["registration"] = "/registered.json"
        self.write()
        w = workflow.Workflow(self.path, True)
        with patch.object(w, "call") as run:
            w.run("restore")
        args = run.call_args.args
        self.assertEqual(args[:2], ("calibration/reference_board.py", "restore-auto"))
        self.assertIn("--home", args)
        self.assertNotIn("--execute", args)
        self.assertEqual(args[args.index("--speed-percent") + 1], 40)

    def test_apply_rejects_bad_quality_without_mutations(self):
        r = self.root / "bad.json"
        r.write_text('{"quality_passed":false}')
        self.cfg["result"] = str(r)
        self.write()
        w = workflow.Workflow(self.path)
        with patch("workflow.require_idle"), patch.object(w, "call") as call:
            with self.assertRaisesRegex(ValueError, "质量未通过"):
                w.run("apply")
            call.assert_not_called()
        self.assertFalse((self.root / "runs").exists())

    def test_apply_backs_up_before_install_and_stops_on_table_failure(self):
        result = self.root / "result.json"
        result.write_text('{"quality_passed":true}')
        old = self.root / "old.json"
        old.write_text("old calibration")
        table = self.root / "table.json"
        table.write_text("old table")
        pipeline = self.root / "pipeline.json"
        pipeline.write_text(json.dumps({"calibration": str(old), "green_cup": {"home_table_scene": str(table)}}))
        self.cfg.update(result=str(result), pipeline_config=str(pipeline))
        self.write()
        w = workflow.Workflow(self.path)
        calls = []

        def call(script, *args, **kwargs):
            calls.append(script)
            backup = Path(w.state["backup"])
            self.assertEqual((backup / "handeye_result.json").read_text(), "old calibration")
            self.assertEqual((backup / "home_table_scene.json").read_text(), "old table")
            if script == "calibration/tools/table_capture.py":
                raise RuntimeError("camera busy")

        with patch("workflow.require_idle"), patch.object(w, "call", side_effect=call):
            with self.assertRaisesRegex(RuntimeError, "camera busy"):
                w.run("apply")
        self.assertEqual(calls, ["calibration/apply_result.py", "calibration/tools/table_capture.py"])
        self.assertNotIn("table", w.state)

    def test_missing_table_tools_stop_before_install_or_backup(self):
        result = self.root / "result.json"
        result.write_text('{"quality_passed":true}')
        self.cfg["result"] = str(result)
        self.write()
        w = workflow.Workflow(self.path)
        with patch("workflow.require_idle"), patch.object(workflow, "CODE", self.root), patch.object(w, "call") as call:
            with self.assertRaisesRegex(ValueError, "桌面登记工具不存在"):
                w.run("apply")
            call.assert_not_called()
        self.assertFalse((self.root / "runs").exists())
        self.assertFalse(w.state_path.exists())

    def test_table_retry_needs_an_applied_site_pipeline(self):
        w = workflow.Workflow(self.path)
        with patch("workflow.require_idle"), patch.object(w, "call") as call:
            with self.assertRaisesRegex(ValueError, "请先执行 apply"):
                w.run("table")
            call.assert_not_called()

    def test_first_apply_creates_the_site_pipeline_from_the_algorithm_template(self):
        source, site = self.root / "source", self.root / "site"
        (source / "configs").mkdir(parents=True)
        (source / "configs/green_cup.json").write_text(
            json.dumps(
                {
                    "calibration": "configs/calibration/handeye_result.json",
                    "home": "configs/actions/home.json",
                    "green_cup": {
                        "home_table_scene": "flow/home_table_scene.json",
                        "installation_requires_calibration": False,
                    },
                }
            )
        )
        result = self.root / "result.json"
        result.write_text('{"quality_passed":true}')
        self.cfg.update(result=str(result), pipeline_config=str(site / "green_cup.json"))
        self.write()
        w = workflow.Workflow(self.path)
        with (
            patch("workflow.require_idle"),
            patch.object(workflow, "SOURCE", source),
            patch.object(workflow, "SITE", site),
            patch.object(w, "call") as call,
        ):
            w.run("apply")
        created = json.loads((site / "green_cup.json").read_text())
        self.assertEqual(created["calibration"], str(site / "calibration/handeye_result.json"))
        self.assertEqual(created["green_cup"]["home_table_scene"], str(site / "calibration/home_table_scene.json"))
        self.assertTrue(created["green_cup"]["installation_requires_calibration"])
        self.assertEqual(created["home"], "configs/actions/home.json")  # Algorithm resources stay relative.
        self.assertEqual(sorted(p.name for p in Path(w.state["backup"]).iterdir()), ["pipeline_config.json"])
        self.assertEqual(
            [c.args[0] for c in call.call_args_list], ["calibration/apply_result.py", *workflow.TABLE_TOOLS]
        )

    def test_table_retry_uses_existing_tools_and_records_only_complete_capture(self):
        pipeline = workflow.resolve(self.cfg["pipeline_config"])
        pipeline.parent.mkdir(parents=True, exist_ok=True)
        pipeline.write_text("{}")
        self.addCleanup(pipeline.unlink)
        w = workflow.Workflow(self.path)
        scripts = []

        def call(script, *args, **kwargs):
            self.assertTrue((workflow.CODE / script).is_file())
            scripts.append(script)

        with patch("workflow.require_idle"), patch.object(w, "call", side_effect=call):
            w.run("table")
        self.assertEqual(scripts, list(workflow.TABLE_TOOLS))
        self.assertIn("table", w.state)
        self.assertNotIn("backup", w.state)

    def test_first_solves_and_tracks_new_teaching_calibration(self):
        w = workflow.Workflow(self.path)

        def call(script, *args, **kwargs):
            if script.endswith("reprocess_dimensions.py"):
                out = Path(args[args.index("--output") + 1])
                out.mkdir(parents=True)
                (out / "result.json").write_text('{"quality_passed":true}')

        with patch("workflow.require_idle"), patch.object(w, "call", side_effect=call):
            w.run("first")
        self.assertEqual(w.state["result"], w.state["teaching_calibration"])
        self.assertEqual(w.state["dataset"], w.state["teaching_dataset"])


if __name__ == "__main__":
    unittest.main()
