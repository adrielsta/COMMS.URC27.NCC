# Rover health console: source research and design rationale

Research checked on 2026-10-15. The console draws operational patterns from public NASA software documentation. It is an independent student rover project; it is not a NASA product or a certified flight system. These references inform the design and do not establish that a hardware subsystem works.

## Sources actually inspected

The files below were read through GitHub's HTTPS API. Links pin the exact revision inspected, so later upstream edits do not change this record. The rendered documentation sites at `nasa.github.io`, `fprime.jpl.nasa.gov`, and the attempted JPL robotics page were unavailable through this environment's network proxy (HTTP 403); findings here come from the accessible official repositories.

| Source | Observed behavior or guidance | Application to this console |
| --- | --- | --- |
| [Open MCT overview](https://github.com/nasa/openmct/blob/e09bfaf47856b2b7ae2ea74334800b26fd27a41e/README.md) | Open MCT is a telemetry visualization framework used for spacecraft data analysis and experimental rover planning/operations. Its object model organizes meaningful telemetry objects into a hierarchy. | Organize the interface around the rover, its subsystems, and measured channels. A subsystem selection should lead directly to its readings and relevant events. |
| [Open MCT telemetry API](https://github.com/nasa/openmct/blob/e09bfaf47856b2b7ae2ea74334800b26fd27a41e/API.md#telemetry-api) | Metadata names channels, units, formats, and time fields. Historical queries and live subscriptions are separate provider functions. A common time system synchronizes views; requested history is time ordered. | Display engineering units and timestamps, distinguish live monitoring from history, and align trends and events to the same time axis. Preserve the source time separately from ground receipt time. |
| [Open MCT example staleness provider](https://github.com/nasa/openmct/blob/e09bfaf47856b2b7ae2ea74334800b26fd27a41e/example/exampleStalenessProvider/ExampleStalenessProvider.js) | Staleness is evaluated explicitly from the latest telemetry timestamp and a configurable interval, separately from the measurement value. | A last known good voltage must become stale when samples stop. Connection status and individual sensor freshness are distinct. The example's three-second interval is an example, not a universal hardware requirement. |
| [Open MCT example limit provider](https://github.com/nasa/openmct/blob/e09bfaf47856b2b7ae2ea74334800b26fd27a41e/example/generator/SinewaveLimitProvider.js) | Per-channel evaluators determine low/high limit violations and their severity. The example supplies named limits for plots and evaluations. | Show the limit and actual measured value next to an anomaly. Use explicit warning/fault labels alongside color. Simulator values and limits are examples pending actual electrical/thermal ratings. |
| [Open MCT example acknowledged events](https://github.com/nasa/openmct/blob/e09bfaf47856b2b7ae2ea74334800b26fd27a41e/example/eventGenerator/EventWithAcknowledgeTelemetryProvider.js) | The example retains a message identifier while producing a later event with acknowledgement metadata. | Keep acknowledgement as a separate operator state tied to the original occurrence. Acknowledging an alarm must not repair, clear, or recolor an active equipment fault as healthy. This lifecycle is our design decision; the example does not specify a full alarm-management policy. |
| [Open MCT plots](https://github.com/nasa/openmct/blob/e09bfaf47856b2b7ae2ea74334800b26fd27a41e/src/plugins/plot/README.md) | Telemetry can be displayed as individual, overlay, or stacked plots. | Put a selected subsystem's recent measurements beside the anatomy view. Preserve gaps when data is missing; do not animate synthetic history as if it had been received. |
| [F Prime telemetry-channel reference](https://github.com/nasa/fprime/blob/d32863dd63952d1085890cc69c1b25ea6edb2257/docs/reference/system-functional/telemetry-chan.md) | Each telemetry value has a channel ID, typed value, and timestamp. Channels can be emitted always or on change. Numeric limits are defined in the dictionary and evaluated by the ground system. A delayed downlink can carry stale data. | Define a stable channel dictionary and verify types/units at ingestion. Assess age of measurements, not just arrival of a packet. An on-change channel needs an explicit freshness/heartbeat contract. |
| [F Prime health-checking pattern](https://github.com/nasa/fprime/blob/d32863dd63952d1085890cc69c1b25ea6edb2257/docs/user-manual/design-patterns/health-checking.md) and [Health component specification](https://github.com/nasa/fprime/blob/d32863dd63952d1085890cc69c1b25ea6edb2257/Svc/Health/docs/sdd.md) | Active software components are pinged on their own execution threads. Per-component timeouts produce warning and fatal events. The service can drive a watchdog while checks pass. A fatal response is chosen by the deployment and may reset/abort software. | Track each critical device/process independently. A working radio does not prove the motor controller is responsive. A display may report a timeout, but any real watchdog or shutdown action must run locally on validated vehicle hardware; the browser is not that watchdog. |
| [F Prime event-management reference](https://github.com/nasa/fprime/blob/d32863dd63952d1085890cc69c1b25ea6edb2257/docs/reference/system-functional/event-management.md) | Events carry ID, severity, timestamp, and arguments. Event categories distinguish faults, warnings, commands, and normal activity. Count/time throttles prevent repeated events flooding the log. | Maintain a bounded event history with severity and occurrence identity. Record state transitions rather than adding the same fault on every refresh. Keep command outcomes separate from health alarms. |

## Operational layout decisions

The mission view should answer four questions in a stable order: Is telemetry current? Which subsystem needs attention? What evidence explains it? What operation is currently underway?

- A persistent header carries the actual connection state, source mode, vehicle session, and age of the last received sample. Mission time is not a decorative countdown.
- A large subsystem anatomy diagram anchors the page. Selecting a component also selects its measurements, dependencies, trend, and alarms. Keyboard-accessible controls provide the same selection as diagram regions.
- Power connections represent configured dependencies. A highlighted downstream component means a reported fault or loss of evidence, not an unmeasured electrical diagnosis.
- A compact measurement table shows channel, value, unit, sample age, and state. Unknown values are a visible dash or `Unknown`, never zero or green.
- An alarm panel keeps active issues visible until the condition clears. Normal activity belongs in an event history rather than competing with faults for attention.
- Quiet dark surfaces, thin structural rules, aligned numeric columns, and restrained status colors support prolonged monitoring. Those are local design choices, not a claim that a specific NASA control room uses this exact theme.

Avoid a single invented “health percentage.” A battery state-of-charge measurement has a defined meaning; a percentage assembled from unrelated device statuses does not.

## Health state and alarm semantics

Transport, measurement validity, operating mode, and limit state are separate facts. They must not collapse into a single optimistic status.

| Observation | Honest display | What it does not establish |
| --- | --- | --- |
| Fresh valid measurement inside configured limits | Nominal for that measured channel | All functions of that component work |
| Fresh measurement outside a warning/fault threshold | Warning/fault with value and crossed limit | The cause is known |
| Sample exceeds its expected reporting interval | Stale, with last value and age | The component is electrically off |
| No supported sensor or adapter | Not instrumented / no data | A zero measurement or a healthy device |
| Fresh contactor/breaker feedback reports open | Off / isolated, with feedback source | Every downstream energy store is de-energized |
| Critical software heartbeat times out | Device/process unavailable | Whether the cause is power, software, or communications |
| Upstream supply fault plus downstream missing telemetry | Upstream fault and downstream unknown/unavailable | Every downstream device has independently failed |

Acknowledgement records that an operator saw a specific occurrence. It does not clear the condition. A new occurrence after recovery must be independently visible, even if an earlier occurrence was acknowledged. Clearing requires fresh evidence that the condition recovered; missing data cannot clear a measured fault. Lost contact should mark the evidence stale while preserving the last known fault/history.

For real equipment, thresholds, debounce periods, hysteresis, reporting intervals, and alarm persistence must come from the actual components, sensor accuracy, failure analysis, and bench measurements. No numeric example from a simulator or upstream example file is a hardware operating limit.

## Measurements needed to answer “is there power everywhere?”

The software can expose the measurement contract before the rover is built. Physical confidence requires sensors and feedback at the relevant locations. This table is an integration plan, not a statement that the listed instruments are connected.

| Subsystem | Useful measurements and feedback | Dependency / diagnostic use |
| --- | --- | --- |
| Battery / battery-management system | Pack voltage, pack current, state of charge with its estimation source, cell minimum/maximum voltage, temperatures, BMS fault codes | Distinguish low energy, voltage sag, temperature limits, and BMS protection. Pack voltage alone cannot establish usable capacity. |
| Main distribution / contactor | Voltage before and after isolation, current, actual contactor feedback, fuse/breaker status where instrumented | Compare commanded switch state with physical feedback. Distinguish a supply failure from a downstream branch failure. |
| Regulated rails and branch circuits | Per-rail voltage/current, regulator temperature/status, branch protection state | A healthy battery can coexist with a failed 12 V or 5 V branch. Instrument the load-side rail rather than assuming its presence. |
| Drive controllers and motors | Controller bus voltage, phase or bus current as identified, controller/motor temperature, commanded/measured wheel speed, controller fault words | Separate “controller alive” from “wheel responded.” Interpret speed mismatch against command, load, and mechanical state. |
| Compute and control | Process heartbeat/session, CPU temperature/load, memory pressure, controller reset cause, watchdog state | Differentiate a restarted application, stalled control loop, and a lost network path. OS telemetry does not prove control-loop correctness. |
| Communications | Receiver-local last packet age, sequence/loss counters, radio-reported signal/link quality, measured throughput/round-trip statistics | Keep RF measurements separate from application acknowledgement delays. Do not invent RSSI for a simulated UDP link. |
| Position and navigation | GNSS fix type, reported accuracy, position timestamp, IMU health, localization validity | A changing coordinate is not evidence of an accurate solution. Mission controls should use the validity reported by a real localization adapter. |
| Manipulator and payload | Rail voltage/current, joint temperatures and positions, driver faults, tool/payload presence feedback | Expose branch faults without suggesting that a responsive rover base proves arm or instrument health. |
| Cameras and other sensors | Device heartbeat, capture timestamp/frame age, stream state, device error/status | “Network connected” and “receiving current camera frames” are separate conditions. |

A future hardware adapter should map measured values into the same channel IDs used by the console, explicitly identify hardware versus simulation, carry device session/sequence and timestamps, and report invalid/unavailable values as such. Ingestion must reject malformed values and incompatible units. Only fresh authenticated device data can replace the simulation source label. Hardware is not connected by changing the label or loading a visual model.

An engineering anatomy view is a schematic until the team's actual geometry, component inventory, wiring, sensor placement, and channel mapping are supplied. Visual node positions do not claim dimensionally accurate CAD or an as-built wiring diagram.

## HWiNFO sensor-monitoring reference

The user also requested HWiNFO as a reference. Direct HTTPS access to the [vendor home page](https://www.hwinfo.com/) and [software overview](https://www.hwinfo.com/about-software/) returned proxy HTTP 403, including a retry after adding the domains to the saved environment configuration. The following accessible material was inspected instead:

- Rainmeter's [Using HWiNFO with Rainmeter](https://github.com/rainmeter/rainmeter-docs/blob/dc9bd8d53fb8b2e9bb968fefa177c652cd341a89/source/tips/hwinfo.html) integration guide. The guide states that HWiNFO author Martin Malik worked with Rainmeter on sensor export. It documents top-level sensor names, individual measurement labels, formatted values with units, and raw numeric values. It describes a default two-second polling interval in that version and distinct Current, Minimum, Maximum, and Average statistics. This is Rainmeter's integration documentation, not a current HWiNFO vendor manual.
- The guide's actual [HWiNFO64 v7.01-4404 Sensor Status screenshot](https://github.com/rainmeter/rainmeter-docs/blob/dc9bd8d53fb8b2e9bb968fefa177c652cd341a89/source/tips/img/hwinfo/HWiNFO2.png) was downloaded and visually inspected. It shows compact alternating rows, device groups such as System and CPU, columns **Sensor / Current / Minimum / Maximum / Average**, units in the measurements, and an elapsed timer plus clock/logging controls at the bottom. These are visible observations of that screenshot; tool behavior cannot be established from an icon alone.
- The maintained community [HWiNFO Stream Deck integration](https://github.com/moeilijk/hwinfo-streamdeck/blob/b3b1e9de39fcc3922dde5ef22f5564020f5dcb34/README.md) documents a Windows/shared-memory bridge, unavailable-source handling, sensor graphs, and thresholds. It explicitly distinguishes plugin behavior from the HWiNFO application. It is useful integration context and is not a vendor guarantee or a dependency of this rover software.

This research did not independently verify a NASA deployment or endorsement of HWiNFO. No such endorsement is used to justify this design.

The directly useful pattern is a grouped engineering sensor table beside the physical subsystem view. The rover adaptation should preserve HWiNFO's useful density and numerical comparability while adding the source/freshness information required by a remote radio link:

| Element | Rover-console decision |
| --- | --- |
| Sensor grouping | Group channels by the component or power branch that actually produces them; include stable channel IDs to disambiguate repeated labels such as Temperature. |
| Current | Display the latest valid, fresh received sample. Show `Unknown` or a dash when unavailable; a stale last value may remain visible only with its age and stale label. |
| Minimum / Maximum / Average | Accumulate only newly received, valid samples since the visible statistics reset/session start. Minimum and maximum are observed extrema. Average is an arithmetic **sample mean**, not a time-weighted average; identify it accordingly. Repeated browser polls of the same device sample must not increase counts. |
| Reset statistics | Reset the aggregates and their elapsed window. This action must not acknowledge an alarm, remove an active condition, restart hardware, or erase command outcomes. |
| Missing/invalid measurements | Exclude them from statistics. Do not enter zero, interpolate an apparent measurement, or keep stale data labelled as Current. Historical extrema remain historical until reset. |
| Trends and logging | Plot or export received values with timestamps, units, source/session identity, and quality. Logging should make start/stop state and its time range explicit. A CSV export or browser trace is not an onboard recorder unless a real recorder is implemented. |

HWiNFO-inspired presentation does not mean HWiNFO is installed in the Linux Codespace or connected to the rover. A Windows PC hardware monitor cannot automatically provide battery-branch voltages, fuse feedback, controller temperatures, or wheel status that the rover does not instrument. The hardware contract above remains necessary.

### Release and interface evidence for further analysis

Microsoft's public WinGet repository provides independently accessible packaging metadata for HWiNFO. The [8.54 installer manifest](https://github.com/microsoft/winget-pkgs/blob/e7187346f65f096be300c0b78e208685aeb918a0/manifests/r/REALiX/HWiNFO/8.54/REALiX.HWiNFO.installer.yaml) lists release date 2026-09-30, an Inno installer for x64/arm64, machine scope, and self-elevation. Its vendor download URL is `https://www.hwinfo.com/files/hwi64_854.exe`; its recorded SHA-256 is `16281EC83A69A720BEAC8E2A1DAD606FB2EAF4757BB02C7752B72EE2C26EE243`. The manifest's [locale metadata](https://github.com/microsoft/winget-pkgs/blob/e7187346f65f096be300c0b78e208685aeb918a0/manifests/r/REALiX/HWiNFO/8.54/REALiX.HWiNFO.locale.en-US.yaml) names the publisher as Martin Malik, REALiX s.r.o., marks the license Proprietary, and links the vendor [license PDF](https://www.hwinfo.com/files/license.pdf) and [version history](https://www.hwinfo.com/version-history/). These are metadata observations: they do not by themselves verify a downloaded executable, its Authenticode signature, or its license terms. No signing certificate information is present in the inspected manifest.

For interface research, the public community plugin's [shared-memory header](https://github.com/moeilijk/hwinfo-streamdeck/blob/b3b1e9de39fcc3922dde5ef22f5564020f5dcb34/internal/hwinfo/hwisenssm2.h), [reading accessors](https://github.com/moeilijk/hwinfo-streamdeck/blob/b3b1e9de39fcc3922dde5ef22f5564020f5dcb34/internal/hwinfo/reading.go), and [sensor accessors](https://github.com/moeilijk/hwinfo-streamdeck/blob/b3b1e9de39fcc3922dde5ef22f5564020f5dcb34/internal/hwinfo/sensor.go) were read. They are published third-party interoperability code, not an inspected official HWiNFO SDK or a claim that the proprietary application's internal implementation is known. No code from them is copied into the rover runtime.

The published schema provides useful concrete design evidence:

| Observed field/group | Meaning stated or implemented by that source | Rover design implication |
| --- | --- | --- |
| `dwSensorID`, `dwSensorInst`, `dwReadingID` | A sensor has an ID and instance; a reading is identified within its sensor. | Use stable compound identity. A display label is not a reliable sensor key. |
| `tReading`, `szUnit` | The header enumerates temperature, voltage, fan, current, power, clock, usage, and other readings; a unit accompanies each reading. | Keep the physical quantity and unit explicit. Never mix rail current with voltage because their display numbers happen to fit. |
| `Value`, `ValueMin`, `ValueMax`, `ValueAvg` | Four separate floating-point statistics appear in a reading. | Separate current data from accumulated statistics. The field names alone do not establish the upstream averaging algorithm, so this console documents its own sample mean. |
| `szLabelOrig`, `szLabelUser` and sensor-name equivalents | Original and user-visible labels are distinct. | Operators can use meaningful labels without changing stable channel identity. |
| `poll_time`, `dwPollingPeriod` | The shared-memory header carries the last polling time and reporting period. | Detect a stopped producer from sample time, not just a successful read of the same memory or HTTP payload. |
| `dwSignature`, version/revision, section offsets, element sizes/counts | The header distinguishes active/dead data and describes layout boundaries/versioning; its comments describe added UTF-8 fields in later layouts. | Validate source activity, version, ranges, and sizes before accepting telemetry. An old cached reading is not proof of a running sensor source. |

The header also identifies Windows named shared-memory and mutex objects. That is a local Windows interface, not a transport suitable for direct exposure across the rover radio link. A future adapter would need an explicit read-only bridge, version/bounds checks, measured timestamps, and the project's authenticated telemetry transport. This research does not install such a bridge or bypass vendor licensing restrictions.

The subsequent [native HWiNFO inspection](hwinfo-native-analysis.md) records the actual decompressed Windows application's reset, logging, and sensor-status code paths using REA/Ghidra, with exact target hashes, evidence IDs, and coverage limits.

## Verification priorities

Demonstrate fresh-to-stale behavior, an individual missing channel while the overall link stays live, an out-of-limit value, a fault that remains active after acknowledgement, recovery followed by a new occurrence, device restart/session change, upstream loss with uncertain downstream state, and bounded event/history storage. Trends should show only recorded samples with real timestamps and gaps. These behaviors matter more than cosmetic animation.

The existing physical E-stop and hardware integration requirements remain in [hardware-gaps.md](hardware-gaps.md). Displaying electrical telemetry does not itself provide isolation, over-current protection, or a local safety controller.
