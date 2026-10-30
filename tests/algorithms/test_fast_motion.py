"""cup-shake delivers each phase as the original FAST executor did: checked against the original
algorithm functions (joint_delivery trapezoid, joint_profile shake commands). No device."""

import json
import math
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "python"))
sys.path.insert(0, str(ROOT.parents[2] / "components/control/manipulation/bindings/python"))
sys.path.insert(0, str(ROOT / "algorithms"))
from cup_grasp_demo.flow import joint_delivery, joint_profile  # noqa: E402
from cup_shake.legacy_green import LegacyGreenPlanner  # noqa: E402

LIMITS = [
    dict(
        joint=i + 1,
        min_angle_rad=-2.7,
        max_angle_rad=2.7,
        max_velocity_rad_s=3.14 if i < 4 else 3.92,
        max_acceleration_rad_s2=5.0,
    )
    for i in range(7)
]
CONFIG = json.loads((ROOT / "algorithms/configs/green_cup.json").read_text())
RECIPE = json.loads((ROOT / "algorithms/configs/actions/joint_shake.json").read_text())


def planner():
    """The planner's motion methods without the camera/table/calibration it is normally built with."""
    instance = object.__new__(LegacyGreenPlanner)
    instance.g = CONFIG["green_cup"]
    instance.cfg = CONFIG
    instance.delivery, instance.profile = joint_delivery, joint_profile
    # As in production: FAST transitions on fast_motion_profile, gestures on the configuration as loaded.
    instance.options = joint_delivery.delivery_options(
        dict(CONFIG.get("joint_delivery", {}), profile=CONFIG["green_cup"].get("fast_motion_profile", "quintic"))
    )
    instance.gesture_options = joint_delivery.delivery_options(CONFIG.get("joint_delivery"))
    instance.settled_rad = math.radians(instance.g.get("settled_joint_delta_deg", 0.5))
    instance.held = None
    model_limits = [(row["min_angle_rad"], row["max_angle_rad"]) for row in LIMITS]
    instance.workflow = SimpleNamespace(
        build_shake=lambda feedback: (joint_profile.make_plan(feedback, RECIPE, model_limits), {})
    )
    instance.unchanged = lambda: None
    instance.lift_end = instance.shake_future = None
    instance.core = __import__("cup_grasp_demo.flow.core", fromlist=["core"])
    instance.screen_cache = {}
    instance.state = lambda: dict(joints_rad=instance.at, moving=False)
    return instance


def steps(motion):
    knots = motion["positions_rad"]
    return [max(abs(b - a) for a, b in zip(p, q)) for p, q in zip(knots, knots[1:])]


def test_phase_speeds_are_the_fast_configuration():
    instance = planner()
    assert instance.speed_percent("approach") == 100
    assert instance.speed_percent("return_home") == 100
    assert instance.speed_percent("lower") == 100
    assert instance.speed_percent("lift") == CONFIG["green_cup"]["fast_speed_percent"] == 30


def test_transition_is_the_original_trapezoid():
    instance = planner()
    start, middle, end = [0.0] * 7, [0.6, -0.2, 0.1, 0.3, 0.0, 0.2, -0.4], [0.2] * 7
    for speed in (100, 30):
        motion = instance.transition(start, [middle, end], speed, LIMITS)
        velocity = [row["max_velocity_rad_s"] * speed / 100 * instance.options["limit_utilization"] for row in LIMITS]
        acceleration = [
            min(row["max_acceleration_rad_s2"], instance.options["acceleration_cap_rad_s2"])
            * instance.options["limit_utilization"]
            for row in LIMITS
        ]
        first = joint_delivery.trapezoid_profile(start, middle, velocity, acceleration)[0]
        second = joint_delivery.trapezoid_profile(middle, end, velocity, acceleration)[0]
        assert motion["positions_rad"][0] == start and motion["positions_rad"][-1] == end
        assert math.isclose(motion["times_s"][-1], first + second)
        # Rest at the stage boundary: the middle knot is a profile endpoint.
        assert middle in motion["positions_rad"]
        assert motion["speed_scale"] == speed / 100 and motion["max_step_rad"] == math.radians(1)
        # The command rate keeps each command step near 0.5 degrees, as the original sample period.
        peak = max(s / (t2 - t1) for s, t1, t2 in zip(steps(motion), motion["times_s"], motion["times_s"][1:]))
        assert peak / motion["command_rate_hz"] <= math.radians(0.55)
        assert motion["tolerance_rad"] == math.radians(0.5)
        assert motion["wait_for_arrival"] is False  # FAST completion: hand over once the last target is sent.


