/* Local historical imagery only. Coordinates are WGS84; tiles use Web Mercator XYZ. */
(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.GeoView = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";
  const MAX_LATITUDE = 85.0511287798066;
  const EARTH_RADIUS = 6378137;
  const SVG_NS = "http://www.w3.org/2000/svg";

  function validPosition(position) {
    return Boolean(position && Number.isFinite(position.lat) && Number.isFinite(position.lon)
      && Math.abs(position.lat) <= 90 && Math.abs(position.lon) <= 180);
  }

  function project(position, zoom, tileSize = 256) {
    if (!validPosition(position) || Math.abs(position.lat) > MAX_LATITUDE
      || !Number.isInteger(zoom) || zoom < 0 || zoom > 22 || !Number.isFinite(tileSize) || tileSize <= 0) return null;
    const size = tileSize * 2 ** zoom;
    const latitude = position.lat * Math.PI / 180;
    return { x: (position.lon + 180) / 360 * size,
      y: (1 - Math.asinh(Math.tan(latitude)) / Math.PI) / 2 * size };
  }

  function unproject(point, zoom, tileSize = 256) {
    if (!point || !Number.isFinite(point.x) || !Number.isFinite(point.y)
      || !Number.isInteger(zoom) || zoom < 0 || zoom > 22 || !Number.isFinite(tileSize) || tileSize <= 0) return null;
    const size = tileSize * 2 ** zoom;
    return { lat: Math.atan(Math.sinh(Math.PI * (1 - 2 * point.y / size))) * 180 / Math.PI,
      lon: point.x / size * 360 - 180 };
  }

  function pointInCoverage(manifest, position) {
    const point = project(position, manifest.zoom, manifest.tile_size);
    if (!point) return false;
    const x = Math.floor(point.x / manifest.tile_size);
    const y = Math.floor(point.y / manifest.tile_size);
    return manifest.tiles.some((tile) => tile.x === x && tile.y === y);
  }

  function validateManifest(manifest) {
    if (!manifest || manifest.schema_version !== 1 || manifest.crs !== "EPSG:3857"
      || manifest.imagery_kind !== "historical-satellite-mosaic" || manifest.tile_size !== 256
      || !Number.isInteger(manifest.zoom) || manifest.zoom < 0 || manifest.zoom > 22
      || !Array.isArray(manifest.tiles) || !manifest.tiles.length || manifest.tiles.length > 64
      || !validPosition(manifest.center) || !project(manifest.center, manifest.zoom)
      || typeof manifest.source !== "string" || !manifest.source || !manifest.year
      || typeof manifest.attribution !== "string" || !manifest.attribution
      || !Number.isFinite(manifest.resolution_m) || manifest.resolution_m <= 0) {
      throw new Error("Historical imagery metadata is invalid.");
    }
    const keys = new Set();
    for (const tile of manifest.tiles) {
      const key = `${tile.x}/${tile.y}`;
      if (!Number.isInteger(tile.x) || !Number.isInteger(tile.y)
        || tile.x < 0 || tile.y < 0 || tile.x >= 2 ** manifest.zoom || tile.y >= 2 ** manifest.zoom
        || !/^\/imagery\/[a-zA-Z0-9_\/-]+\.jpg$/.test(tile.path || "") || keys.has(key)
        || !/^[a-f0-9]{64}$/.test(tile.sha256 || "")) throw new Error("Historical imagery tile metadata is invalid.");
      keys.add(key);
    }
    if (!pointInCoverage(manifest, manifest.center)) throw new Error("Imagery center is outside the stored coverage.");
    return manifest;
  }

  function node(tag, attrs = {}, content) {
    const result = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs).forEach(([key, value]) => result.setAttribute(key, String(value)));
    if (content !== undefined) result.textContent = content;
    return result;
  }

  class OfflineMap {
    constructor(svg, options = {}) {
      this.svg = svg;
      this.follow = options.follow || null;
      this.status = options.status || (() => {});
      this.scaleLabel = options.scaleLabel || (() => {});
      this.scene = {};
      this.scale = 1;
      this.userMoved = false;
      this.tiles = node("g", { class: "satellite-tiles" });
      this.clip = node("clipPath", { id: `${svg.id}-coverage` });
      const definitions = node("defs");
      definitions.append(this.clip);
      this.overlays = node("g", { class: "map-overlays", "clip-path": `url(#${svg.id}-coverage)` });
      svg.append(definitions, this.tiles, this.overlays);
      this.resizeObserver = new ResizeObserver(() => this.render());
      this.resizeObserver.observe(svg);
      if (!this.follow) this.bindPan();
    }

    setManifest(manifest) {
      this.manifest = manifest;
      this.tiles.replaceChildren(...manifest.tiles.map((tile) => {
        const image = node("image", { href: tile.path, width: manifest.tile_size, height: manifest.tile_size });
        image.addEventListener("error", () => {
          this.failed = true;
          this.overlays.replaceChildren();
          this.status("Stored imagery could not be loaded. Position overlays are unavailable.");
        });
        return image;
      }));
      this.reset();
    }

    reset() {
      if (!this.manifest) return;
      this.center = project(this.manifest.center, this.manifest.zoom, this.manifest.tile_size);
      this.scale = this.follow ? 1.6 : 1.5;
      this.userMoved = false;
      this.render();
    }

    zoom(factor) {
      if (!this.manifest) return;
      this.scale = Math.max(0.4, Math.min(4, this.scale * factor));
      this.render();
    }

    update(scene) {
      this.scene = scene;
      this.render();
    }

    bindPan() {
      let drag = null;
      this.svg.addEventListener("pointerdown", (event) => {
        if (!this.manifest || !this.center || (event.pointerType === "mouse" && event.button !== 0)) return;
        drag = { x: event.clientX, y: event.clientY, center: { ...this.center }, id: event.pointerId };
        this.svg.setPointerCapture(event.pointerId);
        this.svg.classList.add("dragging");
      });
      this.svg.addEventListener("pointermove", (event) => {
        if (!drag || drag.id !== event.pointerId) return;
        this.center = { x: drag.center.x - (event.clientX - drag.x) / this.scale,
          y: drag.center.y - (event.clientY - drag.y) / this.scale };
        this.userMoved = true;
        this.render();
      });
      const end = () => { drag = null; this.svg.classList.remove("dragging"); };
      this.svg.addEventListener("pointerup", end);
      this.svg.addEventListener("pointercancel", end);
      this.svg.addEventListener("lostpointercapture", end);
      this.svg.addEventListener("keydown", (event) => {
        if (!this.manifest) return;
        const directions = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
        const direction = directions[event.key];
        if (direction) {
          event.preventDefault();
          this.center.x += direction[0] * 65 / this.scale;
          this.center.y += direction[1] * 65 / this.scale;
          this.userMoved = true;
          this.render();
        }
      });
    }

    render() {
      if (!this.manifest || !this.center || this.failed) return;
      const manifest = this.manifest;
      const bounds = this.svg.getBoundingClientRect();
      if (!bounds.width || !bounds.height) return;
      const width = bounds.width;
      const height = bounds.height;
      this.svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
      const vehicle = this.follow ? this.scene[this.follow] : null;
      if (vehicle && pointInCoverage(manifest, vehicle.position)) {
        this.center = project(vehicle.position, manifest.zoom, manifest.tile_size);
      }
      const toScreen = (position) => {
        const point = project(position, manifest.zoom, manifest.tile_size);
        return point && { x: width / 2 + (point.x - this.center.x) * this.scale,
          y: height / 2 + (point.y - this.center.y) * this.scale };
      };
      const visible = (point) => point && point.x >= 0 && point.x <= width && point.y >= 0 && point.y <= height;
      this.clip.replaceChildren();
      manifest.tiles.forEach((tile, index) => {
        const image = this.tiles.children[index];
        image.setAttribute("x", width / 2 + (tile.x * manifest.tile_size - this.center.x) * this.scale);
        image.setAttribute("y", height / 2 + (tile.y * manifest.tile_size - this.center.y) * this.scale);
        image.setAttribute("width", manifest.tile_size * this.scale + 0.1);
        image.setAttribute("height", manifest.tile_size * this.scale + 0.1);
        this.clip.append(node("rect", { x: image.getAttribute("x"), y: image.getAttribute("y"),
          width: manifest.tile_size * this.scale, height: manifest.tile_size * this.scale }));
      });
      this.overlays.replaceChildren();
      const messages = [];
      const route = this.scene.waypoints || [];
      const drawPath = (points, className) => {
        let segment = [];
        const flush = () => {
          if (segment.length > 1) this.overlays.append(node("polyline", { class: className,
            points: segment.map((point) => `${point.x},${point.y}`).join(" ") }));
          segment = [];
        };
        points.forEach((position) => {
          if (!pointInCoverage(manifest, position)) { flush(); return; }
          segment.push(toScreen(position));
        });
        flush();
      };
      drawPath(this.scene.trail || [], "rover-trail");
      drawPath(route, "review-route-line");
      route.forEach((waypoint, index) => {
        if (!pointInCoverage(manifest, waypoint)) return;
        const point = toScreen(waypoint);
        if (!visible(point)) return;
        this.overlays.append(node("circle", { class: "review-waypoint", cx: point.x, cy: point.y, r: 4 }));
        if (route.length <= 20) this.overlays.append(node("text", { class: "review-waypoint-label",
          x: point.x + 8, y: point.y - 8 }, String(index + 1).padStart(2, "0")));
      });
      if (route.some((point) => !pointInCoverage(manifest, point))) messages.push("Some reviewed waypoints are outside stored imagery.");
      if (this.scene.routeWarning) messages.push(this.scene.routeWarning);
      for (const name of ["rover", "drone"]) {
        if (this.follow && name !== this.follow) continue;
        const item = this.scene[name];
        const label = name === "rover" ? "Rover" : "Drone";
        if (!validPosition(item?.position)) { messages.push(`${label}: waiting for position.`); continue; }
        if (!pointInCoverage(manifest, item.position)) { messages.push(`${label}: outside stored imagery.`); continue; }
        const point = toScreen(item.position);
        if (!visible(point)) { messages.push(`${label}: outside this view; reset to return.`); continue; }
        const marker = node("g", { class: `vehicle-marker ${name}-map-marker${item.fresh ? "" : " marker-stale"}`,
          transform: `translate(${point.x} ${point.y})`, "data-vehicle": name,
          "aria-label": `${label} simulated position${item.fresh ? "" : ", stale"}` });
        if (name === "rover") {
          marker.append(node("circle", { r: 17, class: "marker-halo" }), node("circle", { r: 7, class: "marker-core" }));
        } else {
          marker.append(node("circle", { r: 22, class: "drone-halo" }),
            node("path", { d: "M-12-12L12 12M12-12L-12 12", class: "drone-cross" }));
          for (const [x, y] of [[-12,-12], [12,-12], [-12,12], [12,12]]) {
            marker.append(node("circle", { cx: x, cy: y, r: 4, class: "drone-rotor" }));
          }
        }
        marker.append(node("text", { x: 27, y: name === "drone" ? -11 : 18, class: "map-label" },
          `${label.toUpperCase()} · SIM${item.fresh ? "" : " · STALE"}`));
        this.overlays.append(marker);
        if (!item.fresh) messages.push(`${label}: stale position; last report shown.`);
      }
      const centerCovered = pointInCoverage(manifest, unproject(this.center, manifest.zoom, manifest.tile_size));
      if (!centerCovered) messages.unshift("Outside stored imagery coverage. Reset to return.");
      this.status(messages.join(" "));
      const latitude = unproject(this.center, manifest.zoom, manifest.tile_size).lat;
      const metersPerPixel = Math.cos(latitude * Math.PI / 180) * 2 * Math.PI * EARTH_RADIUS
        / (manifest.tile_size * 2 ** manifest.zoom) / this.scale;
      this.scaleLabel(`100 px ≈ ${Math.round(metersPerPixel * 100)} m · north ↑`);
    }
  }

  return { MAX_LATITUDE, validPosition, project, unproject, pointInCoverage, validateManifest, OfflineMap };
});
