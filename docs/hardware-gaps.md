# Integration and field-validation gaps

This repository provides communications and mission-control software scaffolding with a simulator. Real vehicle drivers, sensors, radio installations, and human procedures need independent integration and validation. Use the supplied PDF and official Q&A checked on 2026-10-13, identified in [rules-source.md](rules-source.md); the linked [requirements matrix](requirements-matrix.md) defines what the software actually covers.

## Required before any powered rover integration

| Gap | Required work and evidence | Rules reference |
| --- | --- | --- |
| Physical emergency stop | Fit a readily visible and accessible red exterior push button. Demonstrate that it immediately stops motion and switches off every rover system's power draw from every battery, including radios/computers and auxiliary batteries. A browser stop, network stop, watchdog, or motor-only stop does not meet this requirement. Validate deployable E-stops or fuses separately. | §2.a.v–vi, p. 9 |
| Motor and actuator adapters | Replace simulated actuation with validated drivers, explicit arming, bounded outputs, encoder feedback, and a local watchdog independent of the browser. Demonstrate safe failure on process crash, stale commands, reboot, packet loss, radio loss, and disconnected sensors. Watchdog behavior and additional hardware interlocks are engineering controls, not substitutes for the rule's physical E-stop. | Supports §2.a.v, p. 9; command-loss behavior is a project design requirement |
| Physical LED | Install a rear-facing daylight-visible LED/array and connect mode/arrival state: red autonomous, blue teleoperation, flashing green arrival. Measure visibility in actual lighting and verify state/output agreement. | §1.e.ii, p. 6 |
| Off-grid vehicle | Verify onboard power, no tether to C2, and no internet/cloud dependency. Any antenna/radio/network adapter must work on the isolated field LAN. Record power budget and runtime. | §2.a.i, p. 8; §2.c.i, p. 10 |

## Radio and C2 installation

| Gap | Required work and evidence | Rules reference |
| --- | --- | --- |
| Actual radio selection | Select FCC-authorized devices, lawful configuration and applicable licenses. Submit device/license/regulatory details by 2027-04-30 and notify changes immediately. Software packet compatibility provides no RF compliance evidence. | §2.c.ii, p. 10 |
| 900 MHz profiles | If using 902–928 MHz, validate occupied bandwidth no greater than 8 MHz and independent operation wholly within 902–910, 911–919, and 920–928 MHz. Include every link and local LAN at C2, rover, drone, and astronaut; verify switching to the assigned sub-band and no out-of-band emission. Frequency selection must be implemented in the actual radio, not merely written into UI configuration. | §2.c.v, p. 11 |
| Other bands and interference | For 2.4 GHz, comply with FCC rules and characterize coexistence; URC adds no separate 2.4 GHz frequency restrictions in this source. Assess channel selection/hopping/switching as appropriate to the selected radio. Other bands and amateur licensing still require applicable regulatory compliance. | §2.c.vi, p. 11 |
| Antenna setup | Measure base antenna height ≤3 m and base distance ≤5 m from C2; stabilizing-only ropes/wires may anchor ≤10 m away. At MDRS use judge-assigned locations, potentially ≤20 m away, and bring at least 25 m communications cable for both rover and drone links (official Delivery Q2). Do not track the rover firsthand or mount a camera atop the antenna for steering feedback. | §2.c.iii–iv, pp. 10–11 |
| Range and obstruction | Field-test real telemetry, commands, media throughput, reconnect, and autonomous behavior beyond line of sight. Official Rover/Drone Q13 clarifies that Delivery and Autonomy can require travel up to 1 km from C2 and total travel may exceed 1 km. Plan the link/energy budget for this clarification despite the PDF’s weaker wording. Route finding explicitly puts a target behind a hill. | §1.c.ii–iv, p. 4; §1.e.xvi, p. 8; §3.d.ii, pp. 13–14; official Rover/Drone Q13 |
| Deployment drill | Time full C2/radio setup to ≤15 minutes and teardown/retrieval to ≤10 minutes. Practice immediate radio power-down when instructed and keep site radios off while not competing. Prepare for a 10-minute transition from Autonomy to Equipment Servicing, including reweigh/measurement unless the official Equipment Q4 exception for an unchanged/reduced configuration applies. | §1.a.ii–iv, p. 1; §1.d.i, p. 4; §2.c.i, p. 10 |
| Operator procedures | C2 operators cannot directly view the course or receive unauthorized spectator feedback. Maintain authorized roles, intervention procedures, and radio discipline; judges determine penalties. During autonomous motion operators remain hands-off even on disconnected map editors; only the C2 drone pilot may touch clearly drone-only controls (official Autonomy Q21/Q25). Physical interventions carry separate 20% mission penalties and keep the clock running. | §3.b.iv, p. 12; §3.d.i, p. 13; §3.e, pp. 14–15 |

