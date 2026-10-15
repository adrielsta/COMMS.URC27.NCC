# Anatomy source and rover adaptation

[Anatomy](https://github.com/wheresryan22/anatomy) is an Agent Skill for building interactive technical figures from isometric SVG solids. Its examples include instruments, a computer, an arcade cabinet and a rocket engine. It supplies drawing geometry and review tools; it does not read vehicle sensors or diagnose faults.

The source is pinned to [`e9488296a44211c42701ff71705b7901470ec78f`](https://github.com/wheresryan22/anatomy/tree/e9488296a44211c42701ff71705b7901470ec78f), retrieved on October 15, 2026. It is licensed under [MIT](https://github.com/wheresryan22/anatomy/blob/e9488296a44211c42701ff71705b7901470ec78f/LICENSE), copyright 2026 Ryan. Preserve that license beside any redistributed kit code or substantial copied material. The license permits adaptation and commercial use; the rover drawing does not need upstream example artwork.

The complete 153-file skill is installed locally at `.agents/skills/anatomy/`, beside the existing Taste skill. `UPSTREAM.json` records its repository, revision and a SHA-256 for every upstream file. All hashes were checked after copying; the source cache is `/workspace/scratch/skill-sources/anatomy`. The skill installation is development tooling, separate from the dashboard's runtime assets. No package installer or gallery publishing command was run.

## Integration approach

The framework-free path fits this dashboard. `kit/iso-kit.mjs` exports projection, solid geometry, shading and SVG string helpers with no package dependencies. `scripts/build_rover_anatomy.mjs` creates the rover artwork once with stable component identifiers; the browser updates selection and status from the same telemetry snapshot as the numerical instruments. The four preserved kit modules and license are recorded in [vendor/anatomy](../vendor/anatomy/README.md). No CDN, React, WebGL or live internet connection is necessary.

Anatomy's documented build and browser-check tools require Node.js 20.10 or newer and Chrome/Chromium. The browser only needs the generated SVG and local JavaScript. The finished illustrative figure has 69 solids mapped to 14 components. Its geometry audit reported zero issues, and dark/light linework checks reported zero floating ends among 250 checked endpoints. Desktop, phone and enlarged detail captures were visually inspected. These checks concern rendering; the drawing is not measured vehicle CAD.

The relevant design references are [`SKILL.md`](https://github.com/wheresryan22/anatomy/blob/e9488296a44211c42701ff71705b7901470ec78f/SKILL.md), [`references/craft.md`](https://github.com/wheresryan22/anatomy/blob/e9488296a44211c42701ff71705b7901470ec78f/references/craft.md), [`references/motion.md`](https://github.com/wheresryan22/anatomy/blob/e9488296a44211c42701ff71705b7901470ec78f/references/motion.md), and the compact [`dial-indicator`](https://github.com/wheresryan22/anatomy/tree/e9488296a44211c42701ff71705b7901470ec78f/examples/dial-indicator) example. The rover uses their physical construction, depth, surface detail, keyboard selection and reduced-motion principles.

## Monitoring model

The system view is a conceptual rover assembly until team CAD, wiring, channel assignments and sensor calibrations are supplied. Its useful purpose is to connect an observed fault with the affected physical subsystem: battery, distribution, drive, computer, communications, mast and payload. Displayed engineering units and alarm states must come from telemetry, with freshness and source shown explicitly.

- Simulation values remain labelled as simulation. Drawing a powered cable cannot establish that a physical rail is energised.
- Missing, invalid, disconnected or stale channels are unknown; an old normal value must not remain a green indication of current health.
- Colour supplements a state word and component selection. Operators can find the same component through a keyboard-accessible list.
- Selection may change the view or reveal internal parts, but never changes vehicle authority or commands a component.
- Alarm thresholds and fault scenarios belong to the telemetry model, not to animation code. An injected simulation fault must be traceable as an injected fault.
- Decorative idle tours are omitted from the operating display. Any motion represents selection, a user-requested assembly view, or a documented measured quantity; reduced-motion mode retains all diagnostic information.

The full future vehicle geometry and the physical telemetry adapters are separate work. This integration should remain honest about the conceptual geometry and the currently connected data source while providing a working foundation for live engineering channels.
