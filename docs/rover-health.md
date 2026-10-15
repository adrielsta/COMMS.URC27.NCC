# Rover engineering monitor

**Rover systems** shows the same received measurements in two forms: a selectable
isometric cutaway and a grouped sensor register. The six-wheel geometry, 14
components, 24 V supply model and thresholds are illustrative. This is live
simulation telemetry, not measured hardware or the team's final CAD.

## Operator workflow

Select a component in the cutaway or subsystem list to inspect voltage, current,
temperature, power state, supply dependency, fault and recent trends. The
**Sensors** tab exposes all 42 channels with Current, Minimum, Maximum, Average,
valid sample count, units, limits and quality. Component groups can be folded;
the Inspect action or double-click opens that component's trends.

Statistics belong to this browser observation window. Each distinct received
health sequence contributes once, regardless of browser rendering frequency.
Average is the arithmetic mean of valid observed samples. The reset time is
visible; Reset statistics clears these aggregates and graph history, without
altering telemetry or alarms. A rover boot change starts a new observation
window. Graphs retain up to 120 observations per channel and show breaks where
measurements become unavailable. CSV export contains the current register and
statistics, not a continuous or durable flight recorder.

Unknown or stale measurements never appear as nominal Current values. Historical
statistics remain identifiable as history. Both HTTP and vehicle/health freshness
matter. C2 expires a health sample after one second without a strictly increasing
health sequence, even if other vehicle telemetry continues. Client rendering also
accounts for time elapsed since its last successful HTTP response.

The fault annunciator retains active and resolved conditions for the current C2
process. Acknowledge records operator review; it never clears a simulated fault.
Independent overtemperature and overcurrent conditions can coexist. A missing
sensor or link marks an earlier fault unconfirmed instead of reporting recovery.
Only a fresh valid reading that no longer satisfies the condition resolves it.
Alarm and event history are bounded, in memory, and reset when C2 restarts.

## Reproducible failure demonstrations

Open **Simulator fault controls** under Rover systems:

1. Select a drive component and apply **Overtemperature**. Confirm its cutaway
   marker, channel readings and alarm change together. Acknowledge the alarm;
   its active condition remains.
2. Apply **Sensor loss** to that component. Its Current values become unknown,
   while the prior temperature alarm is unconfirmed. Clear the selected fault
   and wait for fresh telemetry to confirm recovery.
3. Apply **Power loss** to Power distribution. Downstream loads report an
   upstream supply failure while the battery remains powered. Clear the PDU
   fault to recover the modeled branch.
4. In Network, disconnect the simulated vehicles. The engineering view marks
   measurements stale, stops accumulating observations and disables new health
   fault commands. Reset network faults to reconnect.

Fault injection is an authenticated, expiring, deduplicated rover command with
the same requested/acknowledged lifecycle as other commands. It changes the
engineering telemetry model only. It does not turn off the simulation process,
radio transport or actuators, and does not implement a motor protection policy.

## Telemetry contract

GET `/api/health/catalog` returns model identity, units, components, dependencies,
nominal voltages, limits, freshness period and supported simulation faults.
`comms/health.py` owns the configurable template. The current source is explicitly
`simulation`; the C2 validator rejects other sources until a physical adapter is
implemented and validated.

Received rover state includes:

```json
{
  "health": {
    "schema_version": 1,
    "model_id": "ncc-six-wheel-v1",
    "source": "simulation",
    "seq": 123,
    "components": {
      "battery": {
        "powered": true,
        "voltage_v": 24.0,
        "current_a": 4.2,
        "temperature_c": 30.0,
        "status": "nominal",
        "fault": null
      }
    },
    "overall": "nominal"
  }
}
```

The example abbreviates the 14 components. Missing components or malformed
measurements become unknown. C2 derives status from validated numeric channels
and limits rather than trusting a sender's nominal label, then adds receipt-local
`age_s` and `stale`. Sensor freshness at acquisition is a separate hardware-adapter
requirement; arrival time cannot establish when a delayed physical sample was taken.

POST `/api/command` accepts `SIM_HEALTH_FAULT` for the rover with
`{component, fault}`. Faults are `power_loss`, `overtemp`, `overcurrent`,
`sensor_loss`, or `clear`. POST `/api/health/ack` takes `{alarm_id}` and marks the
C2 alarm acknowledged. Both require the existing same-origin/CSRF protections;
fault commands also pass the signed vehicle transport, session, sequence,
receiver-local expiry and duplicate checks.

`/api/state.health_monitor` exposes bounded alarms and transition events. Each
alarm has an ID, component, code, severity, active/acknowledged/confirmed flags,
and first/last/resolved times. These times describe C2 observations, not hardware
acquisition timestamps. Multiple channels can independently raise alarms on one
component.

## Physical integration still required

The ideal DC model conserves load watts across supply rails; it does not model
converter losses, battery chemistry or a BMS. Loss of a measurement is distinct
from a measured zero-volt supply and does not cascade false power failures.

Replace the catalog with actual part numbers, channel IDs, units, limits and
wiring. Connect calibrated battery/BMS readings, branch voltage/current and
fuse/enable feedback, motor-controller fault/RPM/encoder data, computer metrics,
radio/link metrics, and sensor-specific validity/heartbeat information. Keep
acquisition sample identity, age and quality through the transport. Electrical
power alone does not prove that GNSS, vision, computation or communications work.

No HWiNFO driver, SDK bridge, hardware adapter, real power switching, automatic
fault recovery, physical emergency stop, or final rover CAD is provided by this
monitor. See [hardware gaps](hardware-gaps.md),
[HWiNFO investigation](hwinfo-reconstruction.md) and [Anatomy provenance](anatomy-source.md).
