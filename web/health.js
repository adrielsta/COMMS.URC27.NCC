"use strict";

// Browser observation of receiver-reported engineering telemetry. This module
// never manufactures readings or treats HTTP reachability as vehicle health.
(() => {
  const STALE_MS = 1000;
  const HISTORY_LIMIT = 120;
  const CHANNELS = [
    { id: "voltage_v", name: "Voltage", unit: "V", digits: 2 },
    { id: "current_a", name: "Current", unit: "A", digits: 2 },
    { id: "temperature_c", name: "Temperature", unit: "°C", digits: 1 },
  ];
  const TEMPLATE = [
    ["battery", "Battery pack", "Power"], ["pdu", "Power distribution", "Power"],
    ["drive_fl", "Front left drive", "Drive"], ["drive_ml", "Middle left drive", "Drive"],
    ["drive_rl", "Rear left drive", "Drive"], ["drive_fr", "Front right drive", "Drive"],
    ["drive_mr", "Middle right drive", "Drive"], ["drive_rr", "Rear right drive", "Drive"],
    ["compute", "Onboard computer", "Avionics"], ["radio", "Communications radio", "Avionics"],
    ["gnss", "GNSS receiver", "Avionics"], ["camera", "Navigation camera", "Avionics"],
    ["arm", "Manipulator", "Payload"], ["science", "Science payload", "Payload"],
  ].map(([id, name, group]) => ({ id, name, group, dependencies: [], limits: {} }));
  const STATUS = new Set(["nominal", "warning", "critical", "unknown", "stale"]);
  const FAULTS = [
    ["power_loss", "Power loss"], ["overtemp", "Overtemperature"],
    ["overcurrent", "Overcurrent"], ["sensor_loss", "Sensor loss"],
  ];
  let root = null;
  let hooks = {};
  let anatomy = null;
  let catalog = TEMPLATE;
  let catalogReady = false;
  let catalogLoading = false;
  let selected = "battery";
  let currentTab = "anatomy";
  let latest = null;
  let lastSuccess = 0;
  let httpHealthy = false;
  let fresh = false;
  let wasFresh = false;
  let bootId = null;
  let sampleKey = null;
  let sampleCount = 0;
  let windowStart = Date.now();
  let lastSampleAt = null;
  let lastAlarmFingerprint = "";
  let busy = false;
  let statusById = {};
  const statistics = new Map();
  const sensorRows = new Map();
  const rosterButtons = new Map();
  const pendingAcks = new Set();
  const collapsedComponents = new Set();
  const $ = (id) => document.getElementById(id);
  const finite = (value) => typeof value === "number" && Number.isFinite(value);
  const human = (value) => String(value || "unknown").replaceAll("_", " ");
  const number = (value, digits = 2) => finite(value) ? value.toFixed(digits) : "—";
  const setText = (node, value) => { if (node && node.textContent !== String(value)) node.textContent = String(value); };

  function element(tag, className, content) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (content !== undefined) node.textContent = String(content);
    return node;
  }

  function svgElement(tag, attributes = {}) {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
    return node;
  }

  function utc(value) {
    if (value === null || value === undefined) return "—";
    const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
    return Number.isFinite(date.getTime()) ? date.toISOString().slice(11, 19) + " UTC" : "—";
  }

  function healthData() { return latest?.vehicles?.rover?.state?.health; }
  function metricKey(component, channel) { return `${component}:${channel}`; }

  function classification(component) {
    if (!fresh) return healthData() ? "stale" : "unknown";
    const status = component?.status;
    return STATUS.has(status) ? status : "unknown";
  }

  function valueOf(component, channel) {
    const state = classification(component);
    if (!fresh || state === "unknown" || state === "stale") return null;
    return finite(component?.[channel]) ? component[channel] : null;
  }

  function measurementState(component, channel) {
    const state = classification(component);
    return finite(valueOf(component, channel)) ? state : state === "stale" ? "stale" : "unknown";
  }

  function metricStatistics(component, channel) {
    const key = metricKey(component, channel);
    if (!statistics.has(key)) statistics.set(key, { n: 0, sum: 0, min: Infinity, max: -Infinity, history: [] });
    return statistics.get(key);
  }

  function addPoint(stats, time, value) {
    stats.history.push({ time, value });
    if (stats.history.length > HISTORY_LIMIT) stats.history.shift();
    if (finite(value)) {
      stats.n += 1;
      stats.sum += value;
      stats.min = Math.min(stats.min, value);
      stats.max = Math.max(stats.max, value);
    }
  }

  function resetStatistics(announce = false) {
    statistics.clear();
    sampleKey = null;
    sampleCount = 0;
    windowStart = Date.now();
    lastSampleAt = null;
    if (announce) report("Browser observation statistics reset. Vehicle state and alarms are unchanged.");
  }

  function observe(now) {
    const rover = latest?.vehicles?.rover;
    if (rover?.boot_id && bootId !== rover.boot_id) {
      bootId = rover.boot_id;
      resetStatistics();
    }
    if (wasFresh && !fresh) {
      for (const stat of statistics.values()) addPoint(stat, now, null);
    }
    wasFresh = fresh;
    const health = healthData();
    if (!fresh || !Number.isInteger(health?.seq)) return;
    const key = `${bootId}:${health.seq}`;
    if (key === sampleKey) return;
    sampleKey = key;
    sampleCount += 1;
    lastSampleAt = now;
    for (const component of catalog) {
      const reported = health.components?.[component.id];
      for (const channel of CHANNELS) {
        addPoint(metricStatistics(component.id, channel.id), now, valueOf(reported, channel.id));
      }
    }
  }

  function limitsFor(component, channel) {
    const limits = component?.limits?.[channel] || {};
    if (Array.isArray(limits)) return { min: limits[0], max: limits[1] };
    return limits;
  }

  function limitText(component, channel) {
    const limits = limitsFor(component, channel.id);
    if (finite(limits.warning) && finite(limits.critical)) return `WARN ${number(limits.warning, 1)} / CRIT ${number(limits.critical, 1)} ${channel.unit}`;
    const min = limits.min ?? limits.warning_min;
    const max = limits.max ?? limits.warning_max;
    if (finite(min) && finite(max)) return `${number(min, 1)}–${number(max, 1)} ${channel.unit}`;
    if (finite(max)) return `≤ ${number(max, 1)} ${channel.unit}`;
    if (finite(min)) return `≥ ${number(min, 1)} ${channel.unit}`;
    return "Not configured";
  }

  function report(text, error = false) {
    setText($("health-feedback"), text);
    $("health-feedback").classList.toggle("is-error", error);
    hooks.message?.(text, error);
  }

  function build() {
    root.classList.add("rover-health");
    root.innerHTML = `
      <div class="health-toolbar">
        <div class="health-tabs" role="tablist" aria-label="Engineering display">
          <button id="health-tab-anatomy" type="button" role="tab" aria-selected="true" aria-controls="health-anatomy-panel" data-health-tab="anatomy">Anatomy</button>
          <button id="health-tab-sensors" type="button" role="tab" aria-selected="false" aria-controls="health-sensors-panel" tabindex="-1" data-health-tab="sensors">Sensors</button>
        </div>
        <div class="health-source"><span class="health-sim">SIMULATED TELEMETRY</span><span>ILLUSTRATIVE SIX-WHEEL TEMPLATE</span></div>
      </div>
      <div class="health-readout-strip" aria-label="Engineering telemetry summary">
        <div><span>HEALTH CHANNEL</span><strong id="health-link" data-status="unknown">AWAITING DATA</strong></div>
        <div><span>POWER BUS</span><strong id="health-bus">— <small>V</small></strong></div>
        <div><span>REPORTED NODES</span><strong id="health-node-count">0 / 14</strong></div>
        <div><span>ACTIVE ALARMS</span><strong id="health-alarm-count">—</strong></div>
        <div><span>LAST OBSERVED</span><strong id="health-last-observed">—</strong></div>
      </div>
      <p class="health-data-notice" id="health-data-notice">Waiting for rover health telemetry. No physical hardware is connected.</p>
      <p class="health-catalog-notice" id="health-catalog-notice">Loading subsystem definitions… <button id="health-catalog-retry" type="button" hidden>Retry catalog</button></p>
      <div id="health-active-strip" class="health-active-strip" hidden><div><strong id="health-active-heading"></strong><p id="health-active-summary"></p></div><button type="button" id="health-review-alarms">Review alarms ↓</button></div>
      <div id="health-anatomy-panel" role="tabpanel" aria-labelledby="health-tab-anatomy" class="health-anatomy-layout">
        <aside class="health-roster" aria-label="Rover subsystems"><div class="health-section-heading"><h2>Subsystems</h2><span>14 NODES</span></div><div id="health-component-list"></div></aside>
        <section class="health-figure-panel" aria-label="Interactive rover anatomy">
          <div class="health-section-heading"><h2>Vehicle anatomy</h2><label class="health-layer-label">Layer <select id="health-layer"><option value="all">All systems</option><option value="power">Power</option><option value="drive">Drive</option><option value="avionics">Avionics</option><option value="payload">Payload</option></select></label></div>
          <div id="health-anatomy"></div>
          <div class="health-figure-footer"><p>Select a component to inspect its telemetry.</p><div class="health-legend" aria-label="Subsystem status legend"><span data-status="nominal">Nominal</span><span data-status="warning">Warning</span><span data-status="critical">Critical</span><span data-status="unknown">Unknown</span><span data-status="stale">Stale</span></div></div>
        </section>
        <aside class="health-inspector" aria-labelledby="health-selected-name">
          <div class="health-section-heading"><span id="health-selected-group">POWER</span><span id="health-selected-status" class="health-status" data-status="unknown">UNKNOWN</span></div>
          <div class="health-inspector-title"><h2 id="health-selected-name" tabindex="-1">Battery pack</h2><span id="health-selected-id">battery</span></div>
          <dl class="health-component-facts"><div><dt>Power state</dt><dd id="health-selected-power">Unknown</dd></div><div><dt>Supply path</dt><dd id="health-selected-dependencies">Awaiting catalog</dd></div><div><dt>Reported fault</dt><dd id="health-selected-fault">Unknown</dd></div></dl>
          <div id="health-trends" class="health-trends"></div>
          <p class="health-chart-note">Observed readings · latest 120 samples. Gaps indicate unavailable data.</p>
          <div class="health-limit-heading">MODEL OPERATING LIMITS <span>ILLUSTRATIVE</span></div><dl id="health-selected-limits" class="health-component-facts"></dl>
        </aside>
      </div>
      <section id="health-sensors-panel" role="tabpanel" aria-labelledby="health-tab-sensors" hidden>
        <div class="health-sensor-toolbar"><div><h2>Sensor register</h2><p>Double-click a reading to inspect its component and trends.</p></div><label>Subsystem group <select id="health-sensor-group"><option value="all">All systems</option></select></label></div>
        <div class="health-table-scroll" tabindex="0" role="region" aria-label="Sensor register, scroll horizontally for statistics">
          <table class="health-sensor-table"><thead><tr><th scope="col">Subsystem / sensor</th><th scope="col">Current</th><th scope="col">Minimum</th><th scope="col">Maximum</th><th scope="col">Average</th><th scope="col">Samples</th><th scope="col">Model limits</th><th scope="col">State</th></tr></thead><tbody id="health-sensor-body"></tbody></table>
        </div>
      </section>
      <div class="health-observation-bar"><p id="health-observation-window">Observation window not started.</p><div><button type="button" id="health-reset-stats">Reset statistics</button><button type="button" id="health-export">Export sensor CSV</button></div></div>
      <section class="health-alarms" aria-labelledby="health-alarm-heading"><div class="health-section-heading"><h2 id="health-alarm-heading" tabindex="-1">Fault annunciator</h2><span id="health-alarm-summary">AWAITING DATA</span></div><p class="health-alarm-help">Acknowledge records operator review. An active fault remains until rover telemetry confirms recovery.</p><div id="health-alarm-list"></div></section>
      <details class="health-engineering"><summary>Simulator fault controls <span>ENGINEERING TEST</span></summary><div class="health-fault-controls"><p>Inject a fault into the simulated rover. Power supply failures propagate to dependent components.</p><label>Component<select id="health-fault-component"></select></label><label>Fault<select id="health-fault-type"></select></label><button id="health-inject" type="button">Apply fault</button><button id="health-clear" type="button">Clear selected fault</button></div></details>
      <p id="health-feedback" class="health-feedback" role="status" aria-live="polite"></p>
    `;
    for (const button of root.querySelectorAll("[data-health-tab]")) {
      button.addEventListener("click", () => changeTab(button.dataset.healthTab));
      button.addEventListener("keydown", (event) => {
        if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? "anatomy" : event.key === "End" ? "sensors" : currentTab === "anatomy" ? "sensors" : "anatomy";
        changeTab(next);
        $(`health-tab-${next}`).focus();
      });
    }
    $("health-layer").addEventListener("change", (event) => anatomy?.setLayer(event.target.value));
    $("health-sensor-group").addEventListener("change", filterSensors);
    $("health-reset-stats").addEventListener("click", () => { resetStatistics(true); render(latest, lastSuccess, httpHealthy); });
    $("health-export").addEventListener("click", exportCSV);
    $("health-catalog-retry").addEventListener("click", loadCatalog);
    $("health-review-alarms").addEventListener("click", () => { $("health-alarm-heading").focus({ preventScroll: true }); $("health-alarm-heading").scrollIntoView({ block: "center" }); });
    $("health-inject").addEventListener("click", () => injectFault($("health-fault-type").value));
    $("health-clear").addEventListener("click", () => injectFault("clear"));
    for (const [id, name] of FAULTS) {
      const option = element("option", "", name);
      option.value = id;
      $("health-fault-type").append(option);
    }
    for (const channel of CHANNELS) {
      const panel = element("div", "health-trend");
      const heading = element("div", "health-trend-heading");
      heading.append(element("span", "", channel.name));
      const value = element("strong", "", "—");
      value.id = `health-trend-value-${channel.id}`;
      heading.append(value);
      const svg = svgElement("svg", { viewBox: "0 0 260 64", role: "img", "aria-label": `${channel.name}: no observed readings` });
      svg.id = `health-trend-${channel.id}`;
      panel.append(heading, svg);
      $("health-trends").append(panel);
    }
    buildCatalogViews();
    if (window.RoverAnatomy?.mount) anatomy = window.RoverAnatomy.mount($("health-anatomy"), { onSelect: selectComponent });
    else $("health-anatomy").append(element("p", "health-empty", "Anatomy renderer unavailable. The sensor register remains available."));
    anatomy?.select(selected);
  }

  function changeTab(tab) {
    currentTab = tab;
    for (const name of ["anatomy", "sensors"]) {
      const button = $(`health-tab-${name}`);
      button.setAttribute("aria-selected", String(name === tab));
      button.tabIndex = name === tab ? 0 : -1;
      $(`health-${name}-panel`).hidden = name !== tab;
    }
  }

  function buildCatalogViews() {
    rosterButtons.clear();
    sensorRows.clear();
    $("health-component-list").replaceChildren();
    $("health-sensor-body").replaceChildren();
    $("health-fault-component").replaceChildren();
    const groups = [...new Set(catalog.map((item) => item.group))];
    const groupSelect = $("health-sensor-group");
    const existingFilter = groupSelect.value;
    groupSelect.replaceChildren();
    const all = element("option", "", "All systems");
    all.value = "all";
    groupSelect.append(all);
    for (const group of groups) {
      const option = element("option", "", human(group));
      option.value = group;
      groupSelect.append(option);
      const groupElement = element("div", "health-roster-group");
      groupElement.append(element("h3", "", human(group)));
      for (const component of catalog.filter((item) => item.group === group)) {
        const button = element("button", "health-component-button");
        button.type = "button";
        button.dataset.component = component.id;
        button.dataset.status = "unknown";
        button.setAttribute("aria-pressed", String(component.id === selected));
        button.append(element("span", "health-component-indicator"), element("span", "", component.name));
        const status = element("span", "sr-only", "Unknown");
        button.append(status);
        button.addEventListener("click", () => selectComponent(component.id));
        rosterButtons.set(component.id, { button, status });
        groupElement.append(button);
      }
      $("health-component-list").append(groupElement);
    }
    if (groups.includes(existingFilter)) groupSelect.value = existingFilter;
    for (const component of catalog) {
      const option = element("option", "", component.name);
      option.value = component.id;
      $("health-fault-component").append(option);
      const heading = element("tr", "health-sensor-component-heading");
      heading.dataset.group = component.group;
      heading.dataset.component = component.id;
      const headingCell = element("th");
      headingCell.colSpan = 8;
      headingCell.scope = "rowgroup";
      const expand = element("button", "health-sensor-expand", `${collapsedComponents.has(component.id) ? "+" : "−"} ${component.name}`);
      expand.type = "button";
      expand.setAttribute("aria-expanded", String(!collapsedComponents.has(component.id)));
      expand.addEventListener("click", () => {
        if (collapsedComponents.has(component.id)) collapsedComponents.delete(component.id);
        else collapsedComponents.add(component.id);
        expand.setAttribute("aria-expanded", String(!collapsedComponents.has(component.id)));
        setText(expand, `${collapsedComponents.has(component.id) ? "+" : "−"} ${component.name}`);
        filterSensors();
      });
      const inspect = element("button", "health-sensor-inspect", "Inspect ↗");
      inspect.type = "button";
      inspect.setAttribute("aria-label", `Inspect ${component.name} and trends`);
      inspect.addEventListener("click", () => inspectComponent(component.id));
      headingCell.append(expand, element("span", "health-sensor-group-label", human(component.group)), inspect);
      heading.append(headingCell);
      $("health-sensor-body").append(heading);
      CHANNELS.forEach((channel, index) => {
        const row = element("tr", index === 0 ? "health-sensor-first" : "");
        row.dataset.group = component.group;
        row.dataset.component = component.id;
        row.dataset.channel = channel.id;
        row.addEventListener("dblclick", () => inspectComponent(component.id));
        const label = element("th");
        label.scope = "row";
        label.append(element("span", "health-sensor-channel", `${channel.name} (${channel.unit})`));
        row.append(label);
        const cells = {};
        for (const field of ["current", "min", "max", "average", "samples", "limits", "state"]) {
          cells[field] = element("td", `health-cell-${field}`, "—");
          row.append(cells[field]);
        }
        setText(cells.limits, limitText(component, channel));
        sensorRows.set(metricKey(component.id, channel.id), cells);
        $("health-sensor-body").append(row);
      });
    }
    $("health-fault-component").value = selected;
    filterSensors();
  }

  function filterSensors() {
    const group = $("health-sensor-group").value;
    for (const row of $("health-sensor-body").children) row.hidden = (group !== "all" && row.dataset.group !== group) || Boolean(row.dataset.channel && collapsedComponents.has(row.dataset.component));
  }

  function inspectComponent(id) {
    selectComponent(id);
    changeTab("anatomy");
    $("health-selected-name").focus({ preventScroll: true });
    $("health-selected-name").scrollIntoView({ block: "nearest" });
  }

  async function loadCatalog() {
    if (catalogLoading) return;
    catalogLoading = true;
    $("health-catalog-retry").disabled = true;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 7000);
    try {
      const response = await fetch("/api/health/catalog", { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const data = await response.json();
      if (!Array.isArray(data.components) || data.schema_version !== 1 || data.model_id !== "ncc-six-wheel-v1" || data.source !== "simulation" || data.illustrative !== true) throw new Error("Unrecognized model catalog");
      const valid = data.components.filter((item) => item && TEMPLATE.some((base) => base.id === item.id) && typeof item.name === "string" && typeof item.group === "string" && Array.isArray(item.dependencies) && item.dependencies.every((id) => TEMPLATE.some((base) => base.id === id)) && item.limits && typeof item.limits === "object");
      if (valid.length !== TEMPLATE.length || new Set(valid.map((item) => item.id)).size !== TEMPLATE.length) throw new Error("Incomplete model catalog");
      catalog = valid;
      catalogReady = true;
      buildCatalogViews();
      $("health-catalog-notice").hidden = true;
      render(latest, lastSuccess, httpHealthy);
    } catch (error) {
      $("health-catalog-notice").firstChild.textContent = "Subsystem catalog unavailable. Model limits and supply paths are unverified. ";
      $("health-catalog-retry").hidden = false;
    } finally {
      clearTimeout(timer);
      catalogLoading = false;
      $("health-catalog-retry").disabled = false;
    }
  }

  function selectComponent(id) {
    if (!catalog.some((component) => component.id === id)) return;
    selected = id;
    anatomy?.select(id);
    $("health-fault-component").value = id;
    for (const [componentId, { button }] of rosterButtons) button.setAttribute("aria-pressed", String(componentId === id));
    renderInspector();
  }

  function renderChart(channel) {
    const svg = $(`health-trend-${channel.id}`);
    const stat = statistics.get(metricKey(selected, channel.id));
    const history = stat?.history || [];
    const values = history.map((point) => point.value).filter(finite);
    svg.replaceChildren();
    svg.append(svgElement("path", { d: "M0 8H260 M0 52H260", class: "health-chart-grid" }));
    if (!values.length) {
      const label = svgElement("text", { x: 0, y: 34, class: "health-chart-empty" });
      label.textContent = "NO OBSERVED READINGS";
      svg.append(label);
      svg.setAttribute("aria-label", `${channel.name}: no observed readings`);
      return;
    }
    const min = Math.min(...values);
    const max = Math.max(...values);
    const range = max - min || Math.max(Math.abs(max) * 0.1, 1);
    const low = min === max ? min - range / 2 : min;
    const last = history.at(-1).time;
    const first = history[0].time;
    const span = Math.max(last - first, 1000);
    let points = [];
    const flush = () => {
      if (points.length === 1) svg.append(svgElement("circle", { cx: points[0][0], cy: points[0][1], r: 2, class: "health-chart-point" }));
      if (points.length > 1) svg.append(svgElement("polyline", { points: points.map((point) => point.join(",")).join(" "), class: "health-chart-line" }));
      points = [];
    };
    for (const point of history) {
      if (!finite(point.value)) { flush(); continue; }
      points.push([2 + (point.time - first) / span * 256, 52 - (point.value - low) / range * 44]);
    }
    flush();
    const rangeLabel = svgElement("text", { x: 258, y: 63, "text-anchor": "end", class: "health-chart-range" });
    rangeLabel.textContent = `${number(min, channel.digits)}–${number(max, channel.digits)} ${channel.unit}`;
    svg.append(rangeLabel);
    svg.classList.toggle("is-historical", !fresh);
    svg.setAttribute("aria-label", `${channel.name}, ${values.length} observed readings, minimum ${number(min, channel.digits)}, maximum ${number(max, channel.digits)} ${channel.unit}${fresh ? "" : ", historical, telemetry unavailable"}`);
  }

  function renderInspector() {
    if (!root) return;
    const component = catalog.find((item) => item.id === selected) || TEMPLATE[0];
    const reported = healthData()?.components?.[selected];
    const status = classification(reported);
    setText($("health-selected-name"), component.name);
    setText($("health-selected-id"), selected);
    setText($("health-selected-group"), human(component.group).toUpperCase());
    setText($("health-selected-status"), status.toUpperCase());
    $("health-selected-status").dataset.status = status;
    setText($("health-selected-power"), fresh && typeof reported?.powered === "boolean" ? reported.powered ? "Powered" : "Unpowered" : "Unknown");
    setText($("health-selected-dependencies"), !catalogReady ? "Unverified" : component.dependencies?.length ? component.dependencies.map((id) => catalog.find((item) => item.id === id)?.name || id).join(" → ") : "Primary source");
    setText($("health-selected-fault"), fresh && reported ? reported.fault ? human(reported.fault) : "None reported" : "Unknown");
    $("health-selected-limits").replaceChildren();
    for (const channel of CHANNELS) {
      setText($(`health-trend-value-${channel.id}`), `${number(valueOf(reported, channel.id), channel.digits)} ${channel.unit}`);
      renderChart(channel);
      const row = element("div");
      row.append(element("dt", "", channel.name), element("dd", "", limitText(component, channel)));
      $("health-selected-limits").append(row);
    }
  }

  function renderSensors() {
    const components = healthData()?.components || {};
    for (const component of catalog) {
      for (const channel of CHANNELS) {
        const cells = sensorRows.get(metricKey(component.id, channel.id));
        const stat = statistics.get(metricKey(component.id, channel.id));
        setText(cells.current, number(valueOf(components[component.id], channel.id), channel.digits));
        setText(cells.min, number(stat?.n ? stat.min : null, channel.digits));
        setText(cells.max, number(stat?.n ? stat.max : null, channel.digits));
        setText(cells.average, number(stat?.n ? stat.sum / stat.n : null, channel.digits));
        setText(cells.samples, stat?.n || 0);
        const state = measurementState(components[component.id], channel.id);
        setText(cells.state, state.toUpperCase());
        cells.state.dataset.status = state;
        cells.current.dataset.status = state;
      }
    }
  }

  function alarms() { return Array.isArray(latest?.health_monitor?.alarms) ? latest.health_monitor.alarms : []; }

  function renderAlarms() {
    const list = alarms();
    const active = list.filter((alarm) => alarm.active === true);
    const unacknowledged = active.filter((alarm) => alarm.acknowledged !== true);
    $("health-active-strip").hidden = active.length === 0;
    $("health-active-strip").dataset.status = active.some((alarm) => alarm.severity === "critical") ? "critical" : "warning";
    setText($("health-active-heading"), `${active.length} ACTIVE ${active.length === 1 ? "ALARM" : "ALARMS"}${fresh ? "" : " · STATUS UNCONFIRMED"}`);
    const summaries = active.slice(0, 3).map((alarm) => `${catalog.find((component) => component.id === alarm.component)?.name || human(alarm.component)}: ${human(alarm.code)} (${fresh && alarm.confirmed === true ? "confirmed" : "unconfirmed"})`);
    if (active.length > 3) summaries.push(`+${active.length - 3} additional alarms`);
    setText($("health-active-summary"), summaries.join(" · "));
    setText($("health-alarm-count"), latest?.health_monitor ? active.length : "—");
    $("health-alarm-count").dataset.status = active.some((alarm) => alarm.severity === "critical") ? "critical" : active.length ? "warning" : fresh ? "nominal" : "unknown";
    setText($("health-alarm-summary"), latest?.health_monitor ? `${active.length} ACTIVE · ${unacknowledged.length} UNACKNOWLEDGED${fresh ? "" : " · STATUS UNCONFIRMED"}` : "AWAITING DATA");
    const ordered = [...list].sort((a, b) => Number(b.active) - Number(a.active) || Number(a.acknowledged) - Number(b.acknowledged) || String(b.first_seen).localeCompare(String(a.first_seen))).slice(0, 20);
    // last_seen changes every telemetry frame. It is intentionally excluded:
    // rebuilding unchanged annunciators would discard operator keyboard focus.
    const displayed = ordered.map(({ id, component, code, severity, active, acknowledged, confirmed, first_seen, resolved_at }) => ({ id, component, code, severity, active, acknowledged, confirmed, first_seen, resolved_at }));
    const fingerprint = JSON.stringify([displayed, fresh, httpHealthy, [...pendingAcks]]);
    if (fingerprint === lastAlarmFingerprint) return;
    lastAlarmFingerprint = fingerprint;
    const focusedAlarm = $("health-alarm-list").contains(document.activeElement) ? document.activeElement.closest(".health-alarm-row")?.dataset.alarmId : null;
    $("health-alarm-list").replaceChildren();
    if (!ordered.length) {
      $("health-alarm-list").append(element("p", "health-empty", fresh ? "No reported subsystem alarms in this C2 session." : "Alarm status is unconfirmed while telemetry is unavailable."));
      return;
    }
    for (const alarm of ordered) {
      const row = element("div", "health-alarm-row");
      row.dataset.alarmId = alarm.id;
      row.dataset.component = alarm.component;
      row.dataset.code = alarm.code;
      row.dataset.active = String(alarm.active === true);
      row.dataset.acknowledged = String(alarm.acknowledged === true);
      row.dataset.confirmed = String(alarm.confirmed === true && fresh);
      row.dataset.status = alarm.active ? STATUS.has(alarm.severity) ? alarm.severity : "warning" : "unknown";
      const severity = element("span", "health-alarm-severity", alarm.active ? human(alarm.severity).toUpperCase() : "RECOVERED");
      const identity = element("div", "health-alarm-identity");
      identity.append(element("strong", "", catalog.find((component) => component.id === alarm.component)?.name || human(alarm.component)), element("span", "", human(alarm.code)));
      const time = element("div", "health-alarm-time");
      time.append(element("span", "", `First ${utc(alarm.first_seen)}`), element("span", "", alarm.active ? alarm.confirmed === true && fresh ? "Active · confirmed" : "Active · unconfirmed" : `Recovered ${utc(alarm.resolved_at)}`));
      const button = element("button", "health-ack", alarm.acknowledged ? "Acknowledged" : pendingAcks.has(alarm.id) ? "Sending…" : "Acknowledge");
      button.type = "button";
      button.disabled = alarm.acknowledged === true || !httpHealthy || pendingAcks.has(alarm.id);
      button.setAttribute("aria-label", `${alarm.acknowledged ? "Acknowledged" : "Acknowledge"} ${human(alarm.code)} for ${human(alarm.component)}`);
      button.addEventListener("click", () => acknowledge(alarm.id));
      row.append(severity, identity, time, button);
      $("health-alarm-list").append(row);
      if (focusedAlarm === String(alarm.id)) {
        if (!button.disabled) button.focus({ preventScroll: true });
        else { row.tabIndex = -1; row.focus({ preventScroll: true }); }
      }
    }
  }

  async function acknowledge(id) {
    if (pendingAcks.has(id)) return;
    pendingAcks.add(id);
    renderAlarms();
    try {
      await hooks.post("/api/health/ack", { alarm_id: id });
      report("Alarm acknowledgement recorded. Active faults remain displayed until recovery is reported.");
    } catch (error) { report(error.message || "Acknowledgement failed.", true); }
    finally { pendingAcks.delete(id); renderAlarms(); }
  }

  async function injectFault(fault) {
    if (busy || !fresh || !catalogReady) return;
    busy = true;
    refreshControls();
    const component = $("health-fault-component").value;
    try {
      const result = await hooks.command("rover", "SIM_HEALTH_FAULT", { component, fault });
      if (result?.status === "rejected") report(result.reason || "Simulator fault request rejected.", true);
      else report(`${fault === "clear" ? "Fault clear" : human(fault)} requested for ${catalog.find((item) => item.id === component)?.name || component}. Awaiting receiver confirmation.`);
    } catch (error) { report(error.message || "Fault command failed. Outcome is unconfirmed.", true); }
    finally { busy = false; refreshControls(); }
  }

  function refreshControls() {
    $("health-inject").disabled = busy || !fresh || !catalogReady;
    $("health-clear").disabled = busy || !fresh || !catalogReady;
    $("health-export").disabled = sampleCount === 0;
  }

  function exportCSV() {
    const rows = [["source", "model", "rover_boot_id", "observed_window_start_utc", "exported_at_utc", "component", "sensor", "unit", "current", "minimum", "maximum", "average", "valid_samples", "state", "model_limits"]];
    const now = new Date().toISOString();
    for (const component of catalog) {
      for (const channel of CHANNELS) {
        const stat = statistics.get(metricKey(component.id, channel.id));
        const reported = healthData()?.components?.[component.id];
        rows.push(["simulation", "ncc-six-wheel-v1 illustrative template", bootId || "", new Date(windowStart).toISOString(), now, component.id, channel.name, channel.unit, valueOf(reported, channel.id) ?? "", stat?.n ? stat.min : "", stat?.n ? stat.max : "", stat?.n ? stat.sum / stat.n : "", stat?.n || 0, measurementState(reported, channel.id), limitText(component, channel)]);
      }
    }
    const csv = rows.map((row) => row.map((value) => `"${String(value).replaceAll('"', '""')}"`).join(",")).join("\r\n") + "\r\n";
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const link = element("a");
    link.href = url;
    link.download = `rover-simulated-health-${now.replaceAll(":", "-")}.csv`;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    report("Exported simulated sensor readings and browser observation statistics.");
  }

  function render(data, successAt, healthy) {
    if (!root) return;
    latest = data;
    lastSuccess = finite(successAt) ? successAt : 0;
    httpHealthy = healthy === true;
    const now = Date.now();
    const elapsed = Math.max(0, now - lastSuccess);
    const rover = data?.vehicles?.rover;
    const health = healthData();
    const valid = health?.schema_version === 1 && health?.model_id === "ncc-six-wheel-v1" && health?.source === "simulation" && typeof health.components === "object" && health.components !== null;
    const roverAge = finite(rover?.age_s) ? rover.age_s * 1000 + elapsed : Infinity;
    const healthAge = finite(health?.age_s) ? health.age_s * 1000 + elapsed : Infinity;
    fresh = Boolean(httpHealthy && elapsed < STALE_MS && rover?.connected === true && rover?.synced === true && roverAge < STALE_MS && valid && health?.stale === false && healthAge < STALE_MS);
    observe(now);
    const linkStatus = fresh ? STATUS.has(health.overall) ? health.overall : "unknown" : health ? "stale" : "unknown";
    setText($("health-link"), fresh ? `LIVE · ${linkStatus.toUpperCase()}` : health ? "STALE / UNCONFIRMED" : "AWAITING DATA");
    $("health-link").dataset.status = linkStatus;
    setText($("health-bus"), `${number(valueOf(health?.components?.battery, "voltage_v"))} V`);
    const known = catalog.filter((component) => ["nominal", "warning", "critical"].includes(classification(health?.components?.[component.id]))).length;
    setText($("health-node-count"), `${known} / ${catalog.length}`);
    setText($("health-last-observed"), utc(lastSampleAt));
    setText($("health-data-notice"), fresh
      ? "Live telemetry from the rover simulator. Geometry, components and operating limits are illustrative; no physical hardware is connected."
      : "Current measurements are unavailable. Historical observations remain visible; subsystem power and health are unconfirmed. No physical hardware is connected.");
    $("health-data-notice").classList.toggle("is-stale", !fresh);
    statusById = {};
    for (const component of catalog) {
      const reported = health?.components?.[component.id];
      const status = classification(reported);
      statusById[component.id] = { ...reported, status, powered: fresh ? reported?.powered ?? null : null };
      const roster = rosterButtons.get(component.id);
      roster.button.dataset.status = status;
      setText(roster.status, human(status));
      roster.button.setAttribute("aria-label", `${component.name}: ${human(status)}`);
    }
    anatomy?.update(statusById);
    renderInspector();
    renderSensors();
    renderAlarms();
    const elapsedSeconds = Math.max(0, Math.floor((now - windowStart) / 1000));
    const duration = `${String(Math.floor(elapsedSeconds / 3600)).padStart(2, "0")}:${String(Math.floor(elapsedSeconds / 60) % 60).padStart(2, "0")}:${String(elapsedSeconds % 60).padStart(2, "0")}`;
    setText($("health-observation-window"), `Observation ${duration} · reset ${utc(windowStart)} · ${sampleCount} distinct health frames · ${fresh ? "collecting" : "historical"}${bootId ? ` · boot ${String(bootId).slice(0, 8)}` : ""}`);
    $("health-observation-window").dataset.samples = String(sampleCount);
    $("health-observation-window").dataset.windowStart = String(windowStart);
    refreshControls();
  }

  window.RoverHealth = {
    init(options = {}) {
      if (root) return;
      root = $("health-root");
      if (!root) return;
      hooks = options;
      build();
      render(null, 0, false);
      loadCatalog();
    },
    render,
    onViewChange() { if (root) render(latest, lastSuccess, httpHealthy); },
  };
})();
