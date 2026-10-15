# HWiNFO investigation and rover adaptation

The selected target is **HWiNFO 8.54-6090 for Windows x64**. This investigation
uses REA 6.5.0, the shipped application, its bundled manual, and separately
identified interoperability references. The rover console is independently
implemented; it does not embed HWiNFO, its driver, its graphics, or recovered
proprietary code.

## Artifact identity

| Artifact | Provenance | SHA-256 |
| --- | --- | --- |
| `hwi64_854.exe` installer | [Vendor download](https://www.hwinfo.com/files/hwi64_854.exe), matched against [Microsoft WinGet's pinned manifest](https://github.com/microsoft/winget-pkgs/blob/e7187346f65f096be300c0b78e208685aeb918a0/manifests/r/REALiX/HWiNFO/8.54/REALiX.HWiNFO.installer.yaml) | `16281ec83a69a720beac8e2a1dad606fb2eaf4757bb02c7752b72ee2c26ee243` |
| `HWiNFO64.EXE` | Extracted from the verified installer with innoextract; application not executed | `e4ce0c85c4288fa7e8eb12ebeece99efff4d81e0b13de53f091daabc81a3c9d3` |
| `HWiNFO64.unpacked.exe` | Separate UPX-decompressed analysis copy; original preserved | `5ef21625978eb2d2f6906ad31b9817ce8235be80dca556404f1d83e4674e366a` |
| `HWiNFO Manual.pdf` | English manual bundled in the same installer | `e5e08cab30d16d149fd095e305e9b23f507159e3c0db84b1c7dd90d0f5ed3ce7` |

The private analysis workspace is `/workspace/scratch/hwinfo-research/`.
Tool/extraction/unpacking provenance and complete REA records are retained there.
These target binaries and manual are research inputs, not repository assets.
The default Windows executable is packed; its original entry point is an
unpacking stub. Native application conclusions must refer to the derived copy,
not confuse that stub or the installer with sensor processing.

REA/Ghidra also traced the actual reset and logging handlers, their Windows
message-map entries, and sensor tooltip/title paths. The
[native-analysis report](hwinfo-native-analysis.md) contains exact addresses,
Evidence IDs, observed instructions and unresolved calls. The reset handler
changes stored accumulation fields and the timer origin; logging has a separate
file-handle lifecycle. Neither conclusion relies only on control labels.

## Questions and evidence

| Question | Observed evidence | Rover behavior |
| --- | --- | --- |
| How are measurements organized? | Manual §10, pp. 38–39: hardware groups, optional subgroups, individual sensor readings. Sensor-window resources also contain the corresponding list and column controls. | Physical component identity and explicit units; Anatomy selection and the sensor register inspect the same reported component. |
| What do Current/Minimum/Maximum/Average mean? | Manual p. 39: Current is the last readout; minimum/maximum cover the observation window since opening/reset. Embedded settings describe a sample averaging interval, with zero meaning the whole runtime until user reset. This configuration text does not by itself prove the arithmetic implementation. | Current is shown only while valid and fresh. Minimum, maximum and sample mean use each observed health sequence once. The observation start and sample count are visible. |
| What happens when a sensor fails? | Manual p. 39: HWiNFO greys the last successfully read value. | Current becomes unavailable with an explicit unknown/stale label; historical statistics remain identified as history. Loss of a sensor does not prove loss of electrical power. |
| How are reads scheduled? | Manual pp. 39, 44: default global polling period 2000 ms; selected slow sensors can use a multiple of this period. This is documented behavior, not a Windows runtime capture. | The existing rover simulator publishes every 200 ms. Browser statistics count received samples, not timer ticks, and freshness expires independently of rendering. |
| What does reset affect? | Manual p. 39 and reset dialog/tooltip resources: reset minimum/maximum/average and the observation timer. | Reset browser statistics and graph history, without clearing vehicle faults, alarms, or command state. |
| How are graphs and logs exposed? | Manual pp. 41–42: per-sensor graph on double-click, reset and auto-fit; p. 39: start/stop CSV logging. | Selected-component channel trends with gaps for unavailable data and a CSV export of the observed sensor register. Continuous durable recording is a separate future feature. |
| How are alarms configured? | Manual pp. 49–50: above/below thresholds, minimum notification interval, successive samples and optional once-only notifications. Static alert dialog controls corroborate the configuration options. | Illustrative per-channel limits and a persistent fault annunciator. Acknowledgment records operator review; only fresh confirming telemetry resolves a condition. User-configurable debounce and notification policies are not claimed. |
| How do third-party consumers identify readings? | The separately cited public interoperability header exposes sensor ID/instance/reading ID, original/user labels, unit, typed values, statistics and polling metadata; see [research sources](health-research.md). | Stable component/channel identifiers, explicit unit/quality/source fields and a published rover schema. No HWiNFO shared-memory bridge is installed. |

Group aggregates require care: HWiNFO's manual p. 38 describes a subgroup's
Current value as the average of its member readings, rather than a historical
average. The rover view does not average incompatible voltages, temperatures,
or current rails into a fictitious overall health number. The power model
calculates bus current from load watts and supply voltage.

## Evidence limits and engineering boundaries

Static resources establish embedded controls, labels and defaults. Documentation
describes intended behavior. Native analysis can establish selected code paths,
but neither proves that a Windows driver read a real sensor in this environment.
There is no Windows runtime or rover hardware capture in this investigation.
No claim is made to recover HWiNFO's original source or all of its hardware
support. No affiliation or endorsement by HWiNFO or NASA is implied.

The current rover model is an illustrative six-wheel, 24 V electrical template.
Its limits, geometry and dependencies must be replaced with the team's actual
parts, wiring, calibration and CAD. Battery/BMS, fused power outputs, motor
controllers, computer, radio and sensors need independent measured channels;
a software heartbeat does not establish power at every connector.

The server currently accepts the simulation health source only. Implementing
and validating a physical acquisition adapter is a separate integration step.
The software fault model does not switch real power, simulate processor death,
or provide motor protection. The physical emergency stop remains independent.