## Autonomy, perception, and mission equipment

| Gap | Required work and evidence | Rules reference |
| --- | --- | --- |
| Localization | Connect a real GNSS receiver with WGS 84 latitude/longitude, units, freshness and accuracy/quality reporting; validate sensor fusion and arrival accuracy independently of the simulator. Supply a local GNSS base for RTK corrections; internet/CORS connectivity cannot be assumed (official Rover/Drone Q11). For science documentation, include elevation and accuracy range. | §3.d.v, p. 14; §1.b.iii, p. 2 |
| Terrain and collision safety | Integrate calibrated ranging/perception, odometry, slope/traction assessment, drop-off detection, obstacle planning and actuator control. LiDAR or a simulated stop alone cannot establish traversable terrain or collision safety. Validate rocks, soft ground, slopes and blind approaches at a permitted test site. | §1.c.ii, p. 4; §1.e.xv–xvii, pp. 7–8; §3.d.iv, p. 14 |
| Route finding | Implement and validate full autonomous navigation, tag detection and stopping within 1 m; supplied targets use ArUco 4x4_50 tags on three-sided 20 × 20 cm faces, 0.5–1.5 m above ground. Maintain trustworthy explored-route evidence for recovery. Official Autonomy Q4 requires a first aborted objective without a previous reached GNSS point to return to the start area in front of C2; bind recovery to actual judge-defined start/attempt state. Target coordinates are exact (Q16), but DEM release/timing is unconfirmed (Q20). Any software state/plan gates are supporting controls only. | §1.e.xii–xviii, pp. 7–8 |
| Camera, microphone and media transport | Select cameras/microphones, codec/transport, timestamping and bandwidth limits; add real capture and playback adapters and verify command/telemetry responsiveness under video load. The current package and telemetry path does not carry working camera or audio streams. | Supports §1.b.iii, p. 2; §1.e.iv, p. 6 |
| Astronaut assistance | Connect the EVA camera and microphone for C2 monitoring, validated astronaut localization, follow/stay/come perception and control, and a manipulator for fetch/give. A command label or synthetic position is not autonomous recognition, following, tool pickup, or delivery. Validate 3 m arrival/follow stopping tolerance. Commands must originate from the astronaut except initial approach/interventions; command order is Follow, Stay, Fetch, Come, Give. Gesture inputs use arm/leg/torso movements rather than fingers/faces (official Autonomy Q7/Q11/Q13). | §1.e.iv–xi, pp. 6–7 |
| Service autonomous typing | Implement keyboard perception/alignment and autonomous manipulation; operators must announce autonomous entry/exit to the judge and remain hands-off. Intervention may only exit autonomy and abort or restart the entire attempt. A 3–6 letter key can be programmed before the task; 2 × 2 cm ArUco 4x4_50 markers aid alignment. Official Equipment Q2/Q3 further forbids keyboard touching under manual control and requires judge display reset between attempts; avoid touching the screen. This mission capability is not implemented by this communications scaffold. | §1.d.ii, pp. 4–5 |
| Environment and mechanical envelope | Validate mass, deployed-item accounting, transport envelope, heat/dust/light rain endurance, and battery runtime. Radio relays count toward rover weight. These are measured on the real fielded system. | §2.a.ii–iv, pp. 8–9; §3.d.iii, p. 14 |