def test_shake_streams_the_recipe_commands():
    instance = planner()
    start = [0.1, -1.0, -1.4, 1.6, 0.2, -0.1, 0.3]
    instance.at = start
    motion = instance.shake(start, LIMITS)
    plan = joint_profile.make_plan(
        dict(success=True, limits=LIMITS, q_after_rad=start),
        RECIPE,
        [(row["min_angle_rad"], row["max_angle_rad"]) for row in LIMITS],
    )
    rate = RECIPE["command_rate_hz"]
    assert motion["command_rate_hz"] == rate and motion["speed_scale"] == RECIPE["controller_speed_percent"] / 100
    assert motion["max_step_rad"] == math.radians(RECIPE["command_step_deg"])
    knots, times = motion["positions_rad"], motion["times_s"]
    assert knots[0] == start and knots[-1] == start
    assert math.isclose(times[-1], plan["duration_s"] + 1 / rate)
    # Every streamed knot is the original command at its time, one tick after the start.
    for t, q in list(zip(times, knots))[1:-1]:
        expected = joint_profile.command_values(plan, t - 1 / rate)
        assert max(abs(a - b) for a, b in zip(q, expected)) < 1e-12
    assert max(steps(motion)) <= motion["max_step_rad"]
    deviation = [max(abs(q[i] - start[i]) for q in knots) for i in range(7)]
    for joint, amplitude in zip(RECIPE["joints"], RECIPE["amplitude_deg"]):
        assert math.isclose(deviation[joint - 1], math.radians(amplitude), rel_tol=1e-3)  # 200 Hz samples
    assert deviation[1] == 0  # Joint 2 is not in the recipe.
    assert 8 * 0.3 < plan["duration_s"] < 8 * 0.6  # Eight cycles of about 0.4 s.
    assert motion["wait_for_arrival"] is False


def test_lift_follows_the_grip_command_without_operator_confirmation():
    """As the original application: the delivered grip command allows the lift (grip_confirmation none)."""
    from cup_shake.runtime import CupApplication

    app = object.__new__(CupApplication)
    app.config = {}
    app.client = SimpleNamespace(metadata=dict(driver="agx_nero_revo2"))
    events = []
    assert app._verify_grip(0, lambda: False, events.append) == "grip_commanded"
    assert events == []  # No acknowledgement is requested.


def test_shake_is_centred_on_the_lift_endpoint_once_the_arm_reaches_it():
    instance = planner()
    lift_end = [0.1, -1.0, -1.4, 1.6, 0.2, -0.1, 0.3]
    instance.lift_end = lift_end
    readings = iter([[v + 0.02 for v in lift_end], [v + 0.005 for v in lift_end]])  # Converging.
    instance.state = lambda: dict(joints_rad=next(readings), moving=True)
    motion = instance.shake([v + 0.03 for v in lift_end], LIMITS)
    assert motion["positions_rad"][0] == lift_end and motion["positions_rad"][-1] == lift_end
    # Settled short of it: re-planned around the measured pose, as the original start recovery.
    elsewhere = [v + 0.02 for v in lift_end]
    instance.lift_end = lift_end
    instance.state = lambda: dict(joints_rad=elsewhere, moving=False)
    motion = instance.shake(lift_end, LIMITS)
    assert motion["positions_rad"][0] == elsewhere and motion["positions_rad"][-1] == elsewhere


def test_planner_geometry_is_loaded_once_and_shared():
    """The original FAST run caches collision geometry for the whole run (cached_screen_geometry)."""
    from cup_grasp_demo.flow import core

    instance = planner()
    with instance.geometry():
        first = core.Screen(table_only=True)
    with instance.geometry():
        second = core.Screen(table_only=True)
    assert second.meshes is first.meshes and "source_geometry" in instance.screen_cache
    assert core._screen_cache.get() is None  # Nothing leaks outside the planner's calls.


def test_lower_is_the_original_controller_endpoint():
    """move_j at the phase speed, re-sent every 50 ms while beyond 0.5 deg, complete within it."""
    instance = planner()
    place = [0.1, -1.0, -1.4, 1.6, 0.2, -0.1, 0.3]
    instance.targets = lambda phase, state: [place]
    (motion,) = instance._motions("lower", dict(joints_rad=[0.0] * 7, controller_limits=LIMITS))
    assert motion == dict(
        kind="point",
        target=place,
        speed_scale=1.0,
        tolerance_rad=math.radians(0.5),
        wait_for_arrival=False,
        resend_interval_s=0.05,
    )


