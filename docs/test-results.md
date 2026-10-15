# Verification results

Verified on October 15, 2026 for mission console 0.2.0. All tests exercise explicitly simulated vehicles; none operates physical hardware.

## Reproducible automated check

```bash
./scripts/verify.sh
```

This checks vendored source and all nine imagery tile hashes, rebuilds the native RoveComm C++ codec, and runs the complete Python unittest and Node.js geometry suites. The latest complete devcontainer run reported:

```text
Ran 87 tests
OK
Node.js: 5 tests passed; 0 failed, skipped or cancelled
```

All 87 Python tests and five Node.js tests executed and passed; no skips, expected failures, or disabled tests. The same suite passed in the cloud workspace. The pinned development image built successfully. The suite ran as non-root `vscode`, with `--network=none`, after copying source into a fresh disposable container and rebuilding the native codec using g++ 12. Container geometry checks used Node.js 18.20.4. Local cloud workspace builds use Python 3.12.14 / g++ 14.2. Both use the same source and verifier. Only known upstream unused-local-variable compiler warnings were emitted; vendored code was not changed to suppress them. The verifier also checks the five preserved Anatomy kit/license files and all nine historical imagery tiles.

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
| `test_imagery.py`, `test_geoview.cjs` | Original tile integrity/dimensions, offline bundle verification, constrained HTTP asset routes, known XYZ tile alignment, coordinate round trips, invalid/polar/outside-coverage handling, and invalid manifest rejection |
| `test_codec.py` | Native RoveComm pack/unpack, known wire bytes, network byte order, empty/max binary payloads, native buffer bounds, malformed/truncated/padded/wrong-field packets |
| `test_vehicle.py` | HMAC tamper rejection, strict schema, local window/lease expiry, duplicate and reordered command handling, fresh STOP exception, boot/session retirement, stopped package mutations, drone landing/phase/flight locks, conservative assistance/route manual rejection, onboard completion and visited-route recovery |
| `test_packages.py` | Out-of-order and interrupted chunk resume, idempotent duplicates, hash corruption rejection, immutable IDs, canonical JSON, CRS/units/coordinate limits, store bounds, distinct validation/activation |
| `test_c2_state.py` | STOP admission under saturation, safe automatic session synchronization when full, ACK endpoint matching, retired/reordered telemetry rejection, exact manual-claim ACK lease projection and unchanged receiver expiry |
| `test_link.py` | Loss, delay, jitter, duplication, reordering, full disconnection, telemetry-only failure, bounded bulk queue, essential control priority and invalid configuration |
| `test_http_security.py` | Host/Origin checks, exact Codespaces hostname, CSRF/content-type requirements, bounded/nonfinite input and response security headers |
| `test_end_to_end.py` | Real independent C2/rover/drone processes over HTTP and authenticated UDP: ACK/telemetry, lost ACK timeout, telemetry-only stale rejection, delay/jitter/duplicate/reordered transport, C2/rover/drone restarts, and demo CLI |
| `test_transfer_flow.py` | Drone survey → C2 review → transfer → acceptance → activation → route; flight lock; onboard execution through disconnection; lost final ACK recovered from receiver cache; corruption timeout then explicit retransfer; STOP completion during bulk traffic |
| `test_health.py` | Authenticated independent-process health telemetry, fault injection, electrical supply dependencies, concurrent channel alarms, power loss versus sensor loss, stale/unconfirmed faults, acknowledgment without recovery, malformed observations, HTTP assets and CSRF protection |

The loss tests distinguish send failures from lost acknowledgements. Fresh telemetry does not make a lost command ACK successful. An accepted autonomous command completes onboard during disconnection, and C2 only reports completion after a matching actual ACK is retrieved. Simulator restarts generate new identities and do not resume movement/flight automatically.

## Browser validation

Chromium with Playwright exercised the running dashboard against real local services: manual lease acquisition/pulse/expiry; drone takeoff, survey and landing; reviewed package transfer, acceptance and explicit activation; route completion; return to delivery mode; injected disconnection and recovery; failed HTTP polling and control disabling. No JavaScript errors were observed.

Desktop/laptop/tablet/phone layouts were inspected at widths 1440, 1024, 768, 390 and 320 px without horizontal overflow. Holding/repeating Enter did not generate repeated motion pulses. A focused browser check verified the official Q&A 21 guard: autonomous/recovery motion and stale state lock new review/import/transfer/activation while preserving read-only package inspection, STOP and recovery. Browser checks require an installed Chromium/Playwright setup and are not included in the dependency-free unit-test command. The same flows can be repeated with the README demonstration steps.

