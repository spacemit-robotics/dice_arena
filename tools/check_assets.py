#!/usr/bin/env python3
# Copyright (C) 2026 SpacemiT (Hangzhou) Technology Co. Ltd.
# SPDX-License-Identifier: Apache-2.0
"""Check separately distributed runtime resources without opening hardware or network connections."""

import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def check_assets(root, manifest, verify=False):
    """Return missing and mismatched relative resource paths; reject invalid manifest entries."""
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError("invalid runtime asset manifest")
    missing, mismatched, seen = [], [], set()
    for record in manifest["files"]:
        relative = Path(record["path"])
        size, digest = record["size_bytes"], record["sha256"]
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or not relative.parts
            or relative.as_posix() in seen
            or type(size) is not int
            or size < 0
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            raise ValueError("invalid runtime asset entry")
        seen.add(relative.as_posix())
        resource = root / relative
        if not resource.is_file():
            missing.append(relative.as_posix())
            continue
        if resource.stat().st_size != size:
            mismatched.append(relative.as_posix())
            continue
        if verify:
            actual = hashlib.sha256()
            with resource.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    actual.update(chunk)
            if actual.hexdigest() != digest:
                mismatched.append(relative.as_posix())
    return missing, mismatched


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="application resource root")
    parser.add_argument("--verify", action="store_true", help="verify SHA-256 in addition to size and existence")
    args = parser.parse_args()
    manifest = json.loads((ROOT / "runtime_assets.json").read_text())
    missing, mismatched = check_assets(args.root, manifest, args.verify)
    print(
        json.dumps(
            dict(assets=len(manifest["files"]), missing=missing, mismatched=mismatched, sha256_verified=args.verify),
            ensure_ascii=False,
        )
    )
    return 1 if missing or mismatched else 0


if __name__ == "__main__":
    raise SystemExit(main())
