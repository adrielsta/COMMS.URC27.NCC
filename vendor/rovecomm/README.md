# Vendored RoveComm codec

This directory contains the actual packet serializer and deserializer from
[upstream RoveComm_CPP](https://github.com/MissouriMRDT/RoveComm_CPP),
pinned to commit **bca1c255718804803615a4d9d435a12a2e2b6969** (2026-03-21).
The upstream project declares version 3.00.00; its wire protocol version is 3.

These files are copied **byte-for-byte, unmodified** from that revision:

- [src/RoveComm/RoveCommPacket.cpp](https://github.com/MissouriMRDT/RoveComm_CPP/blob/bca1c255718804803615a4d9d435a12a2e2b6969/src/RoveComm/RoveCommPacket.cpp)
- [src/RoveComm/RoveCommPacket.h](https://github.com/MissouriMRDT/RoveComm_CPP/blob/bca1c255718804803615a4d9d435a12a2e2b6969/src/RoveComm/RoveCommPacket.h)
- [src/RoveComm/RoveCommConsts.h](https://github.com/MissouriMRDT/RoveComm_CPP/blob/bca1c255718804803615a4d9d435a12a2e2b6969/src/RoveComm/RoveCommConsts.h)
- [LICENSE](https://github.com/MissouriMRDT/RoveComm_CPP/blob/bca1c255718804803615a4d9d435a12a2e2b6969/LICENSE)

The upstream MIT license is retained in `LICENSE`. Source file copyright
notices remain intact.

`RoveCommManifest.h` is a **generated compatibility header**, not a copied
upstream file. Upstream gitignores the generated full header. Our header wraps
the exact `DataTypes` enumeration emitted by `insert_datatypes_enum()` in the
same commit's [tools/RoveComm/parser.py](https://github.com/MissouriMRDT/RoveComm_CPP/blob/bca1c255718804803615a4d9d435a12a2e2b6969/tools/RoveComm/parser.py#L146-L163).
It supplies only what the codec needs. No board addresses, command assignments,
or content from the separate RoveComm_Base repository are copied; that inspected
repository has no license file.

`SHA256SUMS` records all five file hashes. Verify with:

```bash
(cd vendor/rovecomm && sha256sum --check SHA256SUMS)
```

## How the integration works

`native/rovecodec.cpp` invokes upstream `PackPacket<uint8_t>` and
`UnpackData<uint8_t>` through a C ABI. `comms/codec.py` calls those functions
with Python's standard-library `ctypes`. Build using:

```bash
bash scripts/build_codec.sh
python -m unittest discover -s tests -p test_codec.py -v
```

The resulting `.build/librovecodec.so` uses the existing Linux C++20 compiler,
with no fetched dependencies. This deliberately builds only the packet codec;
network sockets and application lifecycle behavior belong to the surrounding
application. Upstream's transport threads and its full manifest are not used.

## Compatibility limits

The v3 header is six bytes: version (uint8), data ID (big-endian uint16), count
(big-endian uint16), type (uint8). The bridge uses type UINT8_T (1), at most 8192
payload bytes, and **application data ID 60000**. That data ID is a private
simulation envelope chosen for this project, not an upstream-assigned hardware
command. Application messages inside it require both endpoints in this project.
Existing rover firmware does not acquire those application semantics merely
by receiving a syntactically valid RoveComm packet. Before any hardware use,
agree the real rover manifest, command mapping, endpoints, and safety behavior.

Upstream's generic decoder does not take a datagram length. The bridge checks
version, application data ID, type, element count, exact datagram length, and
the 8192-byte bound **before** invoking it. Output capacity is checked at the C
boundary and native exceptions are contained. Truncated, padded, oversized,
wrong-version, wrong-ID, and wrong-type datagrams are rejected.

The RoveComm header itself has no command acknowledgement, timestamp, session,
sequence number, or authentication fields. Any such behavior belongs to this
project's application payload and must be validated at both endpoints.
