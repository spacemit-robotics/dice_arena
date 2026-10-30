"""Joint model for offline route planning, from the framework's robot description (URDF)."""

from dataclasses import dataclass

import numpy as np

import framework


@dataclass(frozen=True)
class Joint:
    name: str
    lower_rad: float
    upper_rad: float


class Model:
    def __init__(self, kinematics):
        self.kinematics = kinematics
        self.joints = [
            Joint(joint.get("name"), float(joint.find("limit").get("lower")), float(joint.find("limit").get("upper")))
            for joint in kinematics.chain
            if joint.get("type") == "revolute"
        ]

    def fk(self, q_rad):
        """Flange pose; limits are checked by the planner against `joints`, not here."""
        return np.asarray(self.kinematics.forward(list(q_rad), check_limits=False), dtype=float).reshape(4, 4)


def load_model():
    return Model(framework.robot_model())
