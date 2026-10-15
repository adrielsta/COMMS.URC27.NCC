#!/usr/bin/env python3
"""Optional browser check using installed Playwright and Chromium.

Starts its own simulated vehicles on free ports. No physical adapters or remote
requests are used. Run from the repository root after building the native codec:
    python3 scripts/check_ui.py --screenshots /tmp/ncc-ui
Playwright is a development-only dependency; the dashboard does not require it.
"""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_end_to_end import reserve_ports


class Simulation:
    def __enter__(self):
        self.runtime = tempfile.TemporaryDirectory(prefix="ncc-browser-")
        self.log = tempfile.TemporaryFile()
        http, udp = reserve_ports()
        self.url = f"http://127.0.0.1:{http}"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "comms.supervisor"], cwd=ROOT,
            env=os.environ | {"COMMS_RUNTIME_DIR": self.runtime.name,
                              "COMMS_HTTP_HOST": "127.0.0.1",
                              "COMMS_HTTP_PORT": str(http), "COMMS_UDP_PORT": str(udp)},
            stdout=self.log, stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            self.wait(lambda s: all(v["connected"] and v["synced"]
                                   for v in s["vehicles"].values()), timeout=12)
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, *_):
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(self.process.pid, signal.SIGKILL)
            self.process.wait(timeout=3)
        self.log.close()
        self.runtime.cleanup()

    def state(self):
        with urllib.request.urlopen(self.url + "/api/state", timeout=2) as response:
            return json.load(response)

    def wait(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AssertionError("Isolated simulation exited unexpectedly")
            try:
                state = self.state()
                if predicate(state):
                    return state
            except OSError:
                pass
            time.sleep(.04)
        # Never emit state snapshots: they contain an HTTP session token.
        raise AssertionError("Expected simulation state was not observed")


def check_ui(browser, simulation, screenshot_dir):
    context = browser.new_context(viewport={"width": 1440, "height": 1050})
    page = context.new_page()
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: external.append(request.url)
            if not request.url.startswith(simulation.url + "/") else None)
    page.goto(simulation.url, wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelector('#map-empty').hidden")
    page.wait_for_function("() => document.querySelector('#fleet-online').textContent.includes('2 / 2')")

    def selected(view):
        assert page.locator(f"#view-{view}").is_visible(), view
        assert page.locator("[data-workspace-view]:visible").count() == 1
        assert page.locator(f"#nav-{view}").get_attribute("aria-selected") == "true"
        assert page.locator("[data-nav-view][tabindex='0']").count() == 1
        assert page.locator("#stop-rover").is_visible()
        assert page.locator("#activity-title").is_visible()
        assert page.evaluate("""() => [...document.querySelectorAll('[data-workspace-view][hidden]')]
            .every(panel => [...panel.querySelectorAll('button, input, select, a, [tabindex]')]
            .every(node => node.getClientRects().length === 0))""")

    def nav(view):
        page.locator(f"#nav-{view}").click()
        selected(view)

    def command(button, action, vehicle="rover", status="completed"):
        before = {item["id"] for item in simulation.state()["commands"]}
        page.locator(button).click()
        state = simulation.wait(lambda s: any(
            item["id"] not in before and item["vehicle"] == vehicle
            and item["action"] == action and item["status"] == status
            for item in s["commands"]))
        return next(item for item in state["commands"] if item["id"] not in before
                    and item["vehicle"] == vehicle and item["action"] == action
                    and item["status"] == status)

    selected("overview")
    for view in ("drone", "routes", "network", "overview"):
        nav(view)
    page.locator("#nav-overview").focus()
    for key, view in (("ArrowRight", "drone"), ("End", "network"),
                      ("ArrowLeft", "routes"), ("Home", "overview")):
        page.keyboard.press(key)
        selected(view)
        assert page.locator(f"#nav-{view}").evaluate("node => node === document.activeElement")
    nav("drone")
    nav("routes")
    page.go_back()
    selected("drone")
    page.go_forward()
    selected("routes")
    page.reload(wait_until="domcontentloaded")
    selected("routes")
    assert page.url.endswith("#routes")
    page.locator(".skip-link").focus()
    page.keyboard.press("Enter")
    selected("routes")
    assert page.locator("#main").evaluate("node => node === document.activeElement")
    assert page.url.endswith("#routes")
    print("PASS: workspace navigation, keyboard, hidden controls, history and reload", flush=True)

    for width, height in ((1440, 1050), (1024, 900), (768, 1024), (390, 844), (320, 720)):
        page.set_viewport_size({"width": width, "height": height})
        for view in ("overview", "drone", "routes", "network"):
            nav(view)
            page.wait_for_timeout(120)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), (width, view)
            if width == 1440 or (width == 390 and view == "overview"):
                page.screenshot(path=str(screenshot_dir / f"{view}-{width}.png"), full_page=True)
    print("PASS: all four views fit 1440, 1024, 768, 390 and 320 px widths", flush=True)

    page.set_viewport_size({"width": 1440, "height": 1050})
    nav("overview")
    page.wait_for_function("() => document.querySelector('#map-empty').hidden")
    assert page.locator("#field-map .satellite-tiles image").count() == 9
    assert page.locator("#drone-map .satellite-tiles image").count() == 9
    assert "2016" in page.locator("#imagery-source").inner_text()
    tile = page.locator("#field-map .satellite-tiles image").first
    initial = float(tile.get_attribute("width"))
    page.locator("#map-zoom-in").click()
    assert float(tile.get_attribute("width")) > initial
    page.locator("#map-reset").click()
    assert abs(float(tile.get_attribute("width")) - initial) < .01
    start = float(tile.get_attribute("x"))
    page.locator("#field-map").focus()
    page.keyboard.press("ArrowRight")
    assert float(tile.get_attribute("x")) < start
    page.locator("#map-reset").click()
    nav("drone")
    page.locator("#drone-camera-tab").click()
    assert "No camera connected" in page.locator("#drone-camera-panel").inner_text()
    page.locator("#drone-camera-tab").focus()
    page.keyboard.press("Home")
    assert page.locator("#drone-map-panel").is_visible()
    page.keyboard.press("ArrowRight")
    assert page.locator("#drone-camera-panel").is_visible()
    page.locator("#drone-map-tab").click()
    print("PASS: nine local tiles per map, attribution, pan/zoom/reset and truthful camera tabs", flush=True)

    nav("overview")
    command("#claim-control", "CLAIM_CONTROL")
    previous_position = simulation.state()["vehicles"]["rover"]["state"]["position"]
    command("#manual-pulse", "MANUAL")
    simulation.wait(lambda s: s["vehicles"]["rover"]["state"]["position"] != previous_position)
    simulation.wait(lambda s: not s["vehicles"]["rover"]["state"]["moving"])
    command("#stop-rover", "STOP")
    simulation.wait(lambda s: not s["vehicles"]["rover"]["state"]["moving"])
    nav("drone")
    command("#drone-takeoff", "DRONE_TAKEOFF", "drone")
    command("#drone-survey", "DRONE_SURVEY", "drone")
    command("#drone-land", "DRONE_LAND", "drone")
    nav("routes")
    page.locator("#review-survey").click()
    assert page.locator("#package-review").is_visible()
    package_id = page.locator("#review-package-id").inner_text()
    page.locator("#transfer-package").click()
    simulation.wait(lambda s: any(t["package_id"] == package_id and t["status"] == "accepted"
                                 for t in s["transfers"]))
    assert simulation.state()["vehicles"]["rover"]["state"]["active_package"] is None
    command("#activate-package", "ACTIVATE_PACKAGE")
    simulation.wait(lambda s: s["vehicles"]["rover"]["state"]["active_package"] == package_id)
    print("PASS: real simulated manual pulse/STOP, drone survey and separate transfer/activation", flush=True)

    # A longer uploaded synthetic route makes hands-off/stale checks observable.
    package = {"schema_version": 1, "package_id": "browser-long-route", "version": 1,
               "crs": "EPSG:4326", "units": "degrees", "synthetic": True,
               "source": "simulated-drone", "waypoints": [
                   {"lat": 38.418 + i * .00001, "lon": -110.777} for i in range(40)]}
    page.locator("#package-file").set_input_files({"name": "synthetic-route.json",
        "mimeType": "application/json", "buffer": json.dumps(package).encode()})
    page.wait_for_function("() => document.querySelector('#review-package-id').textContent === 'browser-long-route'")
    page.locator("#transfer-package").click()
    simulation.wait(lambda s: any(t["package_id"] == package["package_id"] and t["status"] == "accepted"
                                 for t in s["transfers"]))
    command("#activate-package", "ACTIVATE_PACKAGE")
    nav("overview")
    page.locator("#mission-select").select_option("route_finding")
    page.locator("#set-mission").click()
    simulation.wait(lambda s: all(v["state"]["mission"] == "route_finding"
                                 for v in s["vehicles"].values()))
    simulation.wait(lambda s: s["vehicles"]["rover"]["state"]["drone_state_fresh"]
                    and s["vehicles"]["drone"]["state"]["flight_locked"])
    page.wait_for_timeout(650)
    nav("routes")
    route = command("#start-route", "START_ROUTE", status="accepted")
    page.wait_for_function("() => document.querySelector('#package-edit-status').textContent.includes('Hands off')")
    assert page.locator("#package-file").is_disabled()
    assert page.locator("#review-survey").is_disabled()
    assert page.locator("#transfer-package").is_disabled()
    nav("network")
    page.locator("#fault-disconnect").check()
    page.locator("#fault-form button[type=submit]").click()
    page.wait_for_function("() => !document.querySelector('#stale-warning').hidden", timeout=7000)
    nav("routes")
    assert page.locator("#package-file").is_disabled()
    assert page.locator("#transfer-package").is_disabled()
    nav("overview")
    assert page.locator("#manual-pulse").is_disabled()
    assert page.locator("#stop-rover").is_enabled()
    nav("network")
    page.locator("#reset-faults").click()
    simulation.wait(lambda s: all(v["connected"] for v in s["vehicles"].values()))
    simulation.wait(lambda s: any(c["id"] == route["id"] and c["status"] == "completed"
                                 for c in s["commands"]), timeout=15)
    nav("routes")
    page.wait_for_function("() => !document.querySelector('#package-file').disabled")
    assert simulation.state()["vehicles"]["rover"]["state"]["position"] == package["waypoints"][-1]
    print("PASS: route completion, Q21 package locks, disconnected stale guards and recovery", flush=True)

    # Network interception changes only read-only responses in fresh contexts.
    missing = browser.new_context(viewport={"width": 390, "height": 844})
    missing.route("**/imagery/*.jpg", lambda route: route.fulfill(status=404, body="missing"))
    fallback = missing.new_page()
    fallback.on("pageerror", lambda error: errors.append(str(error)))
    fallback.goto(simulation.url)
    fallback.wait_for_function("() => document.querySelector('#map-load-status').textContent.includes('unavailable')")
    assert fallback.locator("#map-empty").is_visible()
    assert fallback.locator("#field-map .satellite-tiles image").count() == 0
    missing.close()

    page.route("**/api/state", lambda route: route.fulfill(status=503, body="unavailable"))
    page.wait_for_function("() => document.querySelector('#connection-label').textContent === 'C2 unavailable'")
    assert page.locator("#package-file").is_disabled()
    assert page.locator("#transfer-package").is_disabled()
    nav("overview")
    assert page.locator("#manual-pulse").is_disabled()
    assert page.locator("#stop-rover").is_enabled()
    page.unroute("**/api/state")
    page.wait_for_function("() => document.querySelector('#connection-label').textContent === 'C2 connected'")
    assert not errors, errors
    assert not external, "Unexpected external browser requests"
    print("PASS: missing imagery and HTTP failure states; no JavaScript errors or external requests", flush=True)
    context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--screenshots", type=Path, default=Path("/tmp/ncc-ui"))
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with Simulation() as simulation, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True,
                                             args=["--no-sandbox"])
        try:
            check_ui(browser, simulation, args.screenshots)
        except BaseException:
            for index, context in enumerate(browser.contexts):
                if context.pages:
                    context.pages[-1].screenshot(
                        path=str(args.screenshots / f"failure-{index}.png"), full_page=True)
            raise
        finally:
            browser.close()
    print(f"Browser checks passed. Screenshots: {args.screenshots}")


if __name__ == "__main__":
    main()
