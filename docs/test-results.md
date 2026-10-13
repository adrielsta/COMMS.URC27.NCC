# Verification results

Verified on October 13, 2026. All tests exercise explicitly simulated vehicles; none operates physical hardware.

## Reproducible automated check

```bash
./scripts/verify.sh
```

This checks vendored source hashes, rebuilds the actual MRDT C++ codec, and runs the complete standard-library unittest suite. The latest complete devcontainer run reported:

```text
Ran 64 tests in 22.453s
OK
```

All 64 executed and passed; no skips, expected failures, or disabled tests. The same final suite passed in the cloud workspace in 20.964 seconds. The pinned development image built successfully. The suite ran as non-root `vscode`, with `--network=none`, after copying source into a fresh disposable container and rebuilding the native codec using g++ 12. Local cloud workspace builds use Python 3.12.14 / g++ 14.2. Both use the same source and verifier. Only known upstream unused-local-variable compiler warnings were emitted; vendored code was not changed to suppress them.

The final transfer regression suite was additionally repeated twice inside the offline container: two tests passed in 8.985 seconds, then two passed in 8.969 seconds. These runs verify the corrected priority-ordering case in which STOP overtakes bulk traffic. Control sequences remain strict; independent chunk/report handling no longer rejects valid uploads because essential control arrived first.

The tested Dockerfile pins `python:3.12.10-bookworm@sha256:91487c05f87617b9d1165274c07a9b0040dfef21a855b5b418a0ebc6aa26c5de`. Image build used normal apt signature/hash verification; runtime tests required no external connectivity. Local build-time proxy hostname resolution was supplied to Docker from the environment without embedding credentials or weakening TLS/signature validation.

After building the devcontainer image as `comms-urc27-dev:local`, reproduce the offline verification from the repository root:

```bash
set -o pipefail
tar --exclude=__pycache__ -cf - comms native scripts tests vendor web |
  docker run --rm --interactive --network=none --user vscode --workdir /tmp \
    comms-urc27-dev:local bash -c \
    'mkdir source && tar -xf - -C source && cd source && ./scripts/verify.sh'
```

## Covered behaviors

| Suite | Evidence |
| --- | --- |
| `test_codec.py` | Actual native MRDT pack/unpack, known wire bytes, network byte order, empty/max binary payloads, native buffer bounds, malformed/truncated/padded/wrong-field packets |
| `test_vehicle.py` | HMAC tamper rejection, strict schema, local window/lease expiry, duplicate and reordered command handling, fresh STOP exception, boot/session retirement, stopped package mutations, drone landing/phase/flight locks, conservative assistance/route manual rejection, onboard completion and visited-route recovery |
| `test_packages.py` | Out-of-order and interrupted chunk resume, idempotent duplicates, hash corruption rejection, immutable IDs, canonical JSON, CRS/units/coordinate limits, store bounds, distinct validation/activation |
| `test_c2_state.py` | STOP admission under saturation, safe automatic session synchronization when full, ACK endpoint matching, retired/reordered telemetry rejection |
| `test_link.py` | Loss, delay, jitter, duplication, reordering, full disconnection, telemetry-only failure, bounded bulk queue, essential control priority and invalid configuration |
| `test_http_security.py` | Host/Origin checks, exact Codespaces hostname, CSRF/content-type requirements, bounded/nonfinite input and response security headers |
| `test_end_to_end.py` | Real independent C2/rover/drone processes over HTTP and authenticated UDP: ACK/telemetry, lost ACK timeout, telemetry-only stale rejection, delay/jitter/duplicate/reordered transport, C2/rover/drone restarts, and demo CLI |
| `test_transfer_flow.py` | Drone survey → C2 review → transfer → acceptance → activation → route; flight lock; onboard execution through disconnection; lost final ACK recovered from receiver cache; corruption timeout then explicit retransfer; STOP completion during bulk traffic |

The loss tests distinguish send failures from lost acknowledgements. Fresh telemetry does not make a lost command ACK successful. An accepted autonomous command completes onboard during disconnection, and C2 only reports completion after a matching actual ACK is retrieved. Simulator restarts generate new identities and do not resume movement/flight automatically.

## Browser validation

Chromium with Playwright exercised the running dashboard against real local services: manual lease acquisition/pulse/expiry; drone takeoff, survey and landing; reviewed package transfer, acceptance and explicit activation; route completion; return to delivery mode; injected disconnection and recovery; failed HTTP polling and control disabling. No JavaScript errors were observed.

Desktop/laptop/tablet/phone layouts were inspected at widths 1440, 1024, 768, 390 and 320 px without horizontal overflow. Holding/repeating Enter did not generate repeated motion pulses. A focused browser check verified the official Q&A 21 guard: autonomous/recovery motion and stale state lock new review/import/transfer/activation while preserving read-only package inspection, STOP and recovery. Browser checks require an installed Chromium/Playwright setup and are not included in the dependency-free unit-test command. The same flows can be repeated with the README demonstration steps.

## External verification and remaining limits

- GitHub API confirmed authenticated account `adrielsta`, target repository `adrielsta/COMMS.URC27.NCC`, and push permission. Commit identity was explicitly confirmed by the owner.
- Official URC pages and the linked current PDF were retrieved; the official PDF SHA-256 exactly matches the attachment. Applicable Q&A was reviewed; see `rules-source.md` for exact URLs and source scope.
- The checked-in Codespaces configuration was tested as a local Docker development container. No hosted Codespace was launched.
- GitHub Actions configuration is included. Local results do not establish a remote Actions run; consult the PR checks for remote status.
- No radios, video, LiDAR, flight controllers, real rover autonomy, physical E-stops, field GNSS, FAA/FCC compliance or physical vehicle tests were performed. Synthetic coordinates and route completion are not safe terrain planning or competition mission completion.
