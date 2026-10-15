"""RoveComm v3 envelope using the vendored RoveComm C++ codec.

Data ID 60000 is this simulation application's private envelope. It does not
implement the upstream rover command manifest or imply firmware compatibility.
"""

from __future__ import annotations

import ctypes
from functools import lru_cache
from pathlib import Path

MAX_PAYLOAD = 8192
HEADER_SIZE = 6
MAX_PACKET = HEADER_SIZE + MAX_PAYLOAD
DATA_ID = 60000
PROTOCOL_VERSION = 3
DATA_TYPE = 1  # RoveComm UINT8_T


class CodecError(ValueError):
    """Input is not a supported application RoveComm packet or payload."""


@lru_cache(maxsize=1)
def _library() -> ctypes.CDLL:
    path = Path(__file__).resolve().parent.parent / ".build" / "librovecodec.so"
    try:
        library = ctypes.CDLL(str(path))
    except OSError as exc:
        raise RuntimeError(
            "RoveComm codec is unavailable. Run: bash scripts/build_codec.sh"
        ) from exc
    signature = [
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_uint8),
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    for name in ("rc_encode", "rc_decode"):
        function = getattr(library, name)
        function.argtypes = signature
        function.restype = ctypes.c_int
    return library


def _invoke(name: str, data: bytes, output_size: int) -> bytes:
    if not isinstance(data, bytes):
        raise TypeError("Codec input must be bytes")
    source = (ctypes.c_uint8 * max(1, len(data)))()
    if data:
        ctypes.memmove(source, data, len(data))
    output = (ctypes.c_uint8 * max(1, output_size))()
    written = ctypes.c_size_t()
    status = getattr(_library(), name)(
        source, len(data), output, output_size, ctypes.byref(written)
    )
    if status:
        if status == 5:
            raise RuntimeError("Native RoveComm codec failed")
        messages = {
            1: "Invalid codec argument",
            2: "Packet or payload exceeds the 8192-byte payload limit",
            3: "Invalid RoveComm packet: header, data ID, type, count, or length",
            4: "Codec output buffer is too small",
        }
        raise CodecError(messages.get(status, "Unknown native codec error"))
    return bytes(output[:written.value])


def encode(payload: bytes) -> bytes:
    """Encode up to 8192 application bytes into a RoveComm v3 packet."""
    if not isinstance(payload, bytes):
        raise TypeError("Codec input must be bytes")
    if len(payload) > MAX_PAYLOAD:
        raise CodecError("Payload exceeds the 8192-byte limit")
    return _invoke("rc_encode", payload, len(payload) + HEADER_SIZE)


def decode(packet: bytes) -> bytes:
    """Decode one complete packet, rejecting unsupported or malformed input."""
    if not isinstance(packet, bytes):
        raise TypeError("Codec input must be bytes")
    if len(packet) > MAX_PACKET:
        raise CodecError("Packet exceeds the 8192-byte payload limit")
    return _invoke("rc_decode", packet, MAX_PAYLOAD)
