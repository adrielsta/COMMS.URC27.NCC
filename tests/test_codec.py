"""Wire-format and hostile-input checks for the real MRDT native codec."""

import ctypes
from pathlib import Path
import random
import subprocess
import unittest

from comms.codec import (
    CodecError,
    MAX_PAYLOAD,
    _library,
    decode,
    encode,
)


class CodecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = Path(__file__).resolve().parents[1]
        library = root / ".build/librovecodec.so"
        sources = [root / "native/rovecodec.cpp", root / "scripts/build_codec.sh"]
        sources.extend((root / "vendor/mrdt").glob("*"))
        if not library.exists() or any(
            path.stat().st_mtime > library.stat().st_mtime for path in sources
        ):
            subprocess.run(["bash", "scripts/build_codec.sh"], cwd=root, check=True)

    def test_known_wire_bytes(self):
        # version=3; data ID=60000; count=2; type=UINT8_T; payload={}
        expected = bytes.fromhex("03 ea 60 00 02 01 7b 7d")
        self.assertEqual(encode(b"{}"), expected)
        self.assertEqual(decode(expected), b"{}")

    def test_round_trip_binary_empty_and_maximum(self):
        for payload in (b"", bytes(range(256)), b"x" * MAX_PAYLOAD):
            with self.subTest(size=len(payload)):
                self.assertEqual(decode(encode(payload)), payload)

    def test_count_uses_network_byte_order(self):
        packet = encode(bytes(range(256)) + b"x")
        self.assertEqual(packet[:6], bytes.fromhex("03 ea 60 01 01 01"))

    def test_all_truncations_and_extra_bytes_rejected(self):
        valid = encode(b"hello")
        for cut in range(len(valid)):
            with self.subTest(cut=cut):
                with self.assertRaises(CodecError):
                    decode(valid[:cut])
        with self.assertRaises(CodecError):
            decode(valid + b"\0")

    def test_invalid_header_fields_rejected(self):
        valid = encode(b"test")
        for offset, replacement in (
            (0, 0), (0, 2), (0, 255),  # protocol version
            (1, 0), (2, 0),  # application data ID
            (3, 0x20), (3, 0xFF), (4, 3), (4, 5),  # count
            (5, 0), (5, 6), (5, 255),  # unsupported payload types
        ):
            malformed = bytearray(valid)
            malformed[offset] = replacement
            with self.subTest(offset=offset, replacement=replacement):
                with self.assertRaises(CodecError):
                    decode(bytes(malformed))

    def test_oversize_rejected(self):
        with self.assertRaises(CodecError):
            encode(b"x" * (MAX_PAYLOAD + 1))
        with self.assertRaises(CodecError):
            decode(bytes.fromhex("03 ea 60 20 01 01") + b"x" * (MAX_PAYLOAD + 1))

    def test_non_bytes_rejected(self):
        for bad_input in ("text", None, bytearray(b"test"), 1):
            for operation in (encode, decode):
                with self.subTest(input=bad_input, operation=operation):
                    with self.assertRaises(TypeError):
                        operation(bad_input)

    def test_arbitrary_packets_are_rejected_without_native_crash(self):
        generator = random.Random(2027)
        for _ in range(300):
            packet = generator.randbytes(generator.randrange(0, 512))
            with self.assertRaises(CodecError):
                decode(packet)

    def test_native_boundary_checks_output_capacity_and_payload_limit(self):
        lib = _library()
        source = (ctypes.c_uint8 * 1)(42)
        output = (ctypes.c_uint8 * 7)(*[0xAA] * 7)
        written = ctypes.c_size_t(99)
        self.assertEqual(lib.rc_encode(source, 1, output, 6, ctypes.byref(written)), 4)
        self.assertEqual(written.value, 0)
        self.assertEqual(bytes(output), b"\xaa" * 7)
        self.assertEqual(
            lib.rc_encode(source, MAX_PAYLOAD + 1, output, 7, ctypes.byref(written)), 2
        )
        wire = encode(b"ab")
        source_packet = (ctypes.c_uint8 * len(wire)).from_buffer_copy(wire)
        self.assertEqual(
            lib.rc_decode(source_packet, len(wire), output, 1, ctypes.byref(written)), 4
        )
        self.assertEqual(written.value, 0)


if __name__ == "__main__":
    unittest.main()
