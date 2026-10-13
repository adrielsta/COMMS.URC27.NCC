# Working on COMMS.URC27.NCC

This is a simulation communications system, not a physical vehicle controller. All current data products and modes must remain visibly labelled as simulation. Read `docs/requirements-matrix.md`, `docs/protocol.md`, and `docs/hardware-gaps.md` before changing safety or mission logic.

## Checkout and ownership

- Use the existing checkout; each cloud task is isolated. Do not create a Git worktree unless the user requests one.
- Preserve teammates' tracked and untracked work. Work on a feature branch; never force-push or push directly to `main`.
- Verify both commit identity and authenticated GitHub account before committing/pushing as requested by the user. Expected account is `adrielsta`; confirmed identity is `Adriel 1 <adriel28hen@gmail.com>`.
- Git read access does not establish push-account identity. Do not extract proxy credentials, print secrets, or assume an unset token means missing access.

## Project structure

- `comms/c2.py`: authenticated UDP application messages, HTTP API, request/result tracking, transfers.
- `comms/vehicle.py`: independent simulated rover/drone and receiver-local safety state.
- `comms/packages.py`: bounded package validation/storage and separate activation.
- `comms/protocol.py`: HMAC-authenticated envelope around actual native MRDT codec.
- `comms/link.py`: bounded priority scheduler and fault injection.
- `comms/supervisor.py`: three independent process lifecycles, logs and restarts.
- `web/`: dependency-free responsive dashboard, served only by C2.
- `vendor/mrdt/`: preserved third-party files; do not edit vendored source or hashes to make a check pass.
- `native/`, `comms/codec.py`: validate lengths and fields before entering upstream native codec.
- `tests/`: standard-library unittest suites, including real subprocess/UDP/HTTP workflows.

## Required verification

From the repository root:

```bash
./scripts/verify.sh
```

This verifies vendored hashes, builds the C++20 shared codec, and runs all Python tests. It needs Python 3.12+, g++, Bash and sha256sum; no pip/npm dependencies. Keep tests meaningful: message ordering/expiry, integrity, rule restrictions and observed process behavior matter more than implementation-mirroring assertions.

Start: `./scripts/start.sh`. Smoke demo in another terminal: `python3 scripts/demo.py`. Inspect `.runtime/*.log` for failures. Runtime keys/logs/PIDs and compiled output are ignored; never commit them. Use an isolated `COMMS_RUNTIME_DIR` and free HTTP/UDP ports when testing alongside an existing instance.

For UI changes, check laptop, desktop, and phone layouts and the real command/transfer workflow in a browser when available. Keep the Codespaces web port private. Never forward simulator UDP ports or weaken Host, Origin, CSRF or HMAC checks to make cloud access work.

## Safety and scope

- Never operate physical vehicles or buy cloud services as part of development.
- Software STOP is distinct from the physical E-stop that cuts all rover battery power.
- Use receiver-issued expiring tokens and receiver-local deadlines. Never compare monotonic clocks from separate processes/computers.
- Duplicate commands must not repeat side effects or extend manual authority; lost ACKs stay unconfirmed until an actual correlated result is received.
- Keep `requested`, `accepted`, `completed`, `rejected`, and `timeout` distinct. Never infer completion from telemetry alone.
- Rule changes need exact cited sections in the 2027 requirements matrix and appropriate tests. The supplied PDF is identified by SHA-256 in `docs/rules-source.md` and matches the verified official download. Official Q&A was checked through its last listed update of October 11, 2026; recheck it when changing mission policy.
- Do not claim real radio, sensing, safe terrain planning, flight control, autonomy mission completion or physical compliance. Document each remaining adapter explicitly.
