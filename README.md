# COMMS.URC27.NCC — URC 2027 communications

A runnable **simulation and communications development system**, using a native RoveComm C++ packet codec. C2, rover, and drone run in three separate processes. No radio, motors, flight controller, LiDAR, cameras, or physical E-stop are connected.

The governing source is the supplied *University Rover Challenge 2027 — Requirements and Guidelines*. The organiser-hosted PDF was verified byte-for-byte against the attachment, and official Q&A (last listed update October 11, 2026) was checked. See the [requirements matrix](docs/requirements-matrix.md), [source provenance](docs/rules-source.md), and [hardware gaps](docs/hardware-gaps.md).

## Quick start: GitHub Codespaces

1. Open this feature branch in a Codespace. The checked-in `.devcontainer` installs Python 3.12, a C++ compiler, and Node.js for tests, and builds the native codec. No Python or JavaScript package download is required.
2. Run:

   ```bash
   ./scripts/start.sh
   ```

3. Open dashboard port **8080** in the Codespaces Ports panel. Keep its visibility **Private**. Only this port is configured for forwarding; UDP simulator ports stay on loopback. Codespaces defaults new ports to private, but visibility is a platform setting: confirm it in the Ports panel, or run `gh codespace ports visibility 8080:private --codespace "$CODESPACE_NAME"` using your Codespaces account.
4. Verify from another terminal:

   ```bash
   ./scripts/verify.sh
   ```

`Ctrl-C` stops the supervisor and all three children. Runtime logs and the PID list are in ignored `.runtime/`. The supervisor restarts failed children with fresh process sessions and stops after repeated startup failures. Motion never resumes automatically after a vehicle or C2 process restart.

The container image is pinned by version and verified digest. Local Docker validation is recorded in [test results](docs/test-results.md); current remote checks are shown on the pull request. No hosted Codespace has been validated.

**Using Windows PowerShell:** run these commands in the Codespace's Bash terminal, from the repository folder. They are Linux shell scripts. For a local Windows checkout, open WSL2 with `wsl` from PowerShell, change to your checkout folder, install the prerequisites below, and run `./scripts/start.sh` there.

## Offline laptop development

On Linux or WSL2, install Python **3.12+**, `g++` with C++20 support, Bash, and `sha256sum` before going offline. Verification also requires **Node.js 18+**, included in the devcontainer. With these prerequisites and the checkout available, both commands above work with **no internet connection**. There is no hosted map dependency or runtime package installation. The dashboard is served on local port 8080 and includes bundled historical satellite imagery.

An already built devcontainer image can also be used offline. The original image build and OS package installation require internet access. Native binaries must be rebuilt for the target machine/architecture. macOS, Windows-native, ARM targets, actual radios, and vehicle computers have not been validated.

Field operation must be off-grid: no cloud or satellite internet may be required (rules §2.a.i and §2.c.i). This implementation supplies the offline development path and portable application protocol. Physical vehicle deployment requires the adapters and authenticated radio transport described in [hardware gaps](docs/hardware-gaps.md); the current simulator command sockets deliberately accept only localhost traffic.

## Satellite field view and drone view

The field map uses real **2016 Sentinel-2 imagery around MDRS, Utah**, stored locally with its attribution and license. Rover/drone markers and reviewed routes use their WGS 84 coordinates on a Web Mercator map. Drag or use arrow keys to pan, use the zoom buttons, and select **Reset view** to return. Positions outside the stored area are identified; stale positions remain visibly marked.

The separate **Drone view** follows the drone's reported position on the same satellite map. Its **Camera** tab reports that no camera is connected. Vehicle positions and survey products remain simulated; no video or physical drone adapter is connected.

The imagery has nominal 10 m source sampling and a 2016 mosaic date, so it provides historical geographic context rather than current obstacle or landing-site detail. No satellite internet or live satellite feed is used. URC §1.e.xiii encourages satellite imagery; §2.c.i prohibits satellite internet. See [imagery source, coverage and offline verification](docs/imagery-source.md) for the exact bounds, source, CC BY 4.0 license, and pinned tile hashes.

## Reproducible demonstrations

For a command → rover → ACK → telemetry demonstration, start the system and run:

```bash
python3 scripts/demo.py
```

It sends software STOP, verifies the rover's acknowledgement, and returns nonzero on rejection or timeout. It does not request motion.

For the synthetic survey-to-route workflow in the dashboard:

1. Leave both vehicles in **Delivery**, or select **Astronaut assistance**. Take off the simulated drone and generate a synthetic survey.
2. Load the survey into the review panel. Inspect its WGS 84 coordinates, version and synthetic label. Transfer it to the rover. **Accepted** means schema and SHA-256 validated; it does not activate the route.
3. Explicitly activate the accepted package while stopped. Land the simulated drone at its designated pad.
4. Set both vehicles to **Route finding**. The drone flight lock and fresh landing report must reach the rover before departure.
5. Start the route. The rover executes the supplied synthetic waypoints onboard. **Accepted** and **Completed** are separate acknowledgements.
6. Try fault profiles while watching freshness, command results, and diagnostics. A disconnected autonomous route can continue onboard; manual pulses always expire locally. After a restart, use explicit new commands.

