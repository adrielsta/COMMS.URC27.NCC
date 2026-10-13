import base64
import hashlib
import unittest

from comms.packages import canonical_package
from comms.protocol import ProtocolError, decode_message, encode_message
from comms.vehicle import DRONE_TTL, LEASE_TTL, WINDOW_TTL, Vehicle


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class VehicleTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.vehicle = Vehicle("rover", clock=self.clock, boot_id="test-boot")
        self.seq = 0
        self.session = "test-session"
        self.assertEqual(self.send("SYNC")["status"], "completed")

    def command(self, action, args=None, **overrides):
        self.seq += 1
        message = {"kind": "command", "vehicle": self.vehicle.kind, "boot_id": self.vehicle.boot_id,
                   "session": self.session, "id": "cmd-" + str(self.seq), "seq": self.seq,
                   "window": self.vehicle.telemetry()["window"], "action": action, "args": args or {}}
        message.update(overrides)
        return message

    def send(self, action, args=None, **overrides):
        return self.vehicle.handle_command(self.command(action, args, **overrides))

    def prepare_route(self):
        value = {"schema_version": 1, "package_id": "demo", "version": 1, "crs": "EPSG:4326", "units": "degrees",
                 "synthetic": True, "source": "simulated-drone", "waypoints": [
                     {"lat": 38.4181, "lon": -110.777}, {"lat": 38.4182, "lon": -110.777},
                     {"lat": 38.4183, "lon": -110.777}, {"lat": 38.4184, "lon": -110.777}]}
        raw = canonical_package(value)
        for action, args in (("PACKAGE_BEGIN", {"package_id": "demo", "version": 1, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "chunks": 1}),
                             ("PACKAGE_CHUNK", {"package_id": "demo", "index": 0, "data": base64.b64encode(raw).decode()}),
                             ("PACKAGE_COMMIT", {"package_id": "demo"}), ("ACTIVATE_PACKAGE", {"package_id": "demo"}),
                             ("SET_MISSION", {"mission": "route_finding"})):
            self.assertEqual(self.send(action, args)["status"], "completed")

    def drone_report(self, seq=1, flight="landed", pad=True, boot="drone-boot", locked=True):
        return self.send("DRONE_STATE", {"boot_id": boot, "seq": seq, "flight_state": flight, "at_designated_pad": pad, "flight_locked": locked})

    def rover_report(self, seq=1, mission="assistance"):
        return self.send("ROVER_STATE", {"boot_id": "rover-boot", "seq": seq, "mission": mission, "mode": "stopped", "moving": False})

    def test_authentication_tamper_and_unknown_fields(self):
        key = b"k" * 32
        command = self.command("STOP")
        packet = encode_message(command, key)
        self.assertEqual(decode_message(packet, key), command)
        with self.assertRaises(ProtocolError):
            decode_message(packet, b"x" * 32)
        for change in ({"kind": "invented"}, {"remote_monotonic": 123}, {"seq": True}, {"args": {"speed": float("inf")}}):
            with self.subTest(change=change), self.assertRaises((ValueError, TypeError)):
                encode_message(dict(command, **change), key)

    def test_receiver_local_window_expiry(self):
        command = self.command("CLAIM_CONTROL")
        self.clock.advance(WINDOW_TTL + 0.01)
        ack = self.vehicle.handle_command(command)
        self.assertEqual(ack["status"], "rejected")
        self.assertIn("window", ack["reason"])
        self.assertIsNone(self.vehicle.lease_id)

    def test_manual_expiry_and_duplicate_do_not_extend_authority(self):
        claim = self.command("CLAIM_CONTROL")
        ack = self.vehicle.handle_command(claim)
        lease = ack["state"]["lease_id"]
        self.send("MANUAL", {"speed": 0.5, "lease_id": lease})
        self.assertTrue(self.vehicle.moving)
        self.clock.advance(0.5)
        self.assertEqual(self.vehicle.handle_command(claim), ack)
        self.clock.advance(LEASE_TTL - 0.5 + 0.01)
        self.vehicle.tick()
        self.assertFalse(self.vehicle.moving)
        self.assertIsNone(self.vehicle.lease_id)

    def test_reordered_command_and_wrong_boot_rejected(self):
        old = self.command("CLAIM_CONTROL")
        self.send("STOP")
        self.assertIn("reordered", self.vehicle.handle_command(old)["reason"])
        self.assertIn("identity", self.send("CLAIM_CONTROL", boot_id="old-boot")["reason"])

    def test_fresh_reordered_stop_remains_effective(self):
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        self.send("MANUAL", {"speed": 1, "lease_id": lease})
        stop = self.command("STOP")
        self.send("CLAIM_CONTROL")
        self.assertEqual(self.vehicle.handle_command(stop)["status"], "completed")
        self.assertFalse(self.vehicle.moving)

    def test_priority_stop_does_not_invalidate_older_bulk_data(self):
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        begin = self.command("PACKAGE_BEGIN", {"package_id": "pending", "version": 1,
                                               "size": 1, "sha256": "0" * 64, "chunks": 1})
        manual = self.command("MANUAL", {"speed": 1, "lease_id": lease})
        self.assertEqual(self.send("STOP")["status"], "completed")
        stop_seq = self.vehicle.last_seq
        self.assertEqual(self.vehicle.handle_command(begin)["status"], "completed")
        self.assertEqual(self.vehicle.last_seq, stop_seq)
        ack = self.vehicle.handle_command(manual)
        self.assertEqual(ack["status"], "rejected")
        self.assertIn("reordered", ack["reason"])
        self.assertFalse(self.vehicle.moving)

    def test_newer_peer_report_does_not_suppress_pending_actuation(self):
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        manual = self.command("MANUAL", {"speed": 0.5, "lease_id": lease})
        self.assertEqual(self.drone_report()["status"], "completed")
        self.assertEqual(self.vehicle.handle_command(manual)["status"], "completed")
        self.assertTrue(self.vehicle.moving)

    def test_session_replacement_stops_and_retires(self):
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        self.send("MANUAL", {"speed": 1, "lease_id": lease})
        self.session = "new-session"
        self.assertEqual(self.send("SYNC")["status"], "completed")
        self.assertFalse(self.vehicle.moving)
        self.assertIn("retired", self.send("SYNC", session="test-session")["reason"])
        self.assertEqual(self.vehicle.session, "new-session")

    def test_route_requires_fresh_designated_pad_landing(self):
        self.prepare_route()
        self.assertEqual(self.send("START_ROUTE")["status"], "rejected")
        self.drone_report(flight="airborne", pad=False)
        self.assertEqual(self.send("START_ROUTE")["status"], "rejected")
        self.drone_report(seq=2, pad=False)
        self.assertEqual(self.send("START_ROUTE")["status"], "rejected")
        self.drone_report(seq=3)
        self.clock.advance(DRONE_TTL + 0.01)
        self.assertEqual(self.send("START_ROUTE")["status"], "rejected")
        self.drone_report(seq=4, locked=False)
        self.assertEqual(self.send("START_ROUTE")["status"], "rejected")
        self.drone_report(seq=5)
        self.assertEqual(self.send("START_ROUTE")["status"], "accepted")

    def test_duplicate_drone_report_does_not_refresh(self):
        self.drone_report()
        self.clock.advance(DRONE_TTL - 0.1)
        self.assertEqual(self.drone_report()["status"], "rejected")
        self.clock.advance(0.2)
        self.assertFalse(self.vehicle.snapshot()["drone_state_fresh"])
        self.assertEqual(self.drone_report(boot="new-drone")["status"], "completed")
        self.assertEqual(self.drone_report(seq=3)["status"], "rejected")

    def test_new_session_requires_new_peer_report(self):
        self.prepare_route()
        self.drone_report()
        self.session = "replacement-c2"
        self.send("SYNC")
        self.assertFalse(self.vehicle.snapshot()["drone_state_fresh"])
        self.assertEqual(self.send("START_ROUTE")["status"], "rejected")
        self.assertEqual(self.drone_report()["status"], "rejected")
        self.assertEqual(self.drone_report(seq=2)["status"], "completed")
        self.assertEqual(self.send("START_ROUTE")["status"], "accepted")

    def test_route_continues_without_link_and_completes(self):
        self.prepare_route()
        self.drone_report()
        command = self.command("START_ROUTE")
        self.assertEqual(self.vehicle.handle_command(command)["status"], "accepted")
        self.clock.advance(2)
        final = self.vehicle.tick()
        self.assertEqual(len(final), 1)
        self.assertEqual(final[0]["status"], "completed")
        self.assertFalse(self.vehicle.moving)
        self.assertEqual(self.vehicle.position["lat"], 38.4184)
        self.assertEqual(self.vehicle.handle_command(command)["status"], "completed")

    def test_stop_cancels_accepted_route(self):
        self.prepare_route()
        self.drone_report()
        accepted = self.send("START_ROUTE")
        self.send("STOP")
        final = self.vehicle.tick()
        self.assertEqual(final[0]["id"], accepted["id"])
        self.assertEqual(final[0]["status"], "rejected")
        self.assertIn("cancelled", final[0]["reason"])
        self.assertFalse(self.vehicle.moving)
        self.assertEqual(self.vehicle.interventions[-1]["rule"], "1.e.xviii")

    def test_session_change_cancels_route_and_does_not_resume(self):
        self.prepare_route()
        self.drone_report()
        self.send("START_ROUTE")
        self.session = "restarted-c2"
        self.send("SYNC")
        self.clock.advance(5)
        self.vehicle.tick()
        self.assertFalse(self.vehicle.moving)
        self.assertEqual(self.vehicle.position["lat"], 38.418)
        restarted = Vehicle("rover", clock=self.clock)
        self.assertNotEqual(restarted.boot_id, self.vehicle.boot_id)
        self.assertFalse(restarted.moving)
        self.assertIsNone(restarted.packages.active_package)

    def test_route_manual_rejection_and_visited_recovery(self):
        self.prepare_route()
        self.assertEqual(self.send("CLAIM_CONTROL")["status"], "rejected")
        self.assertEqual(self.send("MANUAL", {"speed": 1, "lease_id": "none"})["status"], "rejected")
        self.drone_report()
        self.send("START_ROUTE")
        self.clock.advance(0.51)
        self.vehicle.tick()
        visited = list(self.vehicle.visited)
        self.assertEqual(self.send("RECOVER_ROUTE")["status"], "accepted")
        self.assertTrue(all(point in visited for point in self.vehicle.route))
        self.clock.advance(1)
        self.vehicle.tick()
        self.assertEqual(self.vehicle.position, visited[0])
        self.assertEqual(self.send("RECOVER_ROUTE")["status"], "rejected")

    def test_assistance_manual_control_denied_without_recovery_model(self):
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        self.assertEqual(self.send("SET_MISSION", {"mission": "assistance"})["status"], "completed")
        for action, args in (("CLAIM_CONTROL", {}), ("MANUAL", {"speed": 1, "lease_id": lease})):
            with self.subTest(action=action):
                ack = self.send(action, args)
                self.assertEqual(ack["status"], "rejected")
                self.assertIn("1.e.xi", ack["reason"])
                self.assertFalse(self.vehicle.moving)
        self.assertEqual(self.send("SET_MISSION", {"mission": "service"})["status"], "completed")
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        self.assertEqual(self.send("MANUAL", {"speed": 0.5, "lease_id": lease})["status"], "completed")
        self.assertTrue(self.vehicle.moving)

    def test_activation_while_moving_and_invalid_manual_args_reject(self):
        self.prepare_route()
        self.send("SET_MISSION", {"mission": "delivery"})
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        self.assertEqual(self.send("MANUAL", {"speed": 2, "lease_id": lease})["status"], "rejected")
        self.send("MANUAL", {"speed": 1, "lease_id": lease})
        self.assertEqual(self.send("ACTIVATE_PACKAGE", {"package_id": "demo"})["status"], "rejected")
        self.assertEqual(self.send("SET_MISSION", {"mission": "assistance"})["status"], "rejected")

    def test_all_package_mutations_require_stopped_rover(self):
        self.prepare_route()
        raw = canonical_package(self.vehicle.packages.validated["demo"])
        commands = [
            ("PACKAGE_BEGIN", {"package_id": "demo", "version": 1, "size": len(raw),
                               "sha256": hashlib.sha256(raw).hexdigest(), "chunks": 1}),
            ("PACKAGE_CHUNK", {"package_id": "demo", "index": 0, "data": base64.b64encode(raw).decode()}),
            ("PACKAGE_COMMIT", {"package_id": "demo"}),
        ]
        self.drone_report()
        self.send("START_ROUTE")
        for action, args in commands:
            with self.subTest(mode="autonomous", action=action):
                ack = self.send(action, args)
                self.assertEqual(ack["status"], "rejected")
                self.assertIn("stopped rover (1.e.iii)", ack["reason"])
        self.send("STOP")
        self.send("SET_MISSION", {"mission": "delivery"})
        lease = self.send("CLAIM_CONTROL")["state"]["lease_id"]
        self.send("MANUAL", {"speed": 1, "lease_id": lease})
        for action, args in commands:
            with self.subTest(mode="manual", action=action):
                ack = self.send(action, args)
                self.assertEqual(ack["status"], "rejected")
                self.assertIn("stopped rover (1.e.iii)", ack["reason"])

    def test_drone_survey_and_mission_restrictions(self):
        self.vehicle = Vehicle("drone", clock=self.clock)
        self.send("SYNC")
        self.send("SET_MISSION", {"mission": "assistance"})
        self.rover_report()
        self.assertEqual(self.send("DRONE_SURVEY")["status"], "rejected")
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "completed")
        self.assertEqual(self.send("DRONE_SURVEY")["status"], "completed")
        self.assertTrue(self.vehicle.snapshot()["survey_product"]["synthetic"])
        self.send("STOP")
        self.assertEqual(self.vehicle.flight_state, "airborne")
        self.assertEqual(self.send("SET_MISSION", {"mission": "route_finding"})["status"], "rejected")
        self.send("DRONE_LAND")
        self.assertTrue(self.vehicle.at_designated_pad)
        self.send("SET_MISSION", {"mission": "route_finding"})
        self.assertTrue(self.vehicle.snapshot()["flight_locked"])
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "rejected")

    def test_drone_fresh_rover_state_and_lock_release_required(self):
        self.vehicle = Vehicle("drone", clock=self.clock)
        self.send("SYNC")
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "rejected")
        self.rover_report()
        self.clock.advance(DRONE_TTL + 0.01)
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "rejected")
        self.rover_report(seq=2, mission="route_finding")
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "rejected")
        self.send("SET_MISSION", {"mission": "route_finding"})
        self.assertEqual(self.send("SET_MISSION", {"mission": "assistance"})["status"], "rejected")
        self.rover_report(seq=3)
        self.assertEqual(self.send("SET_MISSION", {"mission": "assistance"})["status"], "completed")

    def test_drone_new_session_invalidates_previous_rover_permission(self):
        self.vehicle = Vehicle("drone", clock=self.clock)
        self.send("SYNC")
        self.rover_report()
        self.session = "replacement-c2"
        self.send("SYNC")
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "rejected")
        self.assertEqual(self.rover_report()["status"], "rejected")
        self.assertEqual(self.rover_report(seq=2)["status"], "completed")
        self.assertEqual(self.send("DRONE_TAKEOFF")["status"], "completed")

    def test_caches_bounded(self):
        for _ in range(300):
            self.send("STOP")
        self.assertLessEqual(len(self.vehicle.acks), 256)
        self.assertLessEqual(len(self.vehicle.windows), 16)


if __name__ == "__main__":
    unittest.main()
