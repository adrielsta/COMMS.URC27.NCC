"""Bounded, resumable transfers for explicitly synthetic waypoint packages."""
import base64
import binascii
import copy
import hashlib
import json
import math
import re

MAX_PACKAGE_BYTES = 64 * 1024
MAX_CHUNK_BYTES = 2048
MAX_PENDING = 2
MAX_STORED = 4
MAX_CHUNKS = 128
PACKAGE_FIELDS = {"schema_version", "package_id", "version", "crs", "units", "synthetic", "waypoints", "source"}


class PackageError(ValueError):
    pass


def _identifier(value):
    return isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value) is not None


def canonical_package(package):
    validate_package(package)
    return json.dumps(package, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def validate_package(package):
    if not isinstance(package, dict) or set(package) != PACKAGE_FIELDS:
        raise PackageError("unknown package schema or fields")
    if type(package["schema_version"]) is not int or package["schema_version"] != 1:
        raise PackageError("unsupported schema version")
    if not _identifier(package["package_id"]) or type(package["version"]) is not int or not 1 <= package["version"] <= 2**31 - 1:
        raise PackageError("invalid package identity/version")
    if package["crs"] != "EPSG:4326" or package["units"] != "degrees":
        raise PackageError("unsupported CRS or units")
    if package["synthetic"] is not True or package["source"] != "simulated-drone":
        raise PackageError("only labelled synthetic products are supported")
    points = package["waypoints"]
    if not isinstance(points, list) or not 1 <= len(points) <= 128:
        raise PackageError("waypoint count outside 1..128")
    for point in points:
        if not isinstance(point, dict) or set(point) != {"lat", "lon"}:
            raise PackageError("invalid waypoint schema")
        for name, low, high in (("lat", 38.410, 38.426), ("lon", -110.787, -110.767)):
            value = point[name]
            if type(value) not in (float, int) or not math.isfinite(value) or not low <= value <= high:
                raise PackageError("waypoint outside synthetic demonstration bounds")
    return package


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise PackageError("duplicate package JSON key")
        obj[key] = value
    return obj


class PackageStore:
    def __init__(self):
        self.pending = {}
        self.validated = {}
        self.active_package = None
        self.last_transfer = None

    def begin(self, metadata):
        if not isinstance(metadata, dict) or set(metadata) != {"package_id", "version", "size", "sha256", "chunks"}:
            raise PackageError("invalid transfer metadata fields")
        identity = metadata["package_id"]
        if not _identifier(identity) or type(metadata["version"]) is not int or not 1 <= metadata["version"] <= 2**31 - 1:
            raise PackageError("invalid package identity/version")
        if type(metadata["size"]) is not int or not 1 <= metadata["size"] <= MAX_PACKAGE_BYTES:
            raise PackageError("package size outside bounds")
        if not isinstance(metadata["sha256"], str) or not re.fullmatch(r"[a-f0-9]{64}", metadata["sha256"]):
            raise PackageError("invalid SHA-256")
        chunks = metadata["chunks"]
        if type(chunks) is not int or not 1 <= chunks <= MAX_CHUNKS or not chunks <= metadata["size"] <= chunks * MAX_CHUNK_BYTES:
            raise PackageError("invalid chunk count")
        if identity in self.pending:
            if self.pending[identity]["metadata"] != metadata:
                raise PackageError("conflicting metadata for existing transfer")
        elif identity in self.validated:
            existing = self.validated[identity]
            raw = canonical_package(existing)
            if existing["version"] != metadata["version"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"] or len(raw) != metadata["size"]:
                raise PackageError("package identity is immutable; use a new package_id")
            self.last_transfer = {"package_id": identity, "received": list(range(chunks)), "chunks": chunks, "status": "validated"}
            return copy.deepcopy(self.last_transfer)
        elif len(self.pending) >= MAX_PENDING or len(self.validated) >= MAX_STORED:
            raise PackageError("package store capacity reached")
        else:
            self.pending[identity] = {"metadata": copy.deepcopy(metadata), "chunks": {}}
        return self._progress(identity)

    def _progress(self, identity):
        entry = self.pending[identity]
        self.last_transfer = {"package_id": identity, "received": sorted(entry["chunks"]),
                              "chunks": entry["metadata"]["chunks"], "status": "uploading"}
        return copy.deepcopy(self.last_transfer)

    def chunk(self, args):
        if not isinstance(args, dict) or set(args) != {"package_id", "index", "data"}:
            raise PackageError("invalid chunk fields")
        identity, index = args["package_id"], args["index"]
        if not isinstance(identity, str) or identity not in self.pending:
            raise PackageError("no pending transfer")
        entry = self.pending[identity]
        if type(index) is not int or not 0 <= index < entry["metadata"]["chunks"]:
            raise PackageError("invalid chunk index")
        if not isinstance(args["data"], str) or len(args["data"]) > 4 * ((MAX_CHUNK_BYTES + 2) // 3):
            raise PackageError("encoded chunk exceeds limit")
        try:
            raw = base64.b64decode(args["data"], validate=True)
        except (ValueError, binascii.Error) as exc:
            raise PackageError("invalid chunk encoding") from exc
        if not 1 <= len(raw) <= MAX_CHUNK_BYTES:
            raise PackageError("chunk size outside bounds")
        previous = entry["chunks"].get(index)
        if previous is not None and previous != raw:
            raise PackageError("conflicting duplicate chunk")
        if previous is None:
            if sum(map(len, entry["chunks"].values())) + len(raw) > entry["metadata"]["size"]:
                raise PackageError("aggregate transfer size exceeds declaration")
            entry["chunks"][index] = raw
        return self._progress(identity)

    def commit(self, args):
        if not isinstance(args, dict) or set(args) != {"package_id"} or not isinstance(args["package_id"], str):
            raise PackageError("invalid commit fields")
        identity = args["package_id"]
        if identity in self.validated:
            return copy.deepcopy(self.validated[identity])
        if identity not in self.pending:
            raise PackageError("no pending transfer")
        if len(self.validated) >= MAX_STORED:
            raise PackageError("validated package store capacity reached")
        entry = self.pending[identity]
        metadata = entry["metadata"]
        if len(entry["chunks"]) != metadata["chunks"]:
            raise PackageError("transfer incomplete; resume missing chunks")
        raw = b"".join(entry["chunks"][index] for index in range(metadata["chunks"]))
        try:
            if len(raw) != metadata["size"] or hashlib.sha256(raw).hexdigest() != metadata["sha256"]:
                raise PackageError("package integrity check failed")
            package = json.loads(raw, object_pairs_hook=_unique_object)
            validate_package(package)
            if canonical_package(package) != raw:
                raise PackageError("package must use canonical JSON encoding")
            if package["package_id"] != identity or package["version"] != metadata["version"]:
                raise PackageError("package identity does not match metadata")
        except (ValueError, UnicodeError, RecursionError, TypeError) as exc:
            del self.pending[identity]
            self.last_transfer = {"package_id": identity, "received": [], "chunks": metadata["chunks"], "status": "rejected"}
            raise PackageError(str(exc)) from exc
        self.validated[identity] = package
        del self.pending[identity]
        self.last_transfer = {"package_id": identity, "received": list(range(metadata["chunks"])), "chunks": metadata["chunks"], "status": "validated"}
        return copy.deepcopy(package)

    def activate(self, package_id, stopped=True):
        if not stopped:
            raise PackageError("activation requires a stopped rover (1.e.iii)")
        if not isinstance(package_id, str) or package_id not in self.validated:
            raise PackageError("package has not been validated")
        self.active_package = package_id
        return copy.deepcopy(self.validated[package_id])

    def summaries(self):
        return [{"package_id": identity, "version": package["version"], "waypoint_count": len(package["waypoints"]),
                 "status": "active" if self.active_package == identity else "validated"}
                for identity, package in self.validated.items()]
