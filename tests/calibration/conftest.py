"""Import path for calibration package tests, and a throwaway site directory.

calibration/ modules import each other by bare module name (e.g.
``from core import ...``); that only resolves with the calibration
directory itself on sys.path.  Real runs get it from executing scripts
inside calibration/, while these tests import ``calibration.xxx`` as a
package -- append the source directory so both forms coexist.
Tests never write to a real site: MANIPULATION_SITE is replaced before
calibration.paths is imported.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

SITE = tempfile.mkdtemp(prefix="calibration-site-")
os.environ["MANIPULATION_SITE"] = SITE
atexit.register(shutil.rmtree, SITE, ignore_errors=True)
CALIBRATION_DIR = Path(__file__).resolve().parents[2] / "calibration"
if str(CALIBRATION_DIR) not in sys.path:
    sys.path.append(str(CALIBRATION_DIR))