## Optional drone integration

Full points are possible without a drone (§2.b.i, p. 9). A simulator's “landed” value cannot prove that a real aircraft is safely at its designated pad.

- Use a pilot in C2 with an outside antenna (§2.b.ii, p. 9) and a dedicated field spotter maintaining visual line of sight (§2.b.xii, p. 10). The spotter communicates for safety or can take over in a dual-pilot setup, intervenes only for unsafe operation, and does not otherwise participate in the mission. The astronaut may not pilot; ask permission before takeoff/landing so judges and the spotter can confirm a clear area (official Autonomy Q22/Q25).
- Implement fresh flight-controller telemetry and an independently verified landed-at-designated-pad condition before the rover leaves the route-finding start toward targets (§1.e.xiv, p. 7). A drone can conduct reconnaissance during astronaut assistance; it cannot remain aloft as the rover begins route finding.
- Validate rotary-wing hover capability and judge-authorized takeoff/landing (§2.b.iii–iv, p. 9), inert nonfunctional dummy mass equal to battery mass at all times (§2.b.v, p. 9), total mass ≤5 kg including dummy mass and registration/marking when over 250 g (§2.b.vii, p. 9).
- Provide Remote ID, pilot TRUST proof and current applicable FAA compliance, including altitude and manned-aircraft right of way (§2.b.ix–xii, pp. 9–10). The repository does not certify current aviation law or validate licensing.
- Validate wind limits; the PDF strongly suggests operation in 48 kph/30 mph winds and associated top speed ≥64 kph/40 mph, but does not waive dummy mass for wind (§2.b.vi, p. 9).
- Include the drone and fielded C2/comms equipment in the $26,000 fielded-equipment budget (§2.b.viii, p. 9; §3.c.iii, p. 13). Official Autonomy Q12 includes required suit garments and wearable electronics in cost (not mass), while excluding specified optional clothing/accessories. Human battery swaps count as interventions; vehicle-executed swaps are permitted capabilities that are not implemented here (official Rover/Drone Q14).
- Repeaters may be deployed by rover/drone within applicable mass/cost budgets. The drone cannot deploy a mini-rover, and the astronaut may carry suit electronics but cannot deploy items (official Rover/Drone Q15; Autonomy Q19/Q26).

## Hardware decisions still needed

The [rover health monitor](rover-health.md) currently receives simulated values.
Its six-wheel topology and electrical/temperature limits are illustrative. Add
calibrated BMS and branch voltage/current sensing, fuse/enable feedback, motor
fault/RPM data, computer/radio metrics and sensor-specific validity before using
the cutaway for physical diagnosis. Preserve acquisition time, sample identity
and quality; a received heartbeat or nominal voltage alone does not establish
that a subsystem works. Replace the reference geometry with the team's CAD and
map every physical channel to its actual component. There is no HWiNFO hardware
bridge or physical acquisition adapter in this repository.

Record actual choices before implementing adapters: rover/drone computers and OS; motor/actuator controller interfaces and independent watchdog; battery/E-stop circuit; GNSS and inertial sensors; camera/audio devices; ranging/perception sensors; radio part numbers, bands and lawful configurations; drone flight controller and bridge protocol; field C2 laptop; LED driver; and whether a drone is fielded at all. These selections are intentionally open because the task supplied no hardware specifications.

## Release gate

Before a field release, collect actual hardware part numbers/configuration, wiring and battery-isolation diagrams, radio/license submissions, offline deployment evidence, timed setup/teardown results, fault-injection records, terrain/navigation results, and the current organizer PDF/Q&A comparison. Official pages/Q&A were checked on 2026-10-13 and the linked PDF bytes matched the attachment, as recorded in `rules-source.md`; recheck for later updates before release. Bench simulation is useful evidence for software transitions and packet handling; it cannot close the hardware and operational gaps above.
