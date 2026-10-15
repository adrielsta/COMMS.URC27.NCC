#!/usr/bin/env python3
"""Restore or verify the small, hash-pinned historical satellite tile bundle.

The application itself never downloads map tiles. Run this helper before field
deployment if a checked-in tile is missing; use --verify for an offline check.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import sys
import tempfile
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "web" / "imagery" / "metadata.json"
MAX_TILE_BYTES = 1024 * 1024
TIMEOUT_SECONDS = 20


def jpeg_dimensions(data):
    """Read JPEG dimensions without changing or decoding the source image."""
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("expected an intact JPEG file")
    offset = 2
    while offset < len(data):
        if data[offset] != 0xFF:
            raise ValueError("invalid JPEG marker")
        while offset < len(data) and data[offset] == 0xFF:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in {0xD9, 0xDA}:
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD8:
            continue
        if offset + 2 > len(data):
            break
        length = struct.unpack_from(">H", data, offset)[0]
        if length < 2 or offset + length > len(data):
            raise ValueError("invalid JPEG segment")
        if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
                      0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
            if length < 8:
                raise ValueError("invalid JPEG frame")
            height, width = struct.unpack_from(">HH", data, offset + 3)
            return width, height
        offset += length
    raise ValueError("JPEG dimensions are missing")


def verify_bytes(data, tile, tile_size):
    if not 0 < len(data) <= MAX_TILE_BYTES:
        raise ValueError("tile exceeds the permitted size")
    digest = hashlib.sha256(data).hexdigest()
    if digest != tile["sha256"]:
        raise ValueError("SHA-256 mismatch; reviewed imagery hashes are never updated automatically")
    if len(data) != tile["bytes"]:
        raise ValueError("tile byte count does not match provenance")
    if jpeg_dimensions(data) != (tile_size, tile_size):
        raise ValueError("tile dimensions do not match the manifest")


def tile_path(tile):
    relative = PurePosixPath(tile["path"])
    if (not relative.is_absolute() or ".." in relative.parts
            or len(relative.parts) != 3 or relative.parts[1] != "imagery"
            or not re.fullmatch(r"tile-\d+-\d+-\d+\.jpg", relative.name)):
        raise ValueError("tile path must identify /imagery/tile-<zoom>-<x>-<y>.jpg")
    destination = ROOT / "web" / str(relative).lstrip("/")
    if not destination.resolve().is_relative_to((ROOT / "web" / "imagery").resolve()):
        raise ValueError("tile path escapes the imagery directory")
    if destination.is_symlink() or destination.parent.is_symlink():
        raise ValueError("refusing a symlink in the imagery destination")
    return destination


class NoRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, url):
        raise ValueError("imagery source redirected; review the source before changing its URL")


def fetch(tile):
    source = urllib.parse.urlparse(tile["source_url"])
    if (source.scheme != "https" or source.hostname != "tiles.maps.eox.at"
            or source.port not in {None, 443} or source.username or source.password
            or source.query or source.fragment
            or not source.path.startswith("/wmts/1.0.0/")):
        raise ValueError("unexpected imagery source; only the reviewed EOX HTTPS WMTS is allowed")
    request = urllib.request.Request(tile["source_url"], headers={
        "User-Agent": "COMMS.URC27.NCC/offline-imagery-fetch",
        "Accept": "image/jpeg",
    })
    opener = urllib.request.build_opener(NoRedirects())
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200 or response.headers.get_content_type() != "image/jpeg":
            raise ValueError("source did not return a JPEG tile")
        return response.read(MAX_TILE_BYTES + 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="verify bundled files without network access")
    mode.add_argument("--refetch", action="store_true", help="re-download tiles and check the recorded hashes")
    args = parser.parse_args(argv)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or manifest.get("tile_size") != 256:
        raise ValueError("unsupported imagery manifest")
    if not 1 <= len(manifest["tiles"]) <= 25:
        raise ValueError("unexpected tile count")
    failures = []
    for tile in manifest["tiles"]:
        try:
            destination = tile_path(tile)
            if destination.exists():
                if destination.stat().st_size > MAX_TILE_BYTES:
                    raise ValueError("existing tile exceeds the permitted size")
                verify_bytes(destination.read_bytes(), tile, manifest["tile_size"])
                if not args.refetch:
                    print(f"Verified {tile['path']}")
                    continue
            elif args.verify:
                raise ValueError("tile is missing")
            data = fetch(tile)
            verify_bytes(data, tile, manifest["tile_size"])
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=".tile-", delete=False) as output:
                    temporary = Path(output.name)
                    output.write(data)
                temporary.replace(destination)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            print(f"Restored {tile['path']}")
        except (OSError, ValueError) as error:
            failures.append(f"{tile.get('path', '<unknown>')}: {error}")
    for error in failures:
        print(error, file=sys.stderr)
    if failures:
        return 1
    print(f"Verified {len(manifest['tiles'])} historical satellite tiles; source: {manifest['source']}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError) as error:
        print(f"Imagery verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)
