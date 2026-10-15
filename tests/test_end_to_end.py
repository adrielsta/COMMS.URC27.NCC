"""Exercise the real HTTP service and two simulated vehicles over localhost UDP."""

import json
import os
from pathlib import Path
import random
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid


def reserve_ports():
    """Find an HTTP port and a consecutive trio for C2, rover, and drone UDP."""
    with socket.socket() as http_socket:
        http_socket.bind(("127.0.0.1", 0))
        http_port = http_socket.getsockname()[1]
    for _ in range(100):
        udp_port = random.SystemRandom().randrange(20000, 55000)
        probes = []
        try:
            for port in range(udp_port, udp_port + 3):
                probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                probes.append(probe)
                probe.bind(("127.0.0.1", port))
            return http_port, udp_port
        except OSError:
            continue
        finally:
            for probe in probes:
                probe.close()
    raise RuntimeError("No free UDP port trio found for process tests")


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo = Path(__file__).resolve().parents[1]
        cls.runtime = tempfile.TemporaryDirectory(prefix="comms-e2e-")
        cls.log = tempfile.TemporaryFile(mode="w+b")
        http_port, udp_port = reserve_ports()
        cls.url = f"http://127.0.0.1:{http_port}"
        env = os.environ.copy()
        env.update(
            COMMS_HTTP_PORT=str(http_port),
            COMMS_HTTP_HOST="127.0.0.1",
            COMMS_UDP_PORT=str(udp_port),
            COMMS_RUNTIME_DIR=cls.runtime.name,
            PYTHONUNBUFFERED="1",
        )
        cls.process = subprocess.Popen(
            [sys.executable, "-m", "comms.supervisor"],
            cwd=cls.repo,
            env=env,
            stdout=cls.log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            cls.wait_for(
                lambda state: all(
                    state.get("vehicles", {}).get(name, {}).get("connected")
                    for name in ("rover", "drone")
                ),
                timeout=12,
            )
        except BaseException:
            cls.stop_process()
            cls.log.seek(0)
            output = cls.log.read().decode(errors="replace")[-6000:]
            for logfile in sorted(Path(cls.runtime.name).glob("*.log")):
                output += f"\n{logfile.name}:\n" + logfile.read_text(errors="replace")[-2000:]
            cls.log.close()
            cls.runtime.cleanup()
            raise AssertionError(f"Simulation did not become ready.\n{output}")

    @classmethod
    def stop_process(cls):
        # The group includes vehicle children even if supervisor exited early.
        try:
            os.killpg(cls.process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(cls.process.pid, signal.SIGKILL)
            cls.process.wait(timeout=3)

    @classmethod
    def tearDownClass(cls):
        cls.stop_process()
        cls.log.close()
        cls.runtime.cleanup()

    @classmethod
    def request(cls, path, body=None, token=None):
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if token is not None:
            headers["X-CSRF-Token"] = token
        req = urllib.request.Request(
            cls.url + path,
            data=None if body is None else json.dumps(body).encode(),
            headers=headers,
        )
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)

    @classmethod
    def wait_for(cls, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        last_state = None
        last_error = None
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise AssertionError("Supervisor exited during process test")
            try:
                last_state = cls.request("/api/state")
                if predicate(last_state):
                    return last_state
            except (OSError, ValueError) as error:
                last_error = str(error)
            time.sleep(0.05)
        raise AssertionError(
            f"State condition timed out: {last_error}; "
            f"vehicles={None if last_state is None else last_state.get('vehicles')}; "
            f"recent commands={None if last_state is None else last_state.get('commands', [])[-5:]}"
        )

    def setUp(self):
        self.token = self.request("/api/state")["csrf_token"]
        self.request("/api/faults", {}, self.token)
        self.wait_for(
            lambda state: all(
                state["vehicles"][name]["connected"]
                and state["vehicles"][name]["synced"]
                for name in ("rover", "drone")
            )
        )
        self.command_record(self.command("rover", "STOP")["id"], "completed")
        self.command_record(
            self.command("rover", "SET_MISSION", {"mission": "delivery"})["id"],
            "completed",
        )

    def tearDown(self):
        # A C2 restart deliberately rotates the token.
        token = self.request("/api/state")["csrf_token"]
        self.request("/api/faults", {}, token)

    def command(self, vehicle, action, args=None):
        return self.request(
            "/api/command",
            {"vehicle": vehicle, "action": action, "args": args or {}},
            self.token,
        )

    def command_record(self, command_id, status, timeout=6):
        state = self.wait_for(
            lambda state: any(
                item["id"] == command_id and item["status"] == status
                for item in state["commands"]
            ),
            timeout=timeout,
        )
        return next(item for item in state["commands"] if item["id"] == command_id)

    def start_autonomous_route(self):
        """Use the public package/activation workflow to start a long enough route."""
        package = {
            "schema_version": 1,
            "package_id": "process-test-" + uuid.uuid4().hex,
            "version": 1,
            "crs": "EPSG:4326",
            "units": "degrees",
            "synthetic": True,
            "source": "simulated-drone",
            "waypoints": [
                {"lat": 38.418 + i * 0.00001, "lon": -110.777}
                for i in range(40)
            ],
        }
        transfer = self.request("/api/transfer", {"package": package}, self.token)
        self.wait_for(
            lambda state: any(
                item["id"] == transfer["id"] and item["status"] == "accepted"
                for item in state["transfers"]
            )
        )
        self.command_record(
            self.command(
                "rover", "ACTIVATE_PACKAGE", {"package_id": package["package_id"]}
            )["id"],
            "completed",
        )
        self.command_record(self.command("drone", "DRONE_LAND")["id"], "completed")
        self.command_record(
            self.command("drone", "SET_MISSION", {"mission": "route_finding"})["id"],
            "completed",
        )
        self.command_record(
            self.command("rover", "SET_MISSION", {"mission": "route_finding"})["id"],
            "completed",
        )
        self.wait_for(
            lambda state: state["vehicles"]["rover"]["state"]["drone_state_fresh"]
            and state["vehicles"]["drone"]["state"].get("flight_locked")
        )
        # The flight lock reaches rover through periodic authenticated forwarding.
        time.sleep(0.6)
        route = self.command("rover", "START_ROUTE")
        self.command_record(route["id"], "accepted")
        return self.wait_for(
            lambda state: state["vehicles"]["rover"]["state"]["moving"]
        )

    def restart_child(self, name):
        pids = json.loads((Path(self.runtime.name) / "processes.json").read_text())
        os.kill(pids[name], signal.SIGKILL)

    def test_ack_loss_cannot_report_command_completion(self):
        self.request("/api/faults", {"ack_loss": 1.0}, self.token)
        command = self.command("rover", "STOP")
        record = self.command_record(command["id"], "timeout", timeout=12)
        self.assertEqual(record["vehicle"], "rover")
        # Fresh telemetry alone must not substitute for an acknowledgement.
        self.assertTrue(self.request("/api/state")["vehicles"]["rover"]["connected"])

    def test_both_simulators_publish_fresh_telemetry(self):
        vehicles = self.request("/api/state")["vehicles"]
        for name in ("rover", "drone"):
            with self.subTest(vehicle=name):
                self.assertTrue(vehicles[name]["connected"])
                self.assertTrue(vehicles[name]["boot_id"])
                self.assertLess(vehicles[name]["age_s"], 2)
                self.assertIsInstance(vehicles[name]["state"], dict)

    def test_command_post_requires_csrf_token(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request(
                "/api/command", {"vehicle": "rover", "action": "STOP", "args": {}}
            )
        self.assertEqual(caught.exception.code, 403)

    def test_demo_cli_observes_acknowledged_stop(self):
        result = subprocess.run(
            [sys.executable, str(self.repo / "scripts" / "demo.py"), "--url", self.url],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        decoder = json.JSONDecoder()
        telemetry, offset = decoder.raw_decode(result.stdout)
        final = json.loads(result.stdout[offset:])
        self.assertIn("rover", telemetry["vehicles"])
        self.assertEqual(final["command"]["action"], "STOP")
        self.assertEqual(final["command"]["status"], "completed")

    def test_delayed_duplicated_reordered_transport_confirms_stop(self):
        baseline = self.request("/api/state")["metrics"]["duplicated"]
        self.request(
            "/api/faults",
            {"delay_ms": 30, "jitter_ms": 10, "duplicate": 1.0, "reorder": 0.7},
            self.token,
        )
        for vehicle in ("rover", "drone"):
            with self.subTest(vehicle=vehicle):
                command = self.command(vehicle, "STOP")
                self.command_record(command["id"], "completed")
        self.assertGreater(self.request("/api/state")["metrics"]["duplicated"], baseline)

    def test_stop_is_acknowledged_by_each_vehicle(self):
        for vehicle in ("rover", "drone"):
            with self.subTest(vehicle=vehicle):
                command = self.command(vehicle, "STOP")
                record = self.command_record(command["id"], "completed")
                self.assertEqual(record["vehicle"], vehicle)
                self.assertEqual(record["action"], "STOP")

    def test_telemetry_loss_denies_new_control(self):
        self.request("/api/faults", {"telemetry_only": True}, self.token)
        self.wait_for(lambda state: not state["vehicles"]["rover"]["connected"])
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.command("rover", "CLAIM_CONTROL")
        self.assertEqual(caught.exception.code, 400)
        self.assertIn("stale", json.load(caught.exception)["error"].lower())

    def test_rover_restart_discards_autonomous_motion(self):
        moving = self.start_autonomous_route()
        old_boot = moving["vehicles"]["rover"]["boot_id"]
        self.restart_child("rover")
        state = self.wait_for(
            lambda state: state["vehicles"]["rover"]["boot_id"] != old_boot
            and state["vehicles"]["rover"]["synced"]
        )
        rover = state["vehicles"]["rover"]["state"]
        self.assertFalse(rover["moving"])
        self.assertEqual(rover["mode"], "stopped")
        self.assertIsNone(rover["lease_id"])
        self.assertIsNone(rover["active_package"])

    def test_drone_restart_discards_flight_and_survey_state(self):
        self.wait_for(
            lambda state: state["vehicles"]["rover"]["state"]["mission"] == "delivery"
        )
        # Wait for periodic rover mission forwarding before releasing flight lock.
        time.sleep(0.6)
        self.command_record(
            self.command("drone", "SET_MISSION", {"mission": "delivery"})["id"],
            "completed",
        )
        self.command_record(self.command("drone", "DRONE_TAKEOFF")["id"], "completed")
        self.command_record(self.command("drone", "DRONE_SURVEY")["id"], "completed")
        airborne = self.wait_for(
            lambda state: state["vehicles"]["drone"]["state"].get("survey_product")
            and state["vehicles"]["drone"]["state"]["flight_state"] == "airborne"
        )
        old_boot = airborne["vehicles"]["drone"]["boot_id"]
        self.restart_child("drone")
        state = self.wait_for(
            lambda state: state["vehicles"]["drone"]["boot_id"] != old_boot
            and state["vehicles"]["drone"]["synced"]
        )
        drone = state["vehicles"]["drone"]["state"]
        self.assertEqual(drone["flight_state"], "landed")
        self.assertEqual(drone["mode"], "stopped")
        self.assertFalse(drone["moving"])
        self.assertNotIn("survey_product", drone)
        time.sleep(0.4)
        self.assertEqual(
            self.request("/api/state")["vehicles"]["drone"]["state"]["flight_state"],
            "landed",
        )

    def test_c2_restart_reconciles_autonomous_rover_to_stopped(self):
        moving = self.start_autonomous_route()
        old_session = moving["session"]
        old_boot = moving["vehicles"]["rover"]["boot_id"]
        self.restart_child("c2")
        state = self.wait_for(
            lambda state: state["session"] != old_session
            and state["vehicles"]["rover"]["synced"]
            and state["vehicles"]["rover"]["state"].get("session") == state["session"]
        )
        self.token = state["csrf_token"]
        rover = state["vehicles"]["rover"]
        self.assertEqual(rover["boot_id"], old_boot)
        self.assertFalse(rover["state"]["moving"])
        self.assertEqual(rover["state"]["mode"], "stopped")
        # Reconnection alone cannot issue a fresh START_ROUTE.
        time.sleep(0.4)
        self.assertFalse(self.request("/api/state")["vehicles"]["rover"]["state"]["moving"])


if __name__ == "__main__":
    unittest.main()
