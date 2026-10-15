# Operations interface

The interface is organized around four operator tasks: field overview, drone
operations, route planning, and network diagnostics. Vehicle state and map
position take priority over explanatory copy. Software STOP, connection status,
simulation context, and command outcomes remain available across workspaces.

The theme uses neutral surfaces, a single blue action color, tabular numeric
values, and compact data rows. Red identifies the software stop action and
errors; green indicates fresh received state. Colors accompany text labels.
Historical imagery and simulated positions retain their distinct source labels.
The camera panel states that no camera is connected.

## Design sources

The requested [Taste skill collection](https://github.com/Leonxlnx/taste-skill)
was inspected at revision `f624f37a8c650b9cc550253104925efe4c8de246`. Its
[`redesign-existing-projects` workflow](https://github.com/Leonxlnx/taste-skill/blob/f624f37a8c650b9cc550253104925efe4c8de246/skills/redesign-skill/SKILL.md)
applies to existing applications and vanilla CSS. This redesign follows its
audit, hierarchy, restrained palette, focus visibility, responsive layout, and
functional verification guidance. The collection's default public-page skill
explicitly excludes dashboards; landing-page typography and decorative motion
requirements are not applied to vehicle controls.

The following actual [21st.dev open-source platform](https://github.com/serafimcloud/21st)
patterns were inspected at revision `b96d84dcf748d5e56f2f72f2bab9a4f7f33574cf`:

- [Sidebar](https://github.com/serafimcloud/21st/blob/b96d84dcf748d5e56f2f72f2bab9a4f7f33574cf/apps/web/components/ui/sidebar.tsx): persistent navigation, named destinations, and filled selected states.
- [Tabs](https://github.com/serafimcloud/21st/blob/b96d84dcf748d5e56f2f72f2bab9a4f7f33574cf/apps/web/components/ui/tabs.tsx): compact selection groups and visible keyboard focus.
- [Table](https://github.com/serafimcloud/21st/blob/b96d84dcf748d5e56f2f72f2bab9a4f7f33574cf/apps/web/components/ui/table.tsx): consistent row spacing and restrained treatment of data.

These informed an original implementation in the existing HTML, CSS, and
JavaScript. No React component source, package, icon library, or remote font was
imported. Live access to the 21st.dev marketplace was blocked by the environment;
the accessible public source supplied the references. No marketplace preview or
MCP integration is claimed.

## Interaction

Navigation switches workspaces without changing vehicle state or discarding a
reviewed package. Arrow keys and Home/End move among navigation tabs. URLs retain
the selected workspace; browser Back/Forward and reload restore it. Hidden
workspaces do not expose controls to keyboard navigation. Maps recalculate their
visible dimensions when reopened.

Mission commands retain receiver checks, confirmed acknowledgements, manual
lease expiry, and separate transfer/activation/execution. Stale telemetry and
autonomous motion still lock package editing. Navigation itself sends no vehicle
command. All rendering assets remain local for offline use.
