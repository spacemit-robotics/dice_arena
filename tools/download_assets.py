#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Download and verify runtime resources without connecting to hardware."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import sys
import tempfile
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import urlopen

from check_assets import ROOT, check_assets


def validate_downloads(manifest, base_url):
    """Validate every download location before creating any files."""
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in ("https", "http")
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be an HTTP(S) directory without credentials, query or fragment")
    for record in manifest["files"]:
        for key in ("path", "remote_path"):
            value = record.get(key)
            if (
                not isinstance(value, str)
                or not PurePosixPath(value).parts
                or PurePosixPath(value).is_absolute()
                or ".." in PurePosixPath(value).parts
                or "\\" in value
                or "\x00" in value
            ):
                raise ValueError(f"invalid asset {key}: {value!r}")
        if type(record.get("executable", False)) is not bool:
            raise ValueError("executable must be a boolean")


def fetch_asset(url, destination, record, timeout):
    """Verify a temporary download, then publish it without overwriting an existing file."""
    temporary = None
    try:
        digest, size = hashlib.sha256(), 0
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".asset-", delete=False) as stream:
            temporary = Path(stream.name)
            with urlopen(url, timeout=timeout) as response:
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    size += len(chunk)
                    if size > record["size_bytes"]:
                        raise ValueError(f"size mismatch: {record['path']}")
                    digest.update(chunk)
                    stream.write(chunk)
        if size != record["size_bytes"] or digest.hexdigest() != record["sha256"]:
            raise ValueError(f"size or SHA-256 mismatch: {record['path']}")
        temporary.chmod(0o755 if record.get("executable", False) else 0o644)
        os.link(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def download_assets(root, manifest, base_url=None, timeout=30, attempts=3):
    """Restore manifest paths; retain matching files and refuse to replace differing files."""
    root = root.expanduser().resolve()
    base_url = base_url if base_url is not None else manifest.get("base_url", "")
    missing, mismatched = check_assets(root, manifest, verify=True)
    validate_downloads(manifest, base_url)
    if timeout <= 0 or attempts < 1:
        raise ValueError("timeout and attempts must be positive")
    if mismatched:
        raise ValueError("existing resources differ; move them aside before retrying: " + ", ".join(mismatched))
    missing = set(missing)
    downloaded = 0
    for record in manifest["files"]:
        if record["path"] not in missing:
            destination = root / record["path"]
            if record.get("executable", False) and not os.access(destination, os.X_OK):
                raise ValueError(f"executable permission missing; run chmod +x {destination}")
            continue
        destination = root / record["path"]
        if destination.is_symlink():
            raise ValueError(f"broken asset symlink: {record['path']}")
        if not destination.parent.resolve().is_relative_to(root):
            raise ValueError(f"download would write outside resource root: {record['path']}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = base_url.rstrip("/") + "/" + quote(record["remote_path"], safe="/")
        print(f"Downloading {record['path']}", file=sys.stderr, flush=True)
        for attempt in range(1, attempts + 1):
            try:
                fetch_asset(url, destination, record, timeout)
                break
            except FileExistsError:
                raise
            except (OSError, ValueError) as error:
                permanent_http_error = isinstance(error, HTTPError) and error.code not in (408, 429, 500, 502, 503, 504)
                if isinstance(error, HTTPError):
                    error.close()
                if attempt == attempts or permanent_http_error:
                    raise
                print(f"Retry {attempt}/{attempts}: {error}", file=sys.stderr, flush=True)
        downloaded += 1
    return dict(assets=len(manifest["files"]), downloaded=downloaded, skipped=len(manifest["files"]) - downloaded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="destination application resource root")
    parser.add_argument("--base-url", help="override archive directory URL for a mirror")
    args = parser.parse_args()
    try:
        manifest = json.loads((ROOT / "runtime_assets.json").read_text())
        result = download_assets(args.root, manifest, args.base_url)
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Resource download failed: {error}\n")
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
