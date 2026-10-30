"""The grasp algorithms' Nero URDF uses the pyAgxArm joint-limit preset, as the framework does."""

import ast
import xml.etree.ElementTree as ET
from pathlib import Path

SDK = Path(__file__).resolve().parents[5]
URDF = (
    Path(__file__).resolve().parents[2]
    / "algorithms/nero_revo2_control/models/hand_geometry/nero/urdf/nero_description.urdf"
)


def test_urdf_limits_are_the_vendor_preset():
    constants = SDK / "components/thirdparty/pyagxarm/pyAgxArm/api/constants.py"
    preset = next(
        ast.literal_eval(node.value)["nero"]
        for node in ast.walk(ast.parse(constants.read_text()))
        if isinstance(node, ast.Assign)
        and any(getattr(t, "id", "") == "ROBOT_JOINT_LIMIT_PRESET_RAD" for t in node.targets)
    )
    limits = {
        joint.get("name"): [float(joint.find("limit").get(k)) for k in ("lower", "upper")]
        for joint in ET.parse(URDF).getroot().findall("joint")
        if joint.get("type") == "revolute"
    }
    assert limits == preset
