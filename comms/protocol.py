"""Authenticated application messages carried by the vendored RoveComm codec.

This schema is a team application protocol, not an upstream MRDT data manifest.
Neither timestamps from another process nor arrival time alone grant authority.
"""
import hashlib
import hmac
import json
import math

MAX_JSON_BYTES = 7800
MAX_BODY_BYTES = 7400
KINDS = {
    "command": {"kind", "vehicle", "boot_id", "session", "id", "seq", "window", "action", "args"},
    "telemetry": {"kind", "vehicle", "boot_id", "seq", "window", "state"},
    "ack": {"kind", "vehicle", "boot_id", "session", "id", "status", "reason"},
}


class ProtocolError(ValueError):
    pass


def _check_tree(value, depth=0):
    if depth > 12:
        raise ProtocolError("JSON nesting limit exceeded")
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, (int, float)):
        if abs(value) > 2**53 or not math.isfinite(value):
            raise ProtocolError("nonfinite or oversized number")
    elif isinstance(value, str):
        if len(value) > 6000:
            raise ProtocolError("string limit exceeded")
    elif isinstance(value, list):
        if len(value) > 256:
            raise ProtocolError("array limit exceeded")
        for item in value:
            _check_tree(item, depth + 1)
    elif isinstance(value, dict):
        if len(value) > 64 or any(not isinstance(k, str) or len(k) > 64 for k in value):
            raise ProtocolError("object limit exceeded")
        for item in value.values():
            _check_tree(item, depth + 1)
    else:
        raise ProtocolError("unsupported JSON value")


def canonical_json(value):
    _check_tree(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")


def _validate(body):
    if not isinstance(body, dict) or body.get("kind") not in KINDS:
        raise ProtocolError("unknown message schema")
    required = KINDS[body["kind"]]
    optional = {"state"} if body["kind"] == "ack" else set()
    if not required <= body.keys() or body.keys() - required - optional:
        raise ProtocolError("invalid message fields")
    if body["vehicle"] not in ("rover", "drone"):
        raise ProtocolError("unknown vehicle")
    for name in ("boot_id", "session", "id", "window", "action"):
        if name in body and (not isinstance(body[name], str) or not 1 <= len(body[name]) <= 128):
            raise ProtocolError("invalid " + name)
    if "seq" in body and (type(body["seq"]) is not int or not 0 <= body["seq"] <= 2**53):
        raise ProtocolError("invalid sequence")
    for name in ("args", "state"):
        if name in body and not isinstance(body[name], dict):
            raise ProtocolError("invalid " + name)
    if body["kind"] == "ack":
        if body["status"] not in ("accepted", "completed", "rejected"):
            raise ProtocolError("invalid ACK status")
        if not isinstance(body["reason"], str) or len(body["reason"]) > 512:
            raise ProtocolError("invalid ACK reason")
    _check_tree(body)


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolError("duplicate JSON key")
        result[key] = value
    return result


def encode_message(body, key):
    from .codec import encode
    if not isinstance(key, bytes) or len(key) < 32:
        raise ProtocolError("authentication key must contain at least 32 bytes")
    _validate(body)
    raw = canonical_json(body)
    if len(raw) > MAX_BODY_BYTES:
        raise ProtocolError("message exceeds size limit")
    envelope = canonical_json({"v": 1, "body": body, "mac": hmac.new(key, raw, hashlib.sha256).hexdigest()})
    if len(envelope) > MAX_JSON_BYTES:
        raise ProtocolError("envelope exceeds size limit")
    return encode(envelope)


def decode_message(packet, key):
    from .codec import decode
    if not isinstance(key, bytes) or len(key) < 32:
        raise ProtocolError("authentication key must contain at least 32 bytes")
    if not isinstance(packet, bytes) or len(packet) > 8192 + 32:
        raise ProtocolError("packet exceeds size limit")
    try:
        raw = decode(packet)
        if len(raw) > MAX_JSON_BYTES:
            raise ProtocolError("envelope exceeds size limit")
        envelope = json.loads(raw, object_pairs_hook=_object,
                              parse_constant=lambda _: (_ for _ in ()).throw(ProtocolError("nonfinite number")))
        if not isinstance(envelope, dict) or set(envelope) != {"v", "body", "mac"} or type(envelope["v"]) is not int or envelope["v"] != 1:
            raise ProtocolError("unknown envelope schema")
        body = envelope["body"]
        _validate(body)
        canonical = canonical_json(body)
        if len(canonical) > MAX_BODY_BYTES:
            raise ProtocolError("message exceeds size limit")
        mac = envelope["mac"]
        if not isinstance(mac, str) or len(mac) != 64 or not hmac.compare_digest(mac, hmac.new(key, canonical, hashlib.sha256).hexdigest()):
            raise ProtocolError("authentication failed")
        return body
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError) as exc:
        raise ProtocolError(str(exc)) from exc
