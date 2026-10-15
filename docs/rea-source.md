# REA source and HWiNFO investigation tooling

[REA](https://github.com/morluto/rea) provides local reverse-engineering CLI and MCP workflows with evidence records. The source checkout is pinned to [`5b16f2431062eea6ffd245a9e05512790007cb13`](https://github.com/morluto/rea/tree/5b16f2431062eea6ffd245a9e05512790007cb13), retrieved October 15, 2026. Its license is MIT, copyright 2026 morluto.

The version 42 `reverse-engineer-anything` skill is installed at `.agents/skills/reverse-engineer-anything/`. Its seven instruction/reference files and upstream license have verified SHA-256 entries in the accompanying `UPSTREAM.json`. The source cache is `/workspace/scratch/skill-sources/rea`; Anatomy and Taste remain installed alongside it.

The separate CLI is pinned to npm package `rea-agents@6.5.0` under `/workspace/scratch/tools/rea/`. Installation used `--ignore-scripts`, an isolated workspace npm cache, and no global client configuration changes. Its package lock and `UPSTREAM.json` preserve the registry artifact, integrity string and dependency lock digest. The registry tarball integrity is:

```text
sha512-C6BG7LyrAdR74mSjertM6PrxJkcNZ2bfQNOJornPo9erDEp2tyPRVYPnV5Yodr+1RqewCQla68WulXlVnveD+A==
```

## Verified capabilities

The installed public launcher reports version 6.5.0 under Node.js 24.19.0. The initial `rea doctor --client codex --json` confirmed the supported Node runtime and identified absent native providers. Ghidra 12.1.4 and a full JDK 21 were subsequently prepared for the native investigation. The CLI works independently of MCP registration; manually installing a skill does not register a server or install a decompiler.

The following public operations are available for a Windows PE artifact without running that artifact:

```bash
/workspace/scratch/tools/rea/node_modules/.bin/rea inspect-pe-resources /absolute/path/to/selected.exe --json
/workspace/scratch/tools/rea/node_modules/.bin/rea inspect-with-objdump /absolute/path/to/selected.exe file_headers --json
/workspace/scratch/tools/rea/node_modules/.bin/rea inspect-with-objdump /absolute/path/to/selected.exe section_headers --json
```

`list-objdump-architectures --json` completed successfully through REA using GNU Binutils 2.44. Its evidence ID is `ev_f7f1904c7877fced40d45589aaaf99247464f7f3e513b6bc77fcd82d9f8e13be`; the output advertises PE x86 and x86-64 formats. This establishes the installed provider's advertised formats, not successful analysis of any particular HWiNFO release. The complete capability record is retained at `/workspace/scratch/tools/rea/objdump-capabilities.json`.

## HWiNFO static evidence

The verified HWiNFO 8.54 installer has SHA-256 `16281ec83a69a720beac8e2a1dad606fb2eaf4757bb02c7752b72ee2c26ee243`. Extraction yielded the x86-64 application with SHA-256 `e4ce0c85c4288fa7e8eb12ebeece99efff4d81e0b13de53f091daabc81a3c9d3`. Its `UPX0` and `UPX1` sections explained the resource decoder's initial rejection: the packed resource ranges are not entirely file-backed. The installer and unpacking stub are distinct from the application code being investigated.

Official UPX 5.2.1, verified against its release asset SHA-256 `402162aad30af47e60dbd767fb2e64ca394ace9727ba1f40283641f1d1b91657`, decompressed a separate analysis copy with the normal `-d` operation. That copy is 26,202,088 bytes with SHA-256 `5ef21625978eb2d2f6906ad31b9817ce8235be80dca556404f1d83e4674e366a`. The original remained unchanged. No HWiNFO executable or driver was run.

REA resource evidence `ev_2bfae231dfe14f16fa2130bf6f40b984b3d07f48d1ef152b4812fca8644b4508` inventories 1,351 resources after examining 2,723 entries, with complete inventory coverage. A separate format-aware decoder read only those verified payload ranges, checking their digests again, and decoded 53 dialog templates and 99 nonempty string-table entries with no decoding errors. This follow-up is recorded separately from the original REA evidence.

| Static application observation | Resource evidence |
| --- | --- |
| Sensor list with configuration, logging and reset controls | Dialog 233; list 2301; buttons 1436–1438 |
| Current, Minimum, Maximum and Average columns | Dialog 1910; controls 1452, 1448, 1450, 1451 |
| Averaging interval in samples and whole-runtime default until reset | Dialog 1910; controls 2539, 2541 and group 1509 |
| Lower/upper alert thresholds and sample-count setting | Dialog 1914; controls 1453, 1454 and 2172 |
| Notification interval and explicit alert enable | Dialog 1914; controls 2170 and 1452 |
| Separate critical-colour and invalid-value ranges | Dialog 1918; groups 1521 and 1522 |
| Graph reset and automatic fit | Dialog 407; controls 2151 and 2150 |

The derived artifact, raw REA JSON, decoded records, selected findings with file offsets, and extraction/unpacking provenance are retained under `/workspace/scratch/hwinfo-research/`. Relevant files are `rea-unpacked-pe-resources.json`, `unpacked-decoded-ui.json`, `static-ui-findings.json`, and `unpacking-provenance.json`. Embedded labels establish the available interface and configuration intent. They do not prove the runtime calculations, threshold timing or physical sensor behavior; those require their own documentation, code or runtime evidence.

## Evidence boundaries

The subsequent native investigation used REA with Ghidra 12.1.4 and Temurin JDK
21.0.12.1+1. It followed the reset and logging controls into recovered application
handlers, retaining code addresses, unresolved calls and complete Evidence
records. See [native analysis](hwinfo-native-analysis.md) for the findings and
tool hashes. The target was closed, the temporary project was removed, and the
original and derived artifact hashes were rechecked at completion.

HWiNFO investigation starts from a specific official downloadable artifact with recorded URL, version and digest. PE resources can establish embedded dialog and string definitions. Native code analysis needs an available decompiler provider; Windows GUI and driver behavior require a suitable Windows runtime. Static string matches alone do not establish execution, sensor calibration, polling cadence, or fault detection behavior.

The rover implementation uses the useful monitoring concepts supported by evidence—grouped measurements, units, current/history values, thresholds and explicit sensor state—as independently written application behavior. Keep observations from the target separate from rover design choices, and retain any unresolved hardware behavior explicitly. REA is development tooling; it adds no dashboard runtime dependency and supplies no rover sensor driver.
