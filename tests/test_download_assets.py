# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Exercise downloads against an isolated local HTTP fixture, without hardware."""

import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib
import io
import os
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
try:
    DOWNLOAD = importlib.import_module("download_assets")
finally:
    sys.path.pop(0)


class DownloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.requests += 1
                status = cls.status.pop(0) if cls.status else 200
                self.send_response(status)
                self.end_headers()
                self.wfile.write(cls.content)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/files/"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        type(self).requests = 0
        type(self).status = []
        type(self).content = b"data"
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "resources"
        self.manifest = dict(
            schema_version=1,
            base_url=self.url,
            files=[dict(path="models/model.bin", remote_path="model.bin", size_bytes=4,
                        sha256=hashlib.sha256(b"data").hexdigest())],
        )

    def download(self, **kwargs):
        with contextlib.redirect_stderr(io.StringIO()):
            return DOWNLOAD.download_assets(self.root, self.manifest, **kwargs)

    def test_download_and_idempotent_skip(self):
        self.assertEqual(self.download(), dict(assets=1, downloaded=1, skipped=0))
        self.assertEqual((self.root / "models/model.bin").read_bytes(), b"data")
        self.assertEqual(self.download(), dict(assets=1, downloaded=0, skipped=1))
        self.assertEqual(type(self).requests, 1)

    def test_executable_permission_and_mirror(self):
        self.manifest["files"][0]["executable"] = True
        self.manifest["base_url"] = "https://invalid.example/"
        self.download(base_url=self.url)
        self.assertTrue(os.access(self.root / "models/model.bin", os.X_OK))

    def test_existing_differing_file_is_not_replaced(self):
        (self.root / "models").mkdir(parents=True)
        target = self.root / "models/model.bin"
        target.write_bytes(b"fake")
        with self.assertRaisesRegex(ValueError, "existing resources differ"):
            self.download()
        self.assertEqual(target.read_bytes(), b"fake")
        self.assertEqual(type(self).requests, 0)

    def test_matching_external_symlink_is_retained(self):
        external = Path(self.temporary.name) / "external.bin"
        external.write_bytes(b"data")
        (self.root / "models").mkdir(parents=True)
        (self.root / "models/model.bin").symlink_to(external)
        self.assertEqual(self.download()["skipped"], 1)
        self.assertEqual(type(self).requests, 0)

    def test_unsafe_paths_are_rejected_before_writing(self):
        for key in ("path", "remote_path"):
            original = self.manifest["files"][0][key]
            for value in ("../outside", "/absolute", "", ".", "bad\\path", "bad\x00path"):
                self.manifest["files"][0][key] = value
                with self.assertRaises((OSError, ValueError)):
                    self.download()
                self.assertFalse(self.root.exists())
            self.manifest["files"][0][key] = original

    def test_parent_symlink_outside_root_is_rejected(self):
        self.root.mkdir()
        (self.root / "models").symlink_to(self.temporary.name)
        with self.assertRaisesRegex(ValueError, "outside resource root"):
            self.download()
        self.assertFalse((Path(self.temporary.name) / "model.bin").exists())

    def test_broken_symlink_is_not_replaced(self):
        (self.root / "models").mkdir(parents=True)
        target = self.root / "models/model.bin"
        target.symlink_to("missing")
        with self.assertRaisesRegex(ValueError, "broken asset symlink"):
            self.download()
        self.assertTrue(target.is_symlink())

    def test_corrupt_or_truncated_download_is_not_installed(self):
        for content in (b"fake", b"da", b"longer"):
            type(self).content = content
            with self.assertRaisesRegex(ValueError, "mismatch"):
                self.download(attempts=1)
            self.assertEqual(list(self.root.rglob(".asset-*")), [])
            self.assertFalse((self.root / "models/model.bin").exists())

    def test_transient_error_retries_but_not_missing_file(self):
        type(self).status = [503, 200]
        self.download()
        self.assertEqual(type(self).requests, 2)
        (self.root / "models/model.bin").unlink()
        type(self).status = [404]
        with self.assertRaises(HTTPError):
            self.download()
        self.assertEqual(type(self).requests, 3)

    def test_invalid_base_url_is_rejected(self):
        for url in ("file:///tmp/", "https://user:secret@example.com/", "https://example.com/?key=x"):
            with self.assertRaises(ValueError):
                self.download(base_url=url)
            self.assertFalse(self.root.exists())


if __name__ == "__main__":
    unittest.main()
