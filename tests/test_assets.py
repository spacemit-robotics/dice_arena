# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Runtime resource validation uses temporary files only."""

import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("dice_asset_check", ROOT / "tools/check_assets.py")
ASSETS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ASSETS)


class AssetTests(unittest.TestCase):
    def manifest(self, name="model.onnx"):
        return dict(schema_version=1, files=[dict(path=name, size_bytes=4, sha256=hashlib.sha256(b"data").hexdigest())])

    def test_missing_and_valid_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(ASSETS.check_assets(root, self.manifest()), (["model.onnx"], []))
            (root / "model.onnx").write_bytes(b"data")
            self.assertEqual(ASSETS.check_assets(root, self.manifest(), verify=True), ([], []))

    def test_size_and_hash_mismatches(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "model.onnx").write_bytes(b"longer")
            self.assertEqual(ASSETS.check_assets(root, self.manifest()), ([], ["model.onnx"]))
            (root / "model.onnx").write_bytes(b"fake")
            self.assertEqual(ASSETS.check_assets(root, self.manifest(), verify=True), ([], ["model.onnx"]))

    def test_linked_assets_are_supported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "external").write_bytes(b"data")
            (root / "model.onnx").symlink_to("external")
            self.assertEqual(ASSETS.check_assets(root, self.manifest(), verify=True), ([], []))

    def test_invalid_paths_and_duplicates_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in ("../outside", "/absolute"):
                with self.assertRaises(ValueError):
                    ASSETS.check_assets(Path(temporary), self.manifest(name))
            manifest = self.manifest()
            manifest["files"] *= 2
            with self.assertRaises(ValueError):
                ASSETS.check_assets(Path(temporary), manifest)


if __name__ == "__main__":
    unittest.main()