def test_lift_endpoint_is_solved_while_the_arm_approaches():
    from concurrent.futures import ThreadPoolExecutor

    instance = planner()
    grasp, lifted = [0.1, -1.0, -1.4, 1.6, 0.2, -0.1, 0.3], [0.1, -0.9, -1.4, 1.5, 0.2, -0.1, 0.3]
    instance.targets = lambda phase, state: [grasp]
    instance.g = dict(instance.g, lift_mm=40)
    solved = []
    instance.workflow.vertical = lambda label, start, dz, single_target: solved.append((label, start, dz)) or [lifted]
    instance.pool = ThreadPoolExecutor(max_workers=1)
    try:
        (motion,) = instance._motions("approach", dict(joints_rad=[0.0] * 7, controller_limits=LIMITS))
        assert motion["positions_rad"][-1] == grasp
        assert instance.following.result(timeout=5) == (grasp, [lifted])
        assert solved == [("lift", grasp, 0.04)]
    finally:
        instance.pool.shutdown()


def test_stored_geometry_is_the_computed_geometry(tmp_path):
    from cup_grasp_demo.flow import core
    from cup_shake.legacy_green import load_geometry, save_geometry

    instance = planner()
    with instance.geometry():
        core.Screen(table_only=True)
        core.Screen()
    path = tmp_path / "screen.npz"
    save_geometry(path, instance.screen_cache)
    stored = load_geometry(path, core.load_model())
    for key in ("table_geometry", "geometry"):
        computed = instance.screen_cache[key][1]
        assert list(stored[key][1]) == list(computed)
        for name, arrays in computed.items():
            for loaded, original in zip(stored[key][1][name], arrays):
                assert (loaded is None and original is None) or (loaded == original).all()
    path.write_bytes(path.read_bytes()[:100])
    assert load_geometry(path, None) is None  # Malformed: computed again, never trusted.


def gesture_planner():
    instance = planner()
    instance.root, instance.registry = ROOT / "algorithms", None
    instance.module = SimpleNamespace(
        arm_plan=lambda start, targets, scene, cfg: dict(
            blockers=[], stages=[dict(target_q_rad=list(target)) for target in targets]
        )
    )
    instance.workflow.table_scene = {}
    instance.ensure_geometry = lambda: None
    return instance


def test_feedback_gestures_are_the_original_recipes():
    """win/lose/draw: the arm to the recipe pose (quintic, recipe speed, configuration as loaded) with the
    hand targets sent from the first arm command at maximum speed, then the finger wait (feedback_execution)."""
    from cup_grasp_demo.flow.feedback_sequence import sequence_values

    recipes = json.loads((ROOT / "algorithms/configs/actions/gestures/result_feedback.json").read_text())
    instance = gesture_planner()
    start = [math.radians(v) for v in (0, -70, -90, 100, -10, -5, 5)]
    for kind, name in recipes["aliases"].items():
        recipe = recipes["gestures"][name]
        motion = instance.gesture(kind, dict(joints_rad=start, controller_limits=LIMITS))
        target = [math.radians(v) for v in recipe["joints_deg"]]
        assert motion["positions_rad"][0] == start and motion["positions_rad"][-1] == target
        options = instance.gesture_options
        assert options["profile"] == "quintic"
        velocity = [row["max_velocity_rad_s"] * options["limit_utilization"] for row in LIMITS]  # 100 %, no cap
        acceleration = [
            min(row["max_acceleration_rad_s2"], options["acceleration_cap_rad_s2"]) * options["limit_utilization"]
            for row in LIMITS
        ]
        assert math.isclose(
            motion["times_s"][-1], joint_delivery.smooth_duration(start, target, velocity, acceleration)
        )
        assert motion["speed_scale"] == recipe.get("speed_percent", recipes["speed_percent"]) / 100
        poses, interval = sequence_values(
            recipe.get("hand_sequence"), recipe["hand_0_100"], recipes["finger_max_wait_s"]
        )
        assert motion["effector_schedule"] == [
            (i * interval, [v / 100 for v in pose], 0.01) for i, pose in enumerate(poses)
        ]
        assert math.isclose(motion["hold_s"], recipes["finger_max_wait_s"] - 0.01)
        # Each streamed command (knots interpolated at command_rate_hz) stays within max_step_rad.
        ticks = [(b - a) * motion["command_rate_hz"] for a, b in zip(motion["times_s"], motion["times_s"][1:])]
        assert all(step <= motion["max_step_rad"] * max(1.0, n) for step, n in zip(steps(motion), ticks))


def test_home_action_opens_the_hand_at_home():
    instance = gesture_planner()
    motion = instance.gesture("home", dict(joints_rad=[0.1] * 7, controller_limits=LIMITS))
    home = json.loads((ROOT / "algorithms/configs/actions/home.json").read_text())["joints_rad"]
    assert motion["positions_rad"][-1] == home and motion["hand_open"]
    assert motion["effector_schedule"] == [(0.0, [0.0] * 6, 0.01)]
