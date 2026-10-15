#!/usr/bin/env python3
"""Exercise the engineering console against isolated simulated vehicle processes.

Optional development check: installed Playwright and Chromium are required.
No physical hardware or external service is used.
"""
import argparse
import copy
import csv
import io
from pathlib import Path

from check_ui import Simulation


def check_health(browser, simulation, screenshots):
    context = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
    page = context.new_page()
    errors, external = [], []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("request", lambda request: external.append(request.url)
            if not request.url.startswith(simulation.url + "/") and not request.url.startswith("blob:") else None)
    page.goto(simulation.url, wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelector('#health-node-count')?.textContent === '14 / 14'")
    page.wait_for_function("() => document.querySelector('#health-catalog-notice').hidden")
    assert page.locator("#view-health").is_visible()
    assert "0.2.0" in page.locator("#console-build").inner_text()
    assert page.locator("#health-component-list button[data-component]").count() == 14

    def select(component):
        page.locator(f"#health-component-list button[data-component='{component}']").click()
        assert page.locator("#health-anatomy").get_attribute("data-selected-component") == component

    def inject(component, fault):
        details = page.locator(".health-engineering")
        if details.get_attribute("open") is None:
            details.locator("summary").click()
        page.locator("#health-fault-component").select_option(component)
        before = {item["id"] for item in simulation.state()["commands"]}
        if fault == "clear":
            page.locator("#health-clear").click()
        else:
            page.locator("#health-fault-type").select_option(fault)
            page.locator("#health-inject").click()
        simulation.wait(lambda state: any(item["id"] not in before and
                        item["action"] == "SIM_HEALTH_FAULT" and item["status"] == "completed"
                        for item in state["commands"]))

    def alarm(component, code):
        return page.locator(f".health-alarm-row[data-component='{component}'][data-code='{code}']")

    select("drive_fr")
    inject("drive_fr", "overtemp")
    page.wait_for_function("() => document.querySelector('#health-selected-status').textContent === 'CRITICAL'")
    row = alarm("drive_fr", "overtemp")
    row.wait_for()
    page.wait_for_function("() => !!document.querySelector('.health-alarm-row[data-component=drive_fr][data-code=overtemp][data-active=true][data-confirmed=true]')")
    ack = row.locator(".health-ack")
    ack.focus()
    page.wait_for_timeout(1200)
    assert ack.evaluate("node => node === document.activeElement"), "Polling displaced the focused acknowledgment"
    ack.click()
    simulation.wait(lambda state: any(item["component"] == "drive_fr" and item["code"] == "overtemp"
                                     and item["active"] and item["acknowledged"]
                                     for item in state["health_monitor"]["alarms"]))
    assert simulation.state()["vehicles"]["rover"]["state"]["health"]["components"]["drive_fr"]["temperature_c"] == 86
    page.screenshot(path=str(screenshots / "drive-fault-1440.png"), full_page=True)
    inject("drive_fr", "sensor_loss")
    page.wait_for_function("() => document.querySelector('#health-selected-status').textContent === 'UNKNOWN'")
    page.wait_for_function("() => !!document.querySelector('.health-alarm-row[data-component=drive_fr][data-code=overtemp][data-active=true][data-confirmed=false]')")
    assert "—" in page.locator("#health-trend-value-temperature_c").inner_text()
    inject("drive_fr", "clear")
    simulation.wait(lambda state: not any(item["component"] == "drive_fr" and item["active"]
                                          for item in state["health_monitor"]["alarms"]))
    print("PASS: component selection, acknowledged fault remains active, sensor loss does not claim recovery", flush=True)

    select("pdu")
    inject("pdu", "power_loss")
    simulation.wait(lambda state: all(not value["powered"] for ident, value in
                    state["vehicles"]["rover"]["state"]["health"]["components"].items() if ident != "battery"))
    page.wait_for_function("() => document.querySelector('#health-selected-power').textContent === 'Unpowered'")
    assert simulation.state()["vehicles"]["rover"]["state"]["health"]["components"]["battery"]["powered"]
    page.screenshot(path=str(screenshots / "power-loss-1440.png"), full_page=True)
    inject("pdu", "clear")
    simulation.wait(lambda state: state["vehicles"]["rover"]["state"]["health"]["overall"] == "nominal")

    page.locator("#nav-network").click()
    page.locator("#fault-disconnect").check()
    page.locator("#fault-form button[type=submit]").click()
    simulation.wait(lambda state: state["faults"]["disconnect"])
    page.locator("#nav-health").click()
    page.wait_for_function("() => document.querySelector('#health-link').dataset.status === 'stale'")
    assert page.locator("#health-inject").is_disabled()
    assert "—" in page.locator("#health-bus").inner_text()
    page.locator("#health-tab-sensors").click()
    cell = page.locator("tr[data-component='battery'][data-channel='voltage_v']")
    assert cell.locator(".health-cell-current").inner_text() == "—"
    count = cell.locator(".health-cell-samples").inner_text()
    page.wait_for_timeout(1200)
    assert cell.locator(".health-cell-samples").inner_text() == count
    page.screenshot(path=str(screenshots / "stale-sensors-1440.png"), full_page=True)
    page.locator("#nav-network").click()
    page.locator("#reset-faults").click()
    simulation.wait(lambda state: state["vehicles"]["rover"]["connected"] and not state["faults"]["disconnect"])
    page.locator("#nav-health").click()
    page.wait_for_function("() => document.querySelector('#health-link').dataset.status === 'nominal'")
    print("PASS: electrical supply cascade, stale currents hidden, statistics pause, and telemetry recovery", flush=True)
    assert not errors, errors
    assert not external, "Unexpected external browser requests"
    context.close()

    # Replay identified valid observations to verify statistics, not browser ticks.
    fixture = copy.deepcopy(simulation.state())
    fixture["vehicles"]["rover"]["age_s"] = 0
    health = fixture["vehicles"]["rover"]["state"]["health"]
    health.update(seq=100, age_s=0, stale=False)
    health["components"]["battery"]["voltage_v"] = 24.0
    context = browser.new_context(viewport={"width": 1440, "height": 950}, accept_downloads=True)
    page = context.new_page()
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.route("**/api/state", lambda route: route.fulfill(json=fixture))
    page.goto(simulation.url, wait_until="domcontentloaded")
    page.wait_for_function("() => document.querySelector('#health-node-count')?.textContent === '14 / 14'")
    page.locator("#health-tab-sensors").click()
    row = page.locator("tr[data-component='battery'][data-channel='voltage_v']")
    page.wait_for_timeout(1200)
    assert row.locator(".health-cell-samples").inner_text() == "1"
    health["seq"] = 101
    health["components"]["battery"]["voltage_v"] = 26.0
    page.wait_for_function("() => document.querySelector('tr[data-component=battery][data-channel=voltage_v] .health-cell-samples').textContent === '2'")
    assert row.locator(".health-cell-min").inner_text() == "24.00"
    assert row.locator(".health-cell-max").inner_text() == "26.00"
    assert row.locator(".health-cell-average").inner_text() == "25.00"
    with page.expect_download() as download_info:
        page.locator("#health-export").click()
    download = download_info.value
    data = Path(download.path()).read_text()
    readings = list(csv.DictReader(io.StringIO(data)))
    assert len(readings) == 42
    battery = next(item for item in readings if item["component"] == "battery" and item["sensor"] == "Voltage")
    assert float(battery["average"]) == 25 and int(battery["valid_samples"]) == 2
    assert battery["source"] == "simulation"
    page.locator("#health-reset-stats").click()
    assert row.locator(".health-cell-samples").inner_text() == "1"
    assert row.locator(".health-cell-average").inner_text() == "26.00"
    fixture["vehicles"]["rover"]["boot_id"] = "browser-test-restarted-rover"
    health["seq"] = 1
    health["components"]["battery"]["voltage_v"] = 24.5
    page.wait_for_function("() => document.querySelector('tr[data-component=battery][data-channel=voltage_v] .health-cell-current').textContent === '24.50'")
    assert row.locator(".health-cell-samples").inner_text() == "1"
    assert row.locator(".health-cell-average").inner_text() == "24.50"
    print("PASS: duplicate sample suppression, exact min/max/mean, CSV, reset and vehicle reboot", flush=True)
    assert not errors, errors
    context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chromium", default="/usr/bin/chromium")
    parser.add_argument("--screenshots", type=Path, default=Path("/tmp/ncc-health-ui"))
    args = parser.parse_args()
    args.screenshots.mkdir(parents=True, exist_ok=True)
    from playwright.sync_api import sync_playwright
    with Simulation() as simulation, sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.chromium, headless=True,
                                             args=["--no-sandbox"])
        try:
            check_health(browser, simulation, args.screenshots)
        except BaseException:
            for index, context in enumerate(browser.contexts):
                if context.pages:
                    context.pages[-1].screenshot(path=str(args.screenshots / f"failure-{index}.png"), full_page=True)
            raise
        finally:
            browser.close()
    print(f"Engineering browser checks passed. Screenshots: {args.screenshots}")


if __name__ == "__main__":
    main()