The verifier runs this workflow across actual subprocesses, including lost completion ACK recovery, corrupted transfers, and STOP during a bulk transfer. It also tests interrupted chunk delivery/resume and SHA-256 rejection directly at the receiver. Re-submit the same reviewed package after a failed transfer to resume missing chunks; a receiver process restart clears volatile uploads and requires retransfer/review/activation. No map package is executable code.

## Controls and interpretation

- **Software STOP is not the physical E-stop.** The physical red push button must remove power from all rover batteries under §2.a.v. This application cannot do that.
- Modes and flight states are the last received vehicle states. Freshness is time since receipt on C2's own clock, not a synchronized measurement of sensor age. Acknowledgements are correlated separately; telemetry cannot prove a command completed.
- Manual movement is an explicit short pulse using a rover-issued 0.8-second lease. Retries and duplicate requests cannot extend it. A new pulse requires new authority.
- Route-finding and astronaut assistance block arbitrary manual driving; delivery and equipment servicing support manual pulses. The recovery command only traverses previously visited synthetic route points in reverse. Full manual recovery constrained to explored terrain, astronaut recognition/manipulation, and autonomous keyboard entry are not implemented.
- Drone surveying produces a labelled demonstration waypoint package, **not real LiDAR, an elevation map, obstacle detection, or safe terrain planning**.
- Fault controls affect both simulated message directions: loss, delay, jitter, duplication, reordering, full disconnection, telemetry-only failure and corrupted bulk frames. `ack_loss` is also available through the simulation API for deterministic tests.
- Histories, command queues, retries, transfers, package sizes, and payloads are bounded. Package storage is intentionally small (four validated packages); restart a simulator to reset a development session.

## Structure and attribution

| Path | Purpose |
| --- | --- |
| `comms/c2.py`, `web/` | HTTP dashboard, command tracking, review and transfer orchestration |
| `comms/vehicle.py` | Independent rover/drone state machines and UDP CLI |
| `comms/protocol.py`, `comms/link.py` | Authenticated session protocol and bounded fault scheduler |
| `comms/packages.py` | Resumable, integrity-checked synthetic package receiver |
| `vendor/rovecomm/`, `native/`, `comms/codec.py` | Pinned MIT-licensed RoveComm C++ codec and checked native bridge |
| `tests/`, `scripts/` | Unit, protocol, HTTP, independent-process tests and start/demo commands |
| `.devcontainer/`, `.github/workflows/` | Codespaces environment and build/test workflow |
| `docs/` | Architecture, protocol, rules, results and integration decisions |

`RoveComm_CPP` revision `bca1c255718804803615a4d9d435a12a2e2b6969` is preserved with its [MIT license](vendor/rovecomm/LICENSE), source hashes and [provenance](vendor/rovecomm/README.md). The native pack/unpack routines execute for every simulator datagram. This project does not claim that existing rover firmware understands the new application commands: data ID 60000 is a simulation-only envelope and requires a reviewed team manifest before hardware deployment. Python/Base repositories without an identified license were not copied.

Read [architecture](docs/architecture.md) and [protocol](docs/protocol.md) before adding an adapter.

## Troubleshooting

- **Compiler or native library missing:** run `./scripts/build_codec.sh`; it validates vendored hashes before compiling. An upstream unused-variable warning is expected; do not edit vendored sources to hide it.
- **No telemetry:** inspect `.runtime/c2.log`, `rover.log`, and `drone.log`. Check for port conflicts. Use `COMMS_HTTP_PORT=8081 COMMS_UDP_PORT=12150 ./scripts/start.sh` to select an HTTP port and a consecutive UDP trio. Update the private forwarded port when changing HTTP ports.
- **HTTP 403:** use the actual local dashboard Host or the exact Codespaces forwarded host. C2 derives the latter from `CODESPACE_NAME` and `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`. Do not disable Host/Origin or CSRF checks. C2 deliberately binds only `127.0.0.1`.
- **Control rejected:** wait for fresh telemetry and session reconciliation; check the receiver's reason in the command log. Route departure requires an activated package, stopped rover, and fresh designated-pad landing plus flight lock.
- **Leaving route-finding:** switch the stopped rover's mission first, wait for the report to reach the drone, then change the drone mission. The dashboard performs this sequence. This conservative lock prevents re-launch during route work.
- **Timeout/unconfirmed:** inspect fresh state; do not assume failure or repeat motion automatically. A lost ACK may mean the original command already executed.
- **Store full or failed transfer:** same package ID must retain identical content/version. Use a new ID for changed content. Resubmit an interrupted package, or restart the simulator to clear its volatile store.
- **GitHub account API/official rules blocked:** add `api.github.com`, `urc.marssociety.org`, and `www.marssociety.org` to environment networking. Git read success alone does not prove the authenticated push account.
