# Mission-control interface

The console opens on **Rover systems**. A selectable engineering cutaway,
component inspector, sensor register and fault annunciator share the same
received rover health state. Mission, Drone, Routes and Network remain separate
operator workspaces. Software STOP, connection state, simulation source and the
running server's version stay visible across them.

Graphite surfaces, compact numeric rows, thin dividers and restrained status
colors support prolonged monitoring. There are no decorative gauges, animated
scans, inferred uptime percentages or unconnected camera imagery. Nominal,
warning, critical, unknown and stale states have text/symbols as well as color.
Active faults are summarized above the cutaway and link to the alarm queue.

## Source-backed behavior

The requested [REA](https://github.com/morluto/rea) skill and CLI were used to
investigate the actual HWiNFO 8.54 application. Its verified installer, unpacked
analysis artifact, embedded dialogs and bundled manual provide the basis for
grouped readings, units, Current/Minimum/Maximum/Average columns, statistics
reset, per-component trends and sensor quality. See the exact
[investigation and evidence limits](hwinfo-reconstruction.md) and
[REA tool provenance](rea-source.md). The rover implementation is original;
HWiNFO binaries, graphics, drivers and recovered code are not included.

NASA Open MCT and F Prime references informed channel freshness, distinct
severity/quality, telemetry limits, event history and separate acknowledgment.
Actual accessed sources and inference limits are recorded in
[monitoring research](health-research.md). The console is not affiliated with or
endorsed by NASA or HWiNFO.

The requested [Anatomy skill](https://github.com/wheresryan22/anatomy), pinned to
`e9488296a44211c42701ff71705b7901470ec78f`, supplies the licensed isometric
geometry kit. The rover is an original 69-solid, 14-component illustration with
physical depth, mounts, wheel hubs, battery cells, electronics and instruments.
It is a configurable six-wheel reference, not measured CAD. The generated SVG
ships locally; no runtime package, network, WebGL or animation loop is required.
Geometry and layer/selection behavior have dedicated checks; see
[Anatomy provenance](anatomy-source.md) and [vendored kit](../vendor/anatomy/README.md).

The [Taste redesign workflow](https://github.com/Leonxlnx/taste-skill/blob/f624f37a8c650b9cc550253104925efe4c8de246/skills/redesign-skill/SKILL.md)
was used for hierarchy, restrained styling, responsive layout and functional
verification. Its default landing-page skill excludes dashboards, so decorative
marketing treatments are not used here. Earlier 21st.dev tab/table source
inspection informed the underlying accessible controls; no React component or
remote stylesheet was imported.

## Interaction and information quality

Anatomy components support pointer and keyboard selection, with the adjacent
subsystem list as an equivalent control. Layer filters emphasize physical groups
without changing telemetry or issuing commands. The Sensors view supports
group filtering, expandable components, inspection/trends, observation reset
and CSV export. Minimum/maximum/mean count distinct valid observations; unknown
and stale current values stay unavailable. Historical statistics remain labeled.

Acknowledging a fault records operator review without clearing it. Only fresh
confirming telemetry resolves a condition. Multiple conditions on one component
remain independently visible. Polling preserves focus on acknowledgment controls.
The current model and engineering injection controls are explicitly simulation.

Workspace navigation preserves the selected package and vehicle state. Arrow
keys and Home/End operate the tabs; browser Back/Forward and reload retain the
workspace. Hidden panels expose no keyboard controls, the skip link reaches the
main content, and local maps recalculate dimensions when reopened. Compact
screens use a stacked layout and a separately scrollable sensor table.

Mission commands retain receiver checks, correlated acknowledgments, manual
lease expiry and separate package transfer/activation/execution. Stale telemetry
and autonomous motion lock package editing. Navigation sends no vehicle command.
Historical satellite imagery retains its source/year/license; the camera view
continues to report that no camera is connected.
