"use strict";

(() => {
  const $ = (id) => document.getElementById(id);
  const STALE_SECONDS = 2;
  const state = {
    data: null,
    lastSuccess: 0,
    httpHealthy: false,
    reviewedPackage: null,
    pendingCommands: new Map(),
    positions: [],
    lastPositionKey: null,
    lastBootId: null,
    faultsInitialized: false,
    faultFormDirty: false,
    commandFingerprint: "",
    eventFingerprint: "",
    inFlight: new Set(),
  };
  const missionNames = {
    delivery: "Delivery",
    assistance: "Astronaut assistance",
    route_finding: "Autonomous route finding",
    service: "Equipment servicing",
  };
  const actionNames = {
    STOP: "Software stop",
    CLAIM_CONTROL: "Claim control lease",
    MANUAL: "Manual pulse",
    SET_MISSION: "Set mission",
    START_ROUTE: "Start route",
    RECOVER_ROUTE: "Recover route",
    DRONE_TAKEOFF: "Take off",
    DRONE_SURVEY: "Run survey",
    DRONE_LAND: "Land drone",
    ACTIVATE_PACKAGE: "Activate package",
  };
  const faultFields = {
    loss: "fault-loss",
    delay_ms: "fault-delay",
    jitter_ms: "fault-jitter",
    duplicate: "fault-duplicate",
    reorder: "fault-reorder",
    disconnect: "fault-disconnect",
    telemetry_only: "fault-telemetry-only",
    corrupt_bulk: "fault-corrupt",
  };
  const fractionFields = new Set(["loss", "duplicate", "reorder"]);
  const booleanFields = new Set(["disconnect", "telemetry_only", "corrupt_bulk"]);

  function text(id, value) {
    const next = value === null || value === undefined || value === "" ? "—" : String(value);
    if ($(id).textContent !== next) $(id).textContent = next;
  }

  function friendly(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "object") return Object.entries(value).map(([key, val]) => `${key}: ${val}`).join(" · ");
    return String(value).replaceAll("_", " ");
  }

  function message(value, error = false) {
    const node = $("message");
    node.textContent = value;
    node.classList.toggle("error", error);
    node.hidden = false;
  }

  function live() {
    return Boolean(state.data && state.httpHealthy && Date.now() - state.lastSuccess < STALE_SECONDS * 1000);
  }

  function vehicleAge(vehicle) {
    const value = vehicle?.age_s;
    if (value === null || value === undefined || !Number.isFinite(Number(value))) return Infinity;
    return Number(value) + (Date.now() - state.lastSuccess) / 1000;
  }

  function vehicleFresh(vehicle) {
    return live() && vehicle?.connected === true && vehicleAge(vehicle) < STALE_SECONDS;
  }

  function packageEditLock() {
    const rover = state.data?.vehicles?.rover;
    const actual = rover?.state;
    if (actual?.moving && ["autonomous", "recovering"].includes(actual.mode)) {
      return "Hands off: package inputs are locked during autonomous rover motion, including recovery (URC 2027 Q&A, Autonomy Q21).";
    }
    if (!vehicleFresh(rover) || typeof actual?.moving !== "boolean" || !["stopped", "manual", "autonomous", "recovering"].includes(actual.mode)) {
      return "Package inputs are locked until fresh rover telemetry confirms its motion state.";
    }
    return null;
  }

  function requirePackageEditing() {
    const reason = packageEditLock();
    if (reason) throw new Error(reason);
  }

  async function post(path, body) {
    if (!state.data?.csrf_token) throw new Error("Waiting for a session token. Request was not sent.");
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 7000);
    try {
      const response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.data.csrf_token },
        body: JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
      });
      let result;
      try { result = await response.json(); } catch { throw new Error(`Server response could not be read (HTTP ${response.status}). Outcome is unconfirmed.`); }
      if (!response.ok) throw new Error(result.error || result.reason || `Request failed (HTTP ${response.status}).`);
      return result;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("HTTP request timed out. The vehicle outcome is unconfirmed; check activity before retrying.");
      if (error instanceof TypeError) throw new Error("HTTP connection failed. The vehicle outcome is unconfirmed; check activity before retrying.");
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  async function withButton(id, operation) {
    if (state.inFlight.has(id)) return;
    state.inFlight.add(id);
    refreshAvailability();
    try { await operation(); } catch (error) { message(error.message || "The request failed. Outcome is unconfirmed.", true); }
    finally { state.inFlight.delete(id); refreshAvailability(); }
  }

  async function command(vehicle, action, args = {}) {
    const result = await post("/api/command", { vehicle, action, args });
    const reported = result.command || result;
    if (reported.id) {
      state.pendingCommands.set(reported.id, {
        id: reported.id,
        vehicle,
        action,
        status: "requested",
        created_at: new Date().toISOString(),
        ...reported,
      });
    }
    renderCommands();
    const rejected = reported.status === "rejected";
    message(rejected
      ? `${actionNames[action] || action} rejected: ${reported.reason || "see command activity"}.`
      : `${actionNames[action] || action} requested for ${vehicle}. Check the vehicle acknowledgment and confirmed telemetry.`, rejected);
    return reported;
  }

  async function waitForConfirmed(predicate, commandId, timeout = 5000) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      const commandState = state.data?.commands?.find((entry) => entry.id === commandId);
      if (["rejected", "timeout"].includes(commandState?.status)) {
        throw new Error(commandState.reason || "The prerequisite command did not complete. Further requests were not sent.");
      }
      // A matching telemetry value is not confirmation of this request.
      if (live() && commandState?.status === "completed" && predicate(commandState)) return commandState;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
    throw new Error("The required vehicle state was not confirmed in time. Further requests were not sent; inspect activity before retrying.");
  }

  function formatTime(value) {
    if (value === null || value === undefined) return "—";
    const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
    return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], { hour12: false }) : String(value);
  }

  function timestamp(value) {
    if (typeof value === "number") return value < 1e12 ? value * 1000 : value;
    return Date.parse(value) || 0;
  }

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = String(content);
    return node;
  }

  function packageId(value) {
    return typeof value === "string" ? value : value?.package_id || value?.id || null;
  }

  function packageAccepted(id) {
    if (!id) return false;
    const rover = state.data?.vehicles?.rover?.state || {};
    const packages = rover.packages;
    const entries = Array.isArray(packages) ? packages : packages && typeof packages === "object" ? Object.entries(packages).map(([key, val]) => typeof val === "object" ? { package_id: key, ...val } : key) : [];
    return packageId(rover.active_package) === id || entries.some((pkg) => packageId(pkg) === id);
  }

  function renderVehicle(name) {
    const vehicle = state.data?.vehicles?.[name];
    const actual = vehicle?.state || {};
    const fresh = vehicleFresh(vehicle);
    const tag = $(`${name}-connection`);
    tag.className = `tag ${fresh ? "online" : "offline"}`;
    tag.textContent = !vehicle?.state ? "UNKNOWN" : fresh ? "LIVE" : "STALE";
    const age = vehicleAge(vehicle);
    text(`${name}-age`, Number.isFinite(age) ? `${age.toFixed(1)} s${fresh ? "" : " · stale"}` : "No telemetry");
    text(`${name}-health`, actual.health && typeof actual.health === "object" ? friendly(actual.health.overall) : friendly(actual.health) === "—" ? (fresh ? "Health not instrumented" : "Awaiting telemetry") : friendly(actual.health));
    text(`${name}-boot`, vehicle?.boot_id);
    if (name === "rover") {
      text("rover-mode", friendly(actual.mode));
      text("rover-moving", actual.moving === undefined ? "Unconfirmed" : actual.moving ? "Moving" : "Stopped");
      text("rover-lease", actual.lease_id ? `Held · ${String(actual.lease_id).slice(0, 9)}` : "None confirmed");
    } else {
      text("drone-flight", friendly(actual.flight_state));
      text("drone-mission", missionNames[actual.mission] || friendly(actual.mission));
      text("drone-product", actual.survey_product ? packageId(actual.survey_product) || "Available" : "None available");
    }
  }

  function renderStatus() {
    const connected = live();
    $("connection-state").classList.toggle("unavailable", !connected);
    text("connection-label", connected ? "C2 connected" : state.lastSuccess ? "C2 unavailable" : "Connecting");
    const vehicles = state.data?.vehicles || {};
    const rover = vehicles.rover?.state || {};
    const health = rover.health && typeof rover.health === "object" ? rover.health : null;
    const elapsed = (Date.now() - state.lastSuccess) / 1000;
    const healthFresh = connected && elapsed < 1 && vehicles.rover?.connected === true && vehicles.rover?.synced === true
      && vehicleAge(vehicles.rover) < 1 && health?.schema_version === 1 && health?.model_id === "ncc-six-wheel-v1"
      && health?.source === "simulation" && health?.stale === false
      && typeof health.age_s === "number" && Number.isFinite(health.age_s) && health.age_s + elapsed < 1;
    const overall = healthFresh && ["nominal", "warning", "critical", "unknown", "stale"].includes(health.overall)
      ? health.overall : health ? "stale" : "unknown";
    text("header-rover-health", overall.toUpperCase());
    $("header-rover-health").className = `health-state ${overall}`;
    const build = state.data?.build;
    const buildLabel = build?.version ? `V${build.version} · ${build.commit || "source archive"}${build.dirty ? " + local changes" : ""}` : "SYSTEMS CONSOLE 02";
    text("console-build", buildLabel);
    text("footer-build", buildLabel);
    window.RoverHealth?.render(state.data, state.lastSuccess, state.httpHealthy);
    $("stale-warning").hidden = connected && vehicleFresh(vehicles.rover) && vehicleFresh(vehicles.drone);
    text("session-id", typeof state.data?.session === "object" ? state.data.session.id || friendly(state.data.session) : state.data?.session || "Awaiting server");
    text("current-mission", missionNames[rover.mission] || friendly(rover.mission));
    text("current-mode", friendly(rover.mode));
    text("active-package", packageId(rover.active_package) || "None confirmed");
    text("fleet-online", `${["rover", "drone"].filter((name) => vehicleFresh(vehicles[name])).length} / 2 live`);
    renderVehicle("rover");
    renderVehicle("drone");
    text("last-refresh", state.lastSuccess ? `Last update ${formatTime(state.lastSuccess)}` : "Waiting for first update");
    const drone = vehicles.drone?.state || {};
    const flight = drone.flight_state;
    let readiness = "Choose the route finding mission, land the drone, and activate an accepted package.";
    if (!vehicleFresh(vehicles.rover) || !vehicleFresh(vehicles.drone)) readiness = "Fresh rover and drone telemetry is required to assess readiness.";
    else if (rover.mission !== "route_finding" || drone.mission !== "route_finding") readiness = "Set both vehicles to autonomous route finding before route execution.";
    else if (flight !== "landed" || drone.at_designated_pad !== true || drone.flight_locked !== true) readiness = "The drone must report a designated landing with its route-finding flight lock engaged.";
    else if (rover.drone_state_fresh !== true) readiness = "Waiting for the rover to confirm its fresh authenticated drone landing report.";
    else if (!rover.active_package) readiness = "Review, transfer, and activate a package before route execution.";
    else if (rover.moving) readiness = "Rover motion is active. Stop before requesting a new route departure.";
    else readiness = "Request route execution; receiver mission, landing, and safety guards still apply.";
    text("route-readiness", readiness);
    refreshAvailability();
  }

  function refreshAvailability() {
    const healthy = live();
    document.querySelectorAll("[data-needs-link]").forEach((button) => { button.disabled = !healthy || state.inFlight.has(button.id); });
    const vehicles = state.data?.vehicles || {};
    const packageLock = packageEditLock();
    const manualPending = state.inFlight.has("manual-pulse") || state.inFlight.has("claim-control");
    const manualAvailable = healthy && vehicleFresh(vehicles.rover) && vehicles.rover?.synced === true;
    $("manual-pulse").disabled = !manualAvailable || manualPending;
    $("claim-control").disabled = !manualAvailable || manualPending;
    $("review-survey").disabled = Boolean(packageLock) || !vehicles.drone?.state?.survey_product;
    $("package-file").disabled = Boolean(packageLock);
    $("package-file-label").setAttribute("aria-disabled", String(Boolean(packageLock)));
    $("transfer-package").disabled = Boolean(packageLock) || !state.reviewedPackage || state.inFlight.has("transfer-package");
    $("activate-package").disabled = Boolean(packageLock) || !packageAccepted(packageId(state.reviewedPackage)) || state.inFlight.has("activate-package");
    text("package-edit-status", packageLock || "Package inputs unlocked. Stop before transferring or activating a package.");
    $("package-edit-status").classList.toggle("package-locked", Boolean(packageLock));
    $("stop-rover").disabled = !state.data?.csrf_token || state.inFlight.has("stop-rover");
  }

  function renderCommands() {
    const reported = Array.isArray(state.data?.commands) ? state.data.commands : [];
    for (const entry of reported) state.pendingCommands.delete(entry.id);
    const commands = [...reported, ...state.pendingCommands.values()].sort((a, b) => timestamp(b.created_at) - timestamp(a.created_at)).slice(0, 50);
    const fingerprint = JSON.stringify(commands);
    if (fingerprint === state.commandFingerprint) return;
    state.commandFingerprint = fingerprint;
    const list = $("command-list");
    list.replaceChildren();
    commands.forEach((entry) => {
      const item = element("li");
      const top = element("div", "command-top");
      top.append(element("span", "command-name", `${actionNames[entry.action] || friendly(entry.action)} · ${entry.vehicle || "vehicle"}`));
      const validStatuses = new Set(["requested", "accepted", "completed", "rejected", "timeout"]);
      const status = validStatuses.has(entry.status) ? entry.status : "unconfirmed";
      top.append(element("span", `command-status ${status}`, status));
      const meta = element("div", "command-meta");
      meta.append(element("code", "command-id", entry.id || "No command ID"), element("time", "", formatTime(entry.created_at)));
      item.append(top, meta);
      if (entry.reason) item.append(element("p", "command-reason", entry.reason));
      list.append(item);
    });
    $("commands-empty").hidden = commands.length > 0;
    text("command-count", `${commands.length} command${commands.length === 1 ? "" : "s"}`);
  }

  function renderEvents() {
    const events = Array.isArray(state.data?.events) ? state.data.events.slice(-40).reverse() : [];
    const fingerprint = JSON.stringify(events);
    if (fingerprint !== state.eventFingerprint) {
      state.eventFingerprint = fingerprint;
      const list = $("event-list");
      list.replaceChildren();
      events.forEach((entry) => {
        const item = element("li");
        item.append(element("time", "", formatTime(entry.time)));
        const severity = ["error", "warning"].includes(entry.level) ? entry.level : "";
        item.append(element("span", `event-message ${severity}`, `${entry.level ? `${entry.level.toUpperCase()} · ` : ""}${entry.message || ""}`));
        list.append(item);
      });
      $("events-empty").hidden = events.length > 0;
    }
    text("network-metrics", state.data?.metrics ? JSON.stringify(state.data.metrics, null, 2) : "No metrics reported");
  }

  function renderFaults(force = false) {
    const faults = state.data?.faults || {};
    const labels = [];
    if (Number(faults.loss)) labels.push(`${Math.round(Number(faults.loss) * 100)}% loss`);
    if (Number(faults.delay_ms)) labels.push(`${faults.delay_ms} ms delay`);
    if (Number(faults.jitter_ms)) labels.push(`${faults.jitter_ms} ms jitter`);
    if (Number(faults.duplicate)) labels.push("duplicates");
    if (Number(faults.reorder)) labels.push("reordering");
    if (faults.disconnect) labels.push("disconnected");
    if (faults.telemetry_only) labels.push("telemetry only");
    if (faults.corrupt_bulk) labels.push("bulk corruption");
    text("fault-summary", labels.join(" · ") || "No injected faults");
    if (force || !state.faultsInitialized || !state.faultFormDirty) {
      for (const [key, id] of Object.entries(faultFields)) {
        if (booleanFields.has(key)) $(id).checked = Boolean(faults[key]);
        else $(id).value = fractionFields.has(key) ? Math.round(Number(faults[key] || 0) * 100) : Number(faults[key] || 0);
      }
      state.faultsInitialized = true;
    }
  }

  function showPackage(pkg) {
    requirePackageEditing();
    if (!pkg || typeof pkg !== "object" || Array.isArray(pkg)) throw new Error("A package must be a JSON object.");
    state.reviewedPackage = JSON.parse(JSON.stringify(pkg));
    $("package-empty").hidden = true;
    $("package-review").hidden = false;
    text("package-badge", "IN REVIEW");
    text("review-package-id", packageId(pkg) || "Missing package ID");
    text("review-version", pkg.version);
    text("review-waypoints", Array.isArray(pkg.waypoints) ? pkg.waypoints.length : "Missing waypoints");
    text("review-crs", pkg.crs || "Unspecified");
    text("review-summary", `${pkg.synthetic === true ? "Marked synthetic" : "Not marked synthetic"} · Source: ${pkg.source || "unspecified"} · Units: ${pkg.units || "unspecified"}. Review all coordinates below; the receiver validates package acceptance.`);
    text("package-json", JSON.stringify(pkg, null, 2));
    renderMap();
    renderTransfers();
    refreshAvailability();
  }

  function renderTransfers() {
    const transfers = Array.isArray(state.data?.transfers) ? state.data.transfers : [];
    const id = packageId(state.reviewedPackage);
    const applicable = id ? transfers.filter((item) => item.package_id === id) : transfers;
    const transfer = applicable.at(-1);
    const accepted = packageAccepted(id);
    if (state.reviewedPackage) {
      const active = packageId(state.data?.vehicles?.rover?.state?.active_package) === id;
      text("package-badge", active ? "ACTIVE" : accepted ? "ACCEPTED" : "IN REVIEW");
      $("package-badge").className = `tag ${accepted ? "online" : "neutral"}`;
    }
    $("transfer-status").hidden = !transfer;
    if (!transfer) return;
    const raw = Number(transfer.progress || 0);
    const progress = Math.round(Math.max(0, Math.min(100, raw <= 1 ? raw * 100 : raw)));
    text("transfer-label", `${transfer.package_id || "Package"} · ${friendly(transfer.status)}`);
    text("transfer-percent", `${progress}%`);
    $("transfer-progress").value = progress;
    $("transfer-progress").textContent = `${progress}%`;
    text("transfer-reason", transfer.reason || (accepted ? "Accepted package is staged at the rover. Explicit activation is required." : "Transfer progress is separate from receiver acceptance."));
  }

  const validPosition = GeoView.validPosition;
  const fieldMap = new GeoView.OfflineMap($("field-map"), {
    status: (value) => { text("map-status", value || "Read-only map · Drag or use arrow keys to pan. Vehicle positions are simulated."); },
    scaleLabel: (value) => text("map-scale", value),
  });
  const droneMap = new GeoView.OfflineMap($("drone-map"), {
    follow: "drone",
    status: (value) => text("drone-map-status", value || "Following reported drone position · Historical overhead imagery, not camera video."),
    scaleLabel: (value) => text("drone-map-scale", value),
  });
  let imagery = null;

  function coordinateLabel(position) {
    return validPosition(position) ? `LAT ${position.lat.toFixed(6)} · LON ${position.lon.toFixed(6)}` : "LAT — · LON —";
  }

  function renderMap() {
    const vehicles = state.data?.vehicles || {};
    const vehicle = vehicles.rover;
    const position = vehicle?.state?.position;
    const drone = vehicles.drone;
    const dronePosition = drone?.state?.position;
    if (vehicle?.boot_id && state.lastBootId !== vehicle.boot_id) {
      state.positions = [];
      state.lastPositionKey = null;
      state.lastBootId = vehicle.boot_id;
    }
    if (validPosition(position)) {
      const key = `${position.lat},${position.lon}`;
      if (key !== state.lastPositionKey) {
        state.positions.push({ lat: position.lat, lon: position.lon });
        state.positions = state.positions.slice(-120);
        state.lastPositionKey = key;
      }
    }
    text("map-position", `ROVER ${coordinateLabel(position)}`);
    text("field-drone-position", `DRONE ${coordinateLabel(dronePosition)}`);
    text("drone-view-position", coordinateLabel(dronePosition));
    text("drone-view-flight", friendly(drone?.state?.flight_state));
    const age = vehicleAge(drone);
    text("drone-view-freshness", Number.isFinite(age)
      ? `${vehicleFresh(drone) ? "Current report" : "STALE · last report"} · ${age.toFixed(1)} s ago` : "Waiting for a report");
    const reviewed = state.reviewedPackage;
    const geographicRoute = reviewed?.crs === "EPSG:4326" && reviewed?.units === "degrees";
    const waypoints = geographicRoute && Array.isArray(reviewed.waypoints) ? reviewed.waypoints.slice(0, 500) : [];
    const scene = {
      rover: { position, fresh: vehicleFresh(vehicle) },
      drone: { position: dronePosition, fresh: vehicleFresh(drone) },
      trail: state.positions,
      waypoints,
      routeWarning: reviewed && !geographicRoute ? "Reviewed route is not WGS84 degrees; it cannot be placed on this map."
        : waypoints.some((point) => !validPosition(point)) ? "Reviewed route contains invalid coordinates; those points are not plotted." : "",
    };
    fieldMap.update(scene);
    droneMap.update({ drone: scene.drone });
  }

  async function loadImagery() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 12000);
    try {
      const response = await fetch("/imagery/metadata.json", { signal: controller.signal });
      if (!response.ok) throw new Error(`Imagery metadata returned HTTP ${response.status}.`);
      imagery = GeoView.validateManifest(await response.json());
      // Decode every stored tile before presenting either georeferenced map.
      // The fetch abort also bounds requests if a static asset becomes unavailable.
      await Promise.all(imagery.tiles.map(async (tile) => {
        const asset = await fetch(tile.path, { signal: controller.signal, cache: "force-cache" });
        if (!asset.ok) throw new Error("A stored satellite tile could not be loaded.");
        const bytes = await asset.arrayBuffer();
        const bitmap = await createImageBitmap(new Blob([bytes], { type: "image/jpeg" }));
        const correctSize = bitmap.width === imagery.tile_size && bitmap.height === imagery.tile_size;
        bitmap.close();
        if (!correctSize) throw new Error("A stored satellite tile has an unexpected size.");
      }));
      fieldMap.setManifest(imagery);
      droneMap.setManifest(imagery);
      text("imagery-location", imagery.name || "Stored satellite coverage");
      text("imagery-source", `${imagery.year} historical mosaic · ${imagery.resolution_m} m source imagery. ${imagery.attribution.replace(/\.$/, "")}. Historical context only; not a verified navigation map.`);
      text("drone-view-source", imagery.name || `${imagery.year} historical satellite mosaic`);
      $("map-empty").hidden = true;
      $("drone-map-empty").hidden = true;
      for (const id of ["map-zoom-in", "map-zoom-out", "map-reset"]) $(id).disabled = false;
      renderMap();
    } catch (error) {
      imagery = null;
      text("map-load-status", "Historical imagery unavailable. Check the locally stored imagery files.");
      text("drone-map-load-status", "Historical imagery unavailable. Drone camera remains disconnected.");
      text("imagery-location", "Stored imagery unavailable");
      text("imagery-source", "No substitute terrain is displayed. Vehicle telemetry remains available.");
      text("map-status", error.name === "AbortError" ? "Loading local imagery timed out." : error.message);
    } finally { clearTimeout(timer); }
  }

  $("map-zoom-in").addEventListener("click", () => fieldMap.zoom(1.5));
  $("map-zoom-out").addEventListener("click", () => fieldMap.zoom(1 / 1.5));
  $("map-reset").addEventListener("click", () => fieldMap.reset());
  function selectDroneTab(camera, focus = false) {
    $("drone-camera-panel").hidden = !camera;
    $("drone-map-panel").hidden = camera;
    for (const [id, selected] of [["drone-map-tab", !camera], ["drone-camera-tab", camera]]) {
      $(id).setAttribute("aria-selected", String(selected));
      $(id).tabIndex = selected ? 0 : -1;
      if (selected && focus) $(id).focus();
    }
    if (!camera) droneMap.render();
  }
  $("drone-map-tab").addEventListener("click", () => selectDroneTab(false));
  $("drone-camera-tab").addEventListener("click", () => selectDroneTab(true));
  for (const id of ["drone-map-tab", "drone-camera-tab"]) {
    $(id).addEventListener("keydown", (event) => {
      if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        selectDroneTab(event.key === "End" || (!["Home", "End"].includes(event.key) && id === "drone-map-tab"), true);
      }
    });
  }

  const workspaces = {
    overview: { title: "Mission operations", description: "Field position, vehicle telemetry and command authority." },
    health: { title: "Rover systems", description: "Component health, power distribution and observed sensor data." },
    drone: { title: "Drone operations", description: "Position, camera connection and survey controls." },
    routes: { title: "Route planning", description: "Review, transfer and activate a route before departure." },
    network: { title: "Network diagnostics", description: "Test the simulated link and inspect reported events." },
  };
  const workspaceTabs = [...document.querySelectorAll("[data-nav-view]")];

  function selectWorkspace(name, { history = false, focus = false } = {}) {
    const view = Object.hasOwn(workspaces, name) ? name : "health";
    const focusedPanel = document.activeElement?.closest("[data-workspace-view]");
    document.querySelectorAll("[data-workspace-view]").forEach((panel) => {
      panel.hidden = panel.dataset.workspaceView !== view;
    });
    workspaceTabs.forEach((tab) => {
      const selected = tab.dataset.navView === view;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    text("workspace-title", workspaces[view].title);
    text("workspace-description", workspaces[view].description);
    document.title = `${workspaces[view].title} · NCC rover operations`;
    if (history && window.location.hash !== `#${view}`) {
      window.history.pushState(null, "", `#${view}`);
      window.scrollTo({ top: 0, behavior: "instant" });
    }
    if (focus || (focusedPanel && focusedPanel.hidden)) $("workspace-title").focus({ preventScroll: true });
    // A previously hidden SVG needs its visible dimensions before projection.
    requestAnimationFrame(() => { fieldMap.render(); droneMap.render(); window.RoverHealth?.onViewChange?.(); });
  }

  workspaceTabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectWorkspace(tab.dataset.navView, { history: true }));
    tab.addEventListener("keydown", (event) => {
      let target;
      if (["ArrowRight", "ArrowDown"].includes(event.key)) target = (index + 1) % workspaceTabs.length;
      else if (["ArrowLeft", "ArrowUp"].includes(event.key)) target = (index - 1 + workspaceTabs.length) % workspaceTabs.length;
      else if (event.key === "Home") target = 0;
      else if (event.key === "End") target = workspaceTabs.length - 1;
      else return;
      event.preventDefault();
      workspaceTabs[target].focus();
      selectWorkspace(workspaceTabs[target].dataset.navView, { history: true });
    });
  });
  document.querySelectorAll("[data-open-view]").forEach((button) => {
    button.addEventListener("click", () => selectWorkspace(button.dataset.openView, { history: true, focus: true }));
  });
  document.querySelector(".skip-link").addEventListener("click", (event) => {
    event.preventDefault();
    $("main").tabIndex = -1;
    $("main").focus();
  });
  window.addEventListener("popstate", () => selectWorkspace(window.location.hash.slice(1)));
  window.addEventListener("hashchange", () => selectWorkspace(window.location.hash.slice(1)));
  $("workspace-nav").setAttribute("aria-orientation", "horizontal");
  window.RoverHealth?.init({ post, command, message });
  selectWorkspace(window.location.hash.slice(1));

  async function poll() {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    try {
      const response = await fetch("/api/state", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!data || typeof data !== "object" || !data.vehicles) throw new Error("Invalid state response");
      if (state.data?.session && data.session !== state.data.session) {
        state.pendingCommands.clear();
        state.reviewedPackage = null;
        $("package-review").hidden = true;
        $("package-empty").hidden = false;
        text("package-badge", "NO REVIEW");
        message("The C2 session changed. Review the current telemetry and load a package again before operating.");
      }
      state.data = data;
      state.lastSuccess = Date.now();
      state.httpHealthy = true;
      renderStatus();
      renderCommands();
      renderEvents();
      renderFaults();
      renderTransfers();
      renderMap();
    } catch (error) {
      state.httpHealthy = false;
      renderStatus();
    } finally {
      clearTimeout(timeout);
      setTimeout(poll, 400);
    }
  }

  function onCommand(id, vehicle, action, args = () => ({})) {
    $(id).addEventListener("click", () => withButton(id, () => command(vehicle, action, args())));
  }

  onCommand("stop-rover", "rover", "STOP");
  onCommand("claim-control", "rover", "CLAIM_CONTROL");
  $("manual-pulse").addEventListener("click", () => withButton("manual-pulse", async () => {
    const speed = Number($("manual-speed").value);
    if (!$("manual-speed").checkValidity() || !Number.isFinite(speed)) throw new Error("Choose a forward speed between 0 and 1.");
    const session = state.data?.session;
    const bootId = state.data?.vehicles?.rover?.boot_id;
    const claim = await command("rover", "CLAIM_CONTROL");
    const granted = await waitForConfirmed((completed) => {
      const rover = state.data?.vehicles?.rover;
      if (state.data?.session !== session || rover?.boot_id !== bootId) {
        throw new Error("The rover or C2 session changed. Manual pulse was not sent; request control again after reconciliation.");
      }
      return vehicleFresh(rover) && rover.synced === true && completed.vehicle === "rover"
        && completed.action === "CLAIM_CONTROL" && completed.boot_id === bootId
        && typeof completed.result?.lease_id === "string" && /^[a-f0-9]{24}$/.test(completed.result.lease_id);
    }, claim.id, 3500);
    // Use this claim's authenticated ACK token, never a different claim's
    // telemetry token. Receiver-local expiry remains authoritative and unchanged.
    await command("rover", "MANUAL", { speed, lease_id: granted.result.lease_id });
  }));
  onCommand("drone-takeoff", "drone", "DRONE_TAKEOFF");
  onCommand("drone-survey", "drone", "DRONE_SURVEY");
  onCommand("drone-land", "drone", "DRONE_LAND");
  onCommand("start-route", "rover", "START_ROUTE");
  onCommand("recover-route", "rover", "RECOVER_ROUTE");
  onCommand("activate-package", "rover", "ACTIVATE_PACKAGE", () => {
    requirePackageEditing();
    return { package_id: packageId(state.reviewedPackage) };
  });

  // Holding Enter must not turn a bounded pulse into repeated motion requests.
  document.querySelectorAll("button").forEach((button) => {
    button.addEventListener("keydown", (event) => {
      if (event.repeat && (event.key === "Enter" || event.key === " ")) event.preventDefault();
    });
  });

  $("set-mission").addEventListener("click", () => withButton("set-mission", async () => {
    const mission = $("mission-select").value;
    const roverResult = await command("rover", "SET_MISSION", { mission });
    await waitForConfirmed(() => vehicleFresh(state.data?.vehicles?.rover) && state.data.vehicles.rover.state.mission === mission, roverResult.id);
    // Allow the confirmed rover context to reach the drone's own interlock.
    await new Promise((resolve) => setTimeout(resolve, 650));
    const droneResult = await command("drone", "SET_MISSION", { mission });
    const rejected = roverResult.status === "rejected" || droneResult.status === "rejected";
    message(rejected ? "A mission request was rejected. Inspect both outcomes before operating." : `${missionNames[mission]} requested for both vehicles. Confirm each vehicle's mission in telemetry.`, rejected);
  }));

  $("review-survey").addEventListener("click", () => {
    try { showPackage(state.data?.vehicles?.drone?.state?.survey_product); }
    catch (error) { message(error.message, true); }
  });

  $("package-file").addEventListener("change", async (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      requirePackageEditing();
      if (file.size > 1024 * 1024) throw new Error("Choose a JSON package smaller than 1 MiB.");
      showPackage(JSON.parse(await file.text()));
      message(`Loaded ${file.name} for local review. No package has been sent by this action.`);
    } catch (error) { message(error instanceof SyntaxError ? "This file is not valid JSON." : error.message, true); }
    finally { event.target.value = ""; }
  });

  $("transfer-package").addEventListener("click", () => withButton("transfer-package", async () => {
    requirePackageEditing();
    if (!state.reviewedPackage) throw new Error("Review a package before transfer.");
    const result = await post("/api/transfer", { package: state.reviewedPackage });
    const transfer = result.transfer || result;
    message(`Package transfer requested${transfer.id ? ` (${transfer.id})` : ""}. Receiver acceptance and activation are separate steps.`);
  }));

  $("fault-form").addEventListener("input", () => { state.faultFormDirty = true; });
  $("fault-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!$("fault-form").reportValidity()) return;
    const faults = {};
    for (const [key, id] of Object.entries(faultFields)) {
      faults[key] = booleanFields.has(key) ? $(id).checked : Number($(id).value) / (fractionFields.has(key) ? 100 : 1);
    }
    try {
      await post("/api/faults", faults);
      state.faultFormDirty = false;
      message("Network fault configuration requested. The diagnostics summary shows the server's reported configuration.");
    } catch (error) { message(error.message, true); }
  });

  $("reset-faults").addEventListener("click", () => withButton("reset-faults", async () => {
    const faults = Object.fromEntries(Object.keys(faultFields).map((key) => [key, booleanFields.has(key) ? false : 0]));
    await post("/api/faults", faults);
    state.faultFormDirty = false;
    message("Fault reset requested. Awaiting the server's confirmed link configuration.");
  }));

  setInterval(() => { renderStatus(); renderMap(); }, 250);
  loadImagery();
  poll();
})();
