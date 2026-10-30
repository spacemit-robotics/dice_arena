"""Where this program's files are.

ROOT: this application (application/native/dice_arena). Relative paths in the configuration name
  resources shipped here: calibration/config/ (workflow, HOME, boards), calibration/trajectories/.
SITE: the manipulation site directory. Paths written `site:...` in the configuration live there:
  datasets and Web state (SITE/calibration/), the installed result and the green-cup pipeline
  configuration that cup-shake uses (SITE/green_cup.json).
SOURCE: the green-cup vision and grasp algorithms of this application (algorithms/), used by
  `apply`/`table` for table capture and registration, as cup-shake uses them for grasping.
"""

import os
from pathlib import Path

ROOT = CODE = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "calibration/config/calibration_workflow.json"
_DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share")
SITE = Path(os.environ.get("MANIPULATION_SITE") or _DATA_HOME / "spacemit-manipulation/site").expanduser().absolute()
SOURCE = ROOT / "algorithms"


def resolve(value):
    """`site:NAME` is SITE/NAME; other relative paths are resources of this application."""
    text = str(value)
    if text.startswith("site:"):
        return SITE / text[5:]
    path = Path(text).expanduser()
    return path if path.is_absolute() else ROOT / path
