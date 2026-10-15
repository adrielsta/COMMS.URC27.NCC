"""Independent rover/drone simulators. There are no physical hardware adapters."""
import argparse
import copy
import math
import secrets
import socket
import time
from collections import OrderedDict
from pathlib import Path

from .packages import PackageError, PackageStore
from .protocol import ProtocolError, decode_message, encode_message
from .health import SimulatedHealth

WINDOW_TTL = 1.25
LEASE_TTL = 0.8
DRONE_TTL = 1.5
ROUTE_STEP_SECONDS = 0.25
MISSIONS = {"delivery", "assistance", "route_finding", "service"}
DATA_ACTIONS = {"PACKAGE_BEGIN", "PACKAGE_CHUNK", "PACKAGE_COMMIT", "DRONE_STATE", "ROVER_STATE"}
START_POSITION = {"lat": 38.418, "lon": -110.777}


def _fields(args, required=(), optional=()):
    if not isinstance(args, dict) or not set(required) <= args.keys() or args.keys() - set(required) - set(optional):
        raise ValueError("invalid action arguments")


class Vehicle:
    """State machine with an injectable receiver-local monotonic clock."""

    def __init__(self, kind, *, clock=time.monotonic, boot_id=None):
        if kind not in ("rover", "drone"):
            raise ValueError("unknown vehicle kind")
        self.kind = kind
        self.clock = clock
        self.boot_id = boot_id or secrets.token_hex(16)
        self.session = None
        self.retired_sessions = OrderedDict()
        self.last_seq = -1
        self.telemetry_seq = 0
        self.windows = OrderedDict()
        self.acks = OrderedDict()
        self.outbox = []
        self.packages = PackageStore()
        self.mode = "stopped"
        self.mission = "delivery"
        self.position = copy.deepcopy(START_POSITION)
        self.moving = False
        self.flight_state = "landed"
        self.at_designated_pad = True
        self.lease_id = None
        self.lease_until = 0.0
        self.speed = 0.0
        self.drone_report = None
        self.drone_seen = 0.0
        self.retired_drone_boots = OrderedDict()
        self.rover_report = None
        self.rover_seen = 0.0
        self.retired_rover_boots = OrderedDict()
        self.visited = [copy.deepcopy(self.position)]
        self.route = []
        self.route_index = 0
        self.route_at = 0.0
        self.route_command = None
        self.route_status = {"status": "idle", "index": 0, "count": 0}
        self.interventions = []
        self.survey_product = None
        self.survey_version = 0
        self.last_tick = self.clock()
        self.health = SimulatedHealth() if kind == 'rover' else None

    @staticmethod
    def _bounded_put(mapping, key, value, limit):
        mapping[key] = value
        mapping.move_to_end(key)
        while len(mapping) > limit:
            mapping.popitem(last=False)

    def snapshot(self):
        state = {
            "mode": self.mode, "mission": self.mission, "position": copy.deepcopy(self.position),
            "moving": self.moving, "flight_state": self.flight_state, "at_designated_pad": self.at_designated_pad,
            "lease_id": self.lease_id, "active_package": self.packages.active_package,
            "packages": self.packages.summaries(), "synthetic": True,
            "route_status": copy.deepcopy(self.route_status), "interventions": copy.deepcopy(self.interventions[-8:]),
            "session": self.session,
            "indicator": "red" if self.mode in ("autonomous", "recovering") else (
                "blue" if self.mode == "manual" else (
                    "flashing_green" if self.route_status["status"] == "completed" else "off")),
        }
        if self.kind == "drone":
            state["flight_locked"] = self.mission == "route_finding"
        if self.packages.last_transfer is not None:
            state["transfer"] = copy.deepcopy(self.packages.last_transfer)
        if self.kind == "drone" and self.survey_product is not None:
            state["survey_product"] = copy.deepcopy(self.survey_product)
        if self.kind == "rover":
            state["health"] = self.health.sample(self.clock(), self.moving)
            state["drone_state_fresh"] = self.drone_report is not None and self.clock() - self.drone_seen < DRONE_TTL
        return state

    def telemetry(self):
        now = self.clock()
        self._advance(now)
        for token in list(self.windows):
            if self.windows[token] <= now:
                del self.windows[token]
        token = secrets.token_hex(12)
        self._bounded_put(self.windows, token, now + WINDOW_TTL, 16)
        self.telemetry_seq += 1
        return {"kind": "telemetry", "vehicle": self.kind, "boot_id": self.boot_id,
                "seq": self.telemetry_seq, "window": token, "state": self.snapshot()}

    def _ack(self, command, status, reason):
        return {"kind": "ack", "vehicle": self.kind, "boot_id": self.boot_id,
                "session": command["session"], "id": command["id"], "status": status,
                "reason": reason[:512], "state": self.snapshot()}

    def _cache(self, command, ack):
        self._bounded_put(self.acks, (command["session"], command["id"]), copy.deepcopy(ack), 256)
        return ack

    def _intervention(self, action):
        if self.mission in ("route_finding", "assistance"):
            self.interventions.append({"action": action, "mission": self.mission,
                                       "rule": "1.e.xviii" if self.mission == "route_finding" else "1.e.xi",
                                       "potential_penalty_percent": 50 if action == "MANUAL" else 20,
                                       "note": "operator intervention context; judges determine scoring"})
            self.interventions = self.interventions[-8:]

    def _end_route(self, status, reason):
        command = self.route_command
        self.route_command = None
        self.route_status["status"] = status
        if command is not None:
            ack = self._cache(command, self._ack(command, status, reason))
            self.outbox.append(ack)
            self.outbox = self.outbox[-16:]

    def _stop(self, reason):
        self.moving = False
        self.mode = "stopped"
        self.speed = 0.0
        self.lease_id = None
        self.lease_until = 0.0
        if self.route_command is not None:
            self._end_route("rejected", "route cancelled: " + reason)
        self.route = []

    def _advance(self, now):
        dt = max(0.0, min(now - self.last_tick, 0.25))
        self.last_tick = now
        if self.lease_id is not None and now >= self.lease_until:
            self._stop("manual authority expired")
        if self.mode == "manual" and self.moving:
            self.position["lat"] = max(38.410, min(38.426, self.position["lat"] + self.speed * dt * 0.00002))
        if self.mode in ("autonomous", "recovering") and self.route_command is not None:
            # Onboard route execution deliberately continues during C2 radio loss.
            while self.route_index < len(self.route) and now >= self.route_at:
                self.position = copy.deepcopy(self.route[self.route_index])
                if self.mode == "autonomous":
                    self.visited.append(copy.deepcopy(self.position))
                    self.visited = self.visited[-129:]
                elif len(self.visited) > 1:
                    self.visited.pop()
                self.route_index += 1
                self.route_at += ROUTE_STEP_SECONDS
                self.route_status["index"] = self.route_index
            if self.route_index == len(self.route):
                self.moving = False
                self.mode = "stopped"
                self._end_route("completed", "synthetic route completed onboard")

    def tick(self):
        self._advance(self.clock())
        result, self.outbox = self.outbox, []
        return result

    def handle_command(self, command):
        now = self.clock()
        self._advance(now)
        # Network input has already passed protocol validation. Keep direct callers
        # equally strict, and never manufacture an ACK for an unidentifiable packet.
        from .protocol import _validate
        _validate(command)
        if command["kind"] != "command":
            raise ProtocolError("expected command")
        if command["vehicle"] != self.kind or command["boot_id"] != self.boot_id:
            return self._ack(command, "rejected", "vehicle boot identity mismatch")
        cached = self.acks.get((command["session"], command["id"]))
        if cached is not None:
            return copy.deepcopy(cached)
        if self.windows.get(command["window"], 0.0) <= now:
            return self._cache(command, self._ack(command, "rejected", "receiver-issued command window expired or unknown"))
        if command["session"] in self.retired_sessions:
            return self._cache(command, self._ack(command, "rejected", "retired C2 session"))
        action, args = command["action"], command["args"]
        if action == "SYNC":
            try:
                _fields(args)
            except ValueError as exc:
                return self._cache(command, self._ack(command, "rejected", str(exc)))
            if self.session != command["session"]:
                if self.session is not None:
                    self._bounded_put(self.retired_sessions, self.session, True, 64)
                self._stop("C2 session changed; explicit new motion command required")
                # A replacement C2 must reconcile both vehicles before its new
                # commands can rely on landing/mission reports from the old C2.
                self.drone_seen = float("-inf")
                self.rover_seen = float("-inf")
                self.session = command["session"]
                self.last_seq = -1
            elif command["seq"] <= self.last_seq:
                return self._cache(command, self._ack(command, "rejected", "reordered command sequence"))
            self.last_seq = command["seq"]
            return self._cache(command, self._ack(command, "completed", "session synchronized; state reconciled"))
        if command["session"] != self.session:
            return self._cache(command, self._ack(command, "rejected", "SYNC required for this C2 session"))
        # Priority scheduling can legitimately deliver STOP ahead of older bulk
        # packets, or fresh peer reports ahead of actuation. Data messages use
        # transfer identity/index or peer boot/sequence checks instead of the
        # actuation sequence; all still require this session and a live window.
        if action not in DATA_ACTIONS:
            if command["seq"] <= self.last_seq and action != "STOP":
                return self._cache(command, self._ack(command, "rejected", "reordered command sequence"))
            self.last_seq = max(self.last_seq, command["seq"])
        try:
            status, reason = self._action(action, args, command, now)
            ack = self._ack(command, status, reason)
        except (ValueError, TypeError, KeyError) as exc:
            ack = self._ack(command, "rejected", str(exc))
        return self._cache(command, ack)

    def _action(self, action, args, command, now):
        if action == "STOP":
            _fields(args)
            self._intervention(action)
            self._stop("software STOP requested by C2")
            return "completed", "software motion stop confirmed; physical E-stop is separate"
        if action == "SET_MISSION":
            _fields(args, ("mission",))
            if args["mission"] not in MISSIONS:
                raise ValueError("unknown mission")
            if self.moving or self.flight_state != "landed":
                raise ValueError("mission change requires stopped/landed vehicle")
            if self.kind == "drone" and self.mission == "route_finding" and args["mission"] != "route_finding":
                if self.rover_report is None or now - self.rover_seen >= DRONE_TTL or self.rover_report["mission"] == "route_finding":
                    raise ValueError("flight lock release requires fresh rover state outside route_finding")
            self._stop("mission changed")
            self.mission = args["mission"]
            return "completed", "mission changed"
        if action == "DRONE_STATE":
            if self.kind != "rover":
                raise ValueError("drone-state forwarding is rover-only")
            _fields(args, ("boot_id", "seq", "flight_state", "at_designated_pad", "flight_locked"))
            if not isinstance(args["boot_id"], str) or not 1 <= len(args["boot_id"]) <= 128 or type(args["seq"]) is not int or args["seq"] < 0:
                raise ValueError("invalid drone identity/sequence")
            if args["flight_state"] not in ("landed", "airborne") or type(args["at_designated_pad"]) is not bool or type(args["flight_locked"]) is not bool:
                raise ValueError("invalid drone state")
            if args["boot_id"] in self.retired_drone_boots:
                raise ValueError("retired drone boot")
            if self.drone_report is not None:
                if args["boot_id"] == self.drone_report["boot_id"] and args["seq"] <= self.drone_report["seq"]:
                    raise ValueError("duplicate/reordered drone report does not refresh landing state")
                if args["boot_id"] != self.drone_report["boot_id"]:
                    self._bounded_put(self.retired_drone_boots, self.drone_report["boot_id"], True, 16)
            self.drone_report, self.drone_seen = copy.deepcopy(args), now
            return "completed", "fresh drone state recorded using receiver-local time"
        if action == "ROVER_STATE":
            if self.kind != "drone":
                raise ValueError("rover-state forwarding is drone-only")
            _fields(args, ("boot_id", "seq", "mission", "mode", "moving"))
            if not isinstance(args["boot_id"], str) or not 1 <= len(args["boot_id"]) <= 128 or type(args["seq"]) is not int or args["seq"] < 0:
                raise ValueError("invalid rover identity/sequence")
            if args["mission"] not in MISSIONS or args["mode"] not in ("stopped", "manual", "autonomous", "recovering") or type(args["moving"]) is not bool:
                raise ValueError("invalid rover state")
            if args["boot_id"] in self.retired_rover_boots:
                raise ValueError("retired rover boot")
            if self.rover_report is not None:
                if args["boot_id"] == self.rover_report["boot_id"] and args["seq"] <= self.rover_report["seq"]:
                    raise ValueError("duplicate/reordered rover report does not refresh flight permission")
                if args["boot_id"] != self.rover_report["boot_id"]:
                    self._bounded_put(self.retired_rover_boots, self.rover_report["boot_id"], True, 16)
            self.rover_report, self.rover_seen = copy.deepcopy(args), now
            return "completed", "fresh rover mission recorded using receiver-local time"
        if action.startswith("DRONE_"):
            return self._drone_action(action, args)
        if self.kind != "rover":
            raise ValueError("action requires rover")
        if action == 'SIM_HEALTH_FAULT':
            _fields(args, ('component', 'fault'))
            self.health.inject(args['component'], args['fault'])
            return 'completed', 'simulation health model updated; physical hardware and motion policy are unchanged'
        if action in ("PACKAGE_BEGIN", "PACKAGE_CHUNK", "PACKAGE_COMMIT") and self.moving:
            raise ValueError("package changes require a stopped rover (1.e.iii)")
        if action == "CLAIM_CONTROL":
            _fields(args)
            if self.mission in ("route_finding", "assistance"):
                rule = "1.e.xviii" if self.mission == "route_finding" else "1.e.xi"
                raise ValueError("arbitrary manual control is disabled during " + self.mission + " (" + rule + ")")
            if self.moving and self.mode != "manual":
                raise ValueError("STOP autonomous motion before claiming manual control")
            self.lease_id = secrets.token_hex(12)
            self.lease_until = now + LEASE_TTL
            return "completed", "receiver-local manual lease granted for 0.8 seconds"
        if action == "MANUAL":
            _fields(args, ("speed", "lease_id"))
            if self.mission in ("route_finding", "assistance"):
                rule = "1.e.xviii" if self.mission == "route_finding" else "1.e.xi"
                raise ValueError("arbitrary manual motion is forbidden during " + self.mission + " (" + rule + ")")
            if not isinstance(args["lease_id"], str) or args["lease_id"] != self.lease_id or now >= self.lease_until:
                raise ValueError("valid receiver-local manual lease required")
            if type(args["speed"]) not in (float, int) or not math.isfinite(args["speed"]) or not -1 <= args["speed"] <= 1:
                raise ValueError("manual speed must be finite and within [-1,1]")
            if self.route_command is not None:
                raise ValueError("STOP autonomous motion before manual control")
            if args["speed"] != 0 and self.mode != "manual":
                self._intervention(action)
            self.speed = args["speed"]
            self.moving = self.speed != 0
            self.mode = "manual" if self.moving else "stopped"
            return "completed", "manual state applied; lease expiry is unchanged"
        if action == "PACKAGE_BEGIN":
            self.packages.begin(args)
            return "completed", "upload metadata accepted; package inactive"
        if action == "PACKAGE_CHUNK":
            self.packages.chunk(args)
            return "completed", "chunk stored; package inactive"
        if action == "PACKAGE_COMMIT":
            self.packages.commit(args)
            return "completed", "package integrity/schema validated; explicit activation required"
        if action == "ACTIVATE_PACKAGE":
            _fields(args, ("package_id",))
            self.packages.activate(args["package_id"], stopped=not self.moving)
            return "completed", "validated package activated while stopped (1.e.iii)"
        if action == "START_ROUTE":
            _fields(args)
            if self.mission != "route_finding":
                raise ValueError("START_ROUTE requires route_finding mission")
            if self.moving:
                raise ValueError("route departure requires stopped rover")
            if self.drone_report is None or now - self.drone_seen >= DRONE_TTL:
                raise ValueError("fresh authenticated drone landing state required (1.e.xiv)")
            if self.drone_report["flight_state"] != "landed" or not self.drone_report["at_designated_pad"] or not self.drone_report["flight_locked"]:
                raise ValueError("drone must be landed at designated pad with route-finding flight lock before departure (1.e.xiv)")
            identity = self.packages.active_package
            if identity is None:
                raise ValueError("validated active package required")
            self.visited = [copy.deepcopy(self.position)]
            self._start_route(self.packages.validated[identity]["waypoints"], command, now, "autonomous")
            return "accepted", "synthetic route executing onboard; completion will be acknowledged"
        if action == "RECOVER_ROUTE":
            _fields(args)
            if self.mission != "route_finding" or len(self.visited) < 2:
                raise ValueError("recovery requires previously traversed route-finding points")
            self._intervention(action)
            self._stop("operator requested return along visited route")
            points = list(reversed(self.visited[:-1]))
            self._start_route(points, command, now, "recovering")
            return "accepted", "synthetic autonomous return along visited points (1.e.xviii); not teleoperation"
        raise ValueError("unknown command action")

    def _start_route(self, points, command, now, mode):
        self.lease_id = None
        self.lease_until = 0.0
        self.route = copy.deepcopy(points)
        self.route_index = 0
        self.route_at = now + ROUTE_STEP_SECONDS
        self.route_command = copy.deepcopy(command)
        self.route_status = {"status": "accepted", "index": 0, "count": len(points), "command_id": command["id"]}
        self.mode, self.moving = mode, True

    def _drone_action(self, action, args):
        if self.kind != "drone":
            raise ValueError("action requires drone")
        _fields(args)
        if action in ("DRONE_TAKEOFF", "DRONE_SURVEY"):
            if self.rover_report is None or self.clock() - self.rover_seen >= DRONE_TTL:
                raise ValueError("fresh rover mission state required for reconnaissance")
            if self.rover_report["mission"] not in ("delivery", "assistance") or self.rover_report["mode"] in ("autonomous", "recovering"):
                raise ValueError("rover mission/route state forbids reconnaissance (1.e.xiv)")
        if action == "DRONE_TAKEOFF":
            if self.mission not in ("delivery", "assistance"):
                raise ValueError("drone launch restricted to delivery/astronaut assistance phase (1.e.xiv)")
            if self.flight_state != "landed":
                raise ValueError("drone is already airborne")
            self.flight_state, self.at_designated_pad, self.mode = "airborne", False, "hovering"
            self.moving = False
            return "completed", "synthetic drone airborne; no flight controller connected"
        if action == "DRONE_LAND":
            self.flight_state, self.at_designated_pad, self.mode = "landed", True, "stopped"
            self.moving = False
            return "completed", "synthetic drone landed at designated pad"
        if action == "DRONE_SURVEY":
            if self.flight_state != "airborne":
                raise ValueError("survey requires airborne drone")
            if self.mission not in ("delivery", "assistance"):
                raise ValueError("reconnaissance restricted to delivery/astronaut assistance phase (1.e.xiv)")
            self.survey_version += 1
            self.survey_product = {"schema_version": 1, "package_id": "survey-" + self.boot_id[:8] + "-" + str(self.survey_version),
                                   "version": self.survey_version, "crs": "EPSG:4326", "units": "degrees", "synthetic": True,
                                   "source": "simulated-drone", "waypoints": [
                                       {"lat": 38.4181, "lon": -110.777}, {"lat": 38.4182, "lon": -110.7769},
                                       {"lat": 38.4183, "lon": -110.7768}, {"lat": 38.4184, "lon": -110.7767}]}
            return "completed", "synthetic survey product ready for C2 review; no terrain sensing/planning"
        raise ValueError("unknown drone command")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", required=True, choices=("rover", "drone"))
    parser.add_argument("--port", required=True, type=int)
    parser.add_argument("--c2-port", default=12050, type=int)
    parser.add_argument("--key-file", required=True)
    args = parser.parse_args()
    key = Path(args.key_file).read_bytes()
    if len(key) < 32:
        parser.error("key file must contain at least 32 random bytes")
    vehicle = Vehicle(args.kind)
    endpoint = ("127.0.0.1", args.c2_port)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("127.0.0.1", args.port))
    sock.settimeout(0.02)
    next_telemetry = time.monotonic()
    print(f"SIMULATION {args.kind} UDP 127.0.0.1:{args.port}; boot {vehicle.boot_id}", flush=True)
    try:
        while True:
            # Limit ingress per iteration: ticks and telemetry cannot be starved by bulk UDP.
            try:
                packet, source = sock.recvfrom(8225)
                if source == endpoint:
                    message = decode_message(packet, key)
                    if message["kind"] == "command":
                        sock.sendto(encode_message(vehicle.handle_command(message), key), endpoint)
            except (socket.timeout, ProtocolError, ValueError, OSError):
                pass
            for ack in vehicle.tick():
                sock.sendto(encode_message(ack, key), endpoint)
            now = time.monotonic()
            if now >= next_telemetry:
                sock.sendto(encode_message(vehicle.telemetry(), key), endpoint)
                next_telemetry = now + 0.2
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()


if __name__ == "__main__":
    main()