The historical satellite update was checked at desktop (1440), laptop (1024), and phone (390) widths with no horizontal overflow, external runtime requests or JavaScript errors. All nine tiles appeared in both map views. Checks covered pan/zoom/reset, keyboard navigation and tabs, disconnected camera messaging, stale/outside-coverage positions, and missing imagery while telemetry remains usable. Imagery is nominal 10 m sampling from 2016; zooming does not create additional detail.

## Earlier interface verification — commit 3b7b7fc

The updated interface passed all 68 Python tests and five JavaScript geometry
tests in the cloud workspace. The optional browser check is reproducible with
`python3 scripts/check_ui.py --screenshots /tmp/ncc-ui` when Python Playwright and
Chromium are installed. It starts a separate supervisor and temporary runtime,
then stops its own processes on completion or failure.

The browser check passed all four workspaces at 1440, 1024, 768, 390 and 320 px
without horizontal overflow. It exercised keyboard tabs, browser history,
workspace restoration after reload, the skip link, hidden-control focus behavior,
all nine local imagery tiles in each map, pan/zoom/reset, and disconnected camera
messaging. The real simulated workflow covered manual pulse expiry, software
STOP, drone survey, review, transfer, separate activation, and a 40-waypoint route.
Autonomous and stale package locks remained effective through an injected link
outage and reconnection. Missing imagery and HTTP failure states were also
checked. No JavaScript errors or external runtime requests occurred.

This section records the earlier four-workspace interface. The following checks
apply to its replacement, mission console 0.2.0.

## Rover engineering monitor — October 15, 2026

The replacement five-workspace console passed `python3 scripts/check_ui.py
--screenshots /tmp/ncc-ui` at 1440, 1024, 768, 390 and 320 px. Keyboard navigation,
browser history, reload, hidden controls, nine imagery tiles per map, attribution,
pan/zoom/reset, disconnected camera status, and missing-imagery fallback passed.
The live simulator workflow passed manual pulse/STOP, drone survey, separate
transfer/activation, route completion, Q21 package locks, disconnection recovery
and HTTP-failure control disabling. There were no JavaScript errors or external
runtime requests.

The manual-control regression starts with an explicit claim followed by a pulse
that acquires a new lease. The pulse now uses its own completed claim's ACK token,
even when telemetry still shows the older lease. Two C2 regressions verify the
exact result correlation and continued rejection after receiver-local expiry.
Neither the 0.8-second lease nor the receiver checks were weakened.

`python3 scripts/check_health_ui.py --screenshots /tmp/ncc-health-ui` runs against
isolated C2/rover/drone processes. Chromium verified component selection, a
drive overtemperature alarm, keyboard acknowledgment with stable focus, an
acknowledged fault remaining active, and sensor loss leaving that condition
unconfirmed rather than claiming recovery. Battery supply loss propagated to
dependent components. During disconnection, current readings became unavailable
and historical statistics stopped accumulating; reconnecting restored observed
measurements.

A deterministic browser replay additionally verified duplicate-sequence
suppression, exact minimum/maximum/sample mean, a 42-channel CSV register export,
statistics reset, and reset on a new rover boot. These are observed-sample
statistics, not a continuous durable telemetry recorder.

The illustrative rover cutaway contains 69 original solids generated with the
preserved Anatomy kit. The geometry audit reported zero issues. Separate dark
and light linework checks found zero floating ends among 250 checked endpoints.
The model and four-times-scale detail crops were inspected at desktop and phone
sizes. This establishes rendering quality, not dimensional fidelity to a rover
that has not yet been built.

REA research is recorded separately in [hwinfo-native-analysis.md](hwinfo-native-analysis.md).
Artifact hashes, resource decoding and selected native control paths were
verified; no Windows HWiNFO process, sensor driver, or physical vehicle was run.

## External verification and remaining limits

- GitHub API confirmed authenticated account `adrielsta`, target repository `adrielsta/COMMS.URC27.NCC`, and push permission. Commit identity was explicitly confirmed by the owner.
- Official URC pages and the linked current PDF were retrieved; the official PDF SHA-256 exactly matches the attachment. Applicable Q&A was reviewed; see `rules-source.md` for exact URLs and source scope.
- The checked-in Codespaces configuration was tested as a local Docker development container. No hosted Codespace was launched.
- GitHub Actions passed for the initial simulator commit. Consult the PR checks for the current branch revision; local results alone do not establish a remote run.
- No radios, video, LiDAR, flight controllers, real rover autonomy, physical E-stops, field GNSS, FAA/FCC compliance or physical vehicle tests were performed. Synthetic coordinates and route completion are not safe terrain planning or competition mission completion.
