'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const geo = require('../web/geoview.js');
const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, '../web/imagery/metadata.json'), 'utf8'));

test('WGS84 origin and known XYZ tile corners align exactly', () => {
  assert.deepEqual(geo.project({lat: 0, lon: 0}, 0), {x: 128, y: 128});
  assert.deepEqual(geo.unproject({x: 128, y: 128}, 0), {lat: 0, lon: 0});
  const corner = geo.project({lat: manifest.bounds.north, lon: manifest.bounds.west}, manifest.zoom);
  assert.ok(Math.abs(corner.x - Math.min(...manifest.tiles.map(t => t.x)) * 256) < 1e-7);
  assert.ok(Math.abs(corner.y - Math.min(...manifest.tiles.map(t => t.y)) * 256) < 1e-7);
});

test('competition coordinates project into the actual downloaded tile', () => {
  const projected = geo.project({lat: 38.418, lon: -110.777}, 15);
  assert.equal(Math.floor(projected.x / 256), 6300);
  assert.equal(Math.floor(projected.y / 256), 12591);
  assert.equal(geo.pointInCoverage(manifest, {lat: 38.418, lon: -110.777}), true);
  for (const lat of [38.411, 38.425]) for (const lon of [-110.786, -110.768]) {
    assert.equal(geo.pointInCoverage(manifest, {lat, lon}), true);
  }
});

test('latitude longitude roundtrip preserves position without autoscale distortion', () => {
  for (const p of [{lat: 38.418, lon: -110.777}, {lat: -33.8, lon: 151.2}, {lat: 80, lon: -179}]) {
    const result = geo.unproject(geo.project(p, 15), 15);
    assert.ok(Math.abs(result.lat - p.lat) < 1e-9);
    assert.ok(Math.abs(result.lon - p.lon) < 1e-9);
  }
  const here = geo.project(manifest.center, manifest.zoom);
  const north = geo.project({lat: manifest.center.lat + .001, lon: manifest.center.lon}, manifest.zoom);
  const east = geo.project({lat: manifest.center.lat, lon: manifest.center.lon + .001}, manifest.zoom);
  assert.ok(north.y < here.y);
  assert.ok(east.x > here.x);
});

test('invalid and polar positions cannot be clamped onto believable terrain', () => {
  for (const p of [null, {}, {lat: NaN, lon: 0}, {lat: 0, lon: Infinity}, {lat: 90, lon: 0}, {lat: 0, lon: 181}]) {
    assert.equal(geo.project(p, 15), null);
  }
  assert.equal(geo.project(manifest.center, 30), null);
  assert.equal(geo.pointInCoverage(manifest, {lat: 0, lon: 0}), false);
  assert.equal(geo.pointInCoverage(manifest, {lat: 38.418, lon: -110.75}), false);
});

test('manifest rejects remote tile dependencies, duplicates and unsupported projection', () => {
  assert.equal(geo.validateManifest(manifest), manifest);
  const changed = () => JSON.parse(JSON.stringify(manifest));
  const remote = changed(); remote.tiles[0].path = 'https://example.com/live.jpg';
  const duplicate = changed(); duplicate.tiles.push(duplicate.tiles[0]);
  const projection = changed(); projection.crs = 'EPSG:4326';
  const hash = changed(); hash.tiles[0].sha256 = 'unverified';
  const center = changed(); center.center = {lat: 0, lon: 0};
  for (const bad of [remote, duplicate, projection, hash, center]) assert.throws(() => geo.validateManifest(bad));
});
