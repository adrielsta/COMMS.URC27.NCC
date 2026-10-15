# Static inspection of HWiNFO 8.54

On 2026-10-15, REA 6.5.0 and Ghidra 12.1.4 inspected the actual Windows HWiNFO application to understand its sensor-statistics and logging controls. The application was never executed. This is a bounded static investigation, not a reconstruction of the complete product or proof of its runtime behavior.

## Artifact and tool identity

| Artifact | Size | SHA-256 |
| --- | --- | --- |
| Original extracted `HWiNFO64.EXE` | 11,484,648 bytes | `e4ce0c85c4288fa7e8eb12ebeece99efff4d81e0b13de53f091daabc81a3c9d3` |
| UPX-decompressed analysis copy `HWiNFO64.unpacked.exe` | 26,202,088 bytes | `5ef21625978eb2d2f6906ad31b9817ce8235be80dca556404f1d83e4674e366a` |

The original application was UPX-packed. Its normal decompression produced a separate analysis copy; the packed original remained unchanged. The decompressed copy is a derived artifact and must not be described as a byte-identical vendor download. Installer release metadata is recorded in [health-research.md](health-research.md).

The official [Ghidra 12.1.4 release](https://github.com/NationalSecurityAgency/ghidra/releases/tag/Ghidra_12.1.4_build) archive was 569,649,598 bytes and matched GitHub's published SHA-256 `ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db`. All archive paths were checked before extraction. The official [Temurin JDK 21.0.12.1+1 release](https://github.com/adoptium/temurin21-binaries/releases/tag/jdk-21.0.12.1%2B1) archive matched SHA-256 `ce79869e1307ed8ee1e2baa86a412b1eb5b75d10a01006d788a6f968bcfaee94`. Both tools were installed in the research workspace; no global agent registration was added.

REA's Ghidra-specific doctor passed every required check. A single local stdio session imported the decompressed PE into an ephemeral read-only Ghidra project. The observed JVM used a 2 GiB heap and the installed full JDK. REA reported an image base of `0x140000000`, 18,792 recovered procedures, 37,729 defined strings, and seven memory blocks. Those are Ghidra inventory counts, not a guarantee that all code or text was recovered.

## Findings tied to native code

| Question | Static evidence | Design consequence |
| --- | --- | --- |
| What does the reset control represent? | The string at `0x1408bbdf0` is referenced at `0x1402b0fbd` inside `FUN_1402b091c`. This routine maps control `1438` (`0x59e`) to “Reset Min/Max/Average Values and Timer.” The nearby Windows message-map entry at `0x1408bc340` points to `0x1402adb7c`. | Give statistics reset an explicit scope and visible start time, separate from hardware recovery or alarm acknowledgement. |
| Does the reset handler actually update stored statistics? | Recovered `FUN_1402adb7c` acquires a mutex when present, walks sensor/reading entries, writes positive/negative maximum finite-double sentinels into two fields, copies a current-value field into another aggregate field, writes a count/state field to `1`, and updates the stored timer origin before requesting a refresh. It also calls per-device virtual methods whose full effects were not traced. | Statistics have a real accumulation window. Rebuild the rover's own clear, documented sample statistics; do not infer a full average algorithm or hardware side-effect guarantee from this one handler. |
| Is logging a distinct stateful action? | The tooltip routine maps control `1437` (`0x59d`) to Logging Start or Logging Stop based on whether a stored file handle equals `-1`. Native `FUN_1402abb0c` offers CSV/JSON/YAML file choices, calls `CreateFileW`, switches the button text, and dispatches recording/close helpers. | Show whether recording is active and where/time range it covers. Keep a statistics reset separate from starting or stopping a recording. |
| How is the logging button connected? | The adjacent message-map entry at `0x1408bc320` points to `0x1402ab714`. REA read its bytes; a separate `objdump` inspection identifies a small wrapper that sets its second argument to zero and jumps to `0x1402abb0c`. Ghidra did not expose that wrapper as a decompilable procedure, so the byte/disassembly evidence is retained separately. | Retain uncertainty in a tool's recovered function inventory instead of treating an unrecognized wrapper as missing functionality. |
| What happens in the close helper? | Recovered `FUN_1402acddc` contains format-dependent final writes, `WriteFile` calls, `CloseHandle`, and resetting the stored handle to `-1`. | A stopped recording should represent a closed output session. This static path does not prove every possible write failure is handled correctly. |
| Does HWiNFO distinguish uncertain or disabled sensors? | The tooltip code branches to text stating that a mainboard-specific sensor value may not be valid, and separately to text stating monitoring is disabled. It also explains that an aggregated row's Current value is an average of current constituent values, while its other columns describe runtime statistics. | Keep validity and monitoring state visible. Distinguish a physical measurement, a current aggregate, and an average over time; identical column labels can otherwise hide different meanings. |
| Is paused monitoring visible? | Recovered sensor-title routine `FUN_1402a69dc` includes the version/build `8.54`/`6090`, hidden-value counts, and a PAUSED branch. | Make a paused or unavailable data source explicit; do not leave old values looking live. |

The reset timestamp helper `FUN_1402168d0` contains a `GetTickCount` fallback and an unresolved indirect function call. This supports a tick-based timer interpretation but does not establish the identity of the dynamically selected alternative. No claim is made that the rover implementation duplicates HWiNFO's internal timing or averaging algorithm.

## Evidence ledger

Complete REA result envelopes, decompiler output, input/output hashes, logs, and a reusable snapshot remain under `/workspace/scratch/hwinfo-research/rea-native/`. Only this factual summary is part of the application repository; the proprietary program and its decompiled routines are not shipped with the rover software.

| Saved result | REA evidence ID |
| --- | --- |
| `overview.json` | `ev_755678e5c0d2dedc7fd0a47cb68a7d878167da9008c2284f2438b46b72f902a0` |
| `reset-tooltip-owner-pseudocode.json` | `ev_7015f1220a61eeb4cd4a96f65345295b777740aa5c8c914cda3d3a4a2eb7a92e` |
| `reset-log-message-map-bytes.json` | `ev_bbfa44fad7c8c603489de1c8a38c6852f7447b7b19d64d8d593361892f38ec19` |
| `reset-handler-pseudocode.json` | `ev_6df8979a0015ec0fdb9fe9feb4cc2dec58dcc386889f57119f91f388b6c44361` |
| `logging-owner-pseudocode.json` | `ev_cba98b7ee350417c8ddb19521af41b1bd1e3bca47164c24f19b1240c3b8b241c` |
| `log-close-helper-pseudocode.json` | `ev_e51c6f6067ea17a831df63b7118d2afbcf3ac5b86fb573be871b6e11de3a1aec` |
| `log-button-wrapper-bytes.json` | `ev_99f41e6ebc1f46be4d72a9064be8a06b3707435b95cf136fb302f65f31a1cec2` |
| `sensor-window-owner-pseudocode.json` | `ev_f404c58f34496f69e4d357fd45c6e61218606769eb4a423ca669d91367ad0812` |
| `timestamp-helper-pseudocode.json` | `ev_14cfdc3faffb5c47be79bcc60806141851b7bb5ea4ef6b13765c512157ae2c11` |

Decompiler output is an analysis approximation, not the original source. Original types/names and indirect-call targets remain incomplete. Ghidra reported VarnodeContext, RTTI demangling, and data-creation warnings; several result envelopes also identify terminal-flow and unresolved-jump limitations. These were retained rather than suppressed. The analysis did not exercise live hardware, validate measurement accuracy, or independently verify all alert evaluation paths.

At completion, REA saved the snapshot and closed the target. The owned Ghidra process exited, its ephemeral project/runtime directory was removed, and both original and derived file hashes were rechecked unchanged. The research client and REA server also exited normally.
