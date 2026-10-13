"""Simulation C2: HTTP dashboard plus authenticated RoveComm UDP endpoints."""
import argparse
import base64
from collections import deque
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import socket
import threading
import time
from urllib.parse import urlsplit
import uuid

from .link import FaultLink
from .protocol import encode_message, decode_message

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_ACTIONS = {'STOP', 'CLAIM_CONTROL', 'MANUAL', 'SET_MISSION',
                  'START_ROUTE', 'RECOVER_ROUTE', 'DRONE_TAKEOFF',
                  'DRONE_SURVEY', 'DRONE_LAND', 'ACTIVATE_PACKAGE'}


class C2:
    def __init__(self, key, udp_port=12050, rover_port=12051, drone_port=12052):
        self.key = key
        self.session = uuid.uuid4().hex
        self.csrf = secrets.token_urlsafe(32)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', udp_port))
        self.sock.setblocking(False)
        self.peers = {'rover': ('127.0.0.1', rover_port), 'drone': ('127.0.0.1', drone_port)}
        self.lock = threading.RLock()
        self.vehicles = {v: {'boot_id': None, 'seq': -1, 'window': None,
                            'received': 0.0, 'state': {}, 'synced': False} for v in self.peers}
        self.seq = {'rover': 0, 'drone': 0}
        self.commands = deque(maxlen=256)
        self.events = deque(maxlen=256)
        self.pending = {}
        self.transfers = deque(maxlen=8)
        self.link = FaultLink()
        self.invalid = 0
        self.last_drone_forward = 0.0
        self.last_rover_forward = 0.0
        self.running = True
        self.event('info', 'SIMULATION C2 started; hardware adapters are not connected.')

    def event(self, level, message):
        self.events.append({'time': time.time(), 'level': level, 'message': str(message)[:300]})

    def connected(self, vehicle, now=None):
        v = self.vehicles[vehicle]
        return bool(v['boot_id']) and (now or time.monotonic()) - v['received'] < 1.0

    def command(self, vehicle, action, args=None, *, internal=False):
        if vehicle not in self.peers or not isinstance(action, str):
            raise ValueError('Unknown vehicle or command')
        if not internal and action not in PUBLIC_ACTIONS:
            raise ValueError('Command is not exposed to operators')
        if not isinstance(args or {}, dict):
            raise ValueError('Command args must be an object')
        v = self.vehicles[vehicle]
        if not v['boot_id'] or not v['window']:
            raise ValueError('No confirmed vehicle session; wait for telemetry')
        if action not in ('STOP', 'SYNC') and (not self.connected(vehicle) or not v['synced']):
            raise ValueError('Telemetry stale or session reconciliation pending; control denied')
        if action == 'DRONE_TAKEOFF' and (not self.connected('rover') or self.vehicles['rover']['state'].get('mission') == 'route_finding'):
            raise ValueError('Drone flight blocked while rover state is stale or route-finding is selected')
        if len(self.pending) >= (64 if action in ('STOP', 'SYNC') else 56):
            if action not in ('STOP', 'SYNC'):
                raise ValueError('Command queue full; wait for outstanding requests')
            # Safety/reconciliation admission can preempt other work; never block
            # STOP merely because bulk requests or lost ACKs fill the queue.
            victim = next((ident for ident, p in self.pending.items() if p['body']['action'] not in ('STOP', 'SYNC')), next(iter(self.pending)))
            old = self.pending.pop(victim)
            old['record'].update(status='timeout', reason='Superseded by safety/reconciliation request; outcome unconfirmed')
        self.seq[vehicle] += 1
        now = time.monotonic()
        body = {'kind': 'command', 'vehicle': vehicle, 'boot_id': v['boot_id'],
                'session': self.session, 'id': uuid.uuid4().hex,
                'seq': self.seq[vehicle], 'window': v['window'],
                'action': action, 'args': args or {}}
        packet = encode_message(body, self.key)
        rec = {'id': body['id'], 'vehicle': vehicle, 'action': action,
               'status': 'requested', 'reason': 'Awaiting vehicle acknowledgement',
               'created_at': time.time(), 'boot_id': v['boot_id'], 'internal': internal}
        if not internal:
            self.commands.append(rec)
            self.event('info', f'{vehicle}: {action} requested')
        self.pending[body['id']] = {'record': rec, 'body': body, 'packet': packet,
                                    'deadline': now + 2.5, 'next_send': now, 'attempts': 0}
        return rec

    def receive(self, body, addr, now):
        vehicle = body.get('vehicle')
        if vehicle not in self.peers or addr != self.peers[vehicle]:
            self.invalid += 1
            return
        if body.get('kind') == 'telemetry':
            v = self.vehicles[vehicle]
            if (not isinstance(body.get('boot_id'), str) or not isinstance(body.get('seq'), int)
                    or not isinstance(body.get('window'), str) or not isinstance(body.get('state'), dict)):
                self.invalid += 1
                return
            if body['boot_id'] != v['boot_id']:
                # New boots never inherit motion or outstanding command confirmation.
                retired = v.setdefault('retired_boots', deque(maxlen=32))
                if body['boot_id'] in retired:
                    return
                if v['boot_id']:
                    retired.append(v['boot_id'])
                for ident, p in list(self.pending.items()):
                    if p['record']['vehicle'] == vehicle:
                        p['record'].update(status='timeout', reason='Vehicle restarted; outcome unconfirmed')
                        del self.pending[ident]
                v.update(boot_id=body['boot_id'], seq=-1, synced=False)
                self.event('warning', f'{vehicle}: new boot observed; reconciling stopped session')
            if body['seq'] <= v['seq']:
                return
            v.update(seq=body['seq'], window=body['window'], state=body['state'], received=now)
            if not v['synced'] and not any(p['record']['vehicle'] == vehicle and p['body']['action'] == 'SYNC' for p in self.pending.values()):
                try:
                    self.command(vehicle, 'SYNC', internal=True)
                except ValueError as exc:
                    self.event('warning', f'{vehicle}: reconciliation deferred: {exc}')
        elif body.get('kind') == 'ack':
            if body.get('session') != self.session or body.get('boot_id') != self.vehicles[vehicle]['boot_id']:
                return
            ident = body.get('id')
            p = self.pending.get(ident)
            rec = p['record'] if p else next((r for r in reversed(self.commands) if r['id'] == ident and r['vehicle'] == vehicle), None)
            status = body.get('status')
            if rec is None or status not in ('accepted', 'completed', 'rejected'):
                return
            if rec['vehicle'] != vehicle or rec['boot_id'] != body['boot_id']:
                self.invalid += 1
                return
            if rec['status'] in ('completed', 'rejected'):
                return
            rec.update(status=status, reason=str(body.get('reason', ''))[:300])
            if isinstance(body.get('state'), dict):
                rec['ack_state'] = body['state']
            if status == 'accepted' and p:
                # Accepted is not completed: no inference from telemetry or elapsed time.
                p['deadline'] = min(p.get('completion_limit', now + 120), now + 120)
                p['completion_limit'] = p['deadline']
            if status in ('completed', 'rejected'):
                self.pending.pop(ident, None)
                if rec['action'] == 'SYNC' and status == 'completed':
                    self.vehicles[vehicle]['synced'] = True
                if not rec['internal']:
                    self.event('info' if status == 'completed' else 'warning', f'{vehicle}: {rec["action"]} {status}: {rec["reason"]}')

    def transfer(self, package):
        from .packages import validate_package
        validate_package(package)
        raw = json.dumps(package, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(raw) > 65536:
            raise ValueError('Package exceeds 64 KiB')
        if not self.connected('rover') or not self.vehicles['rover']['synced']:
            raise ValueError('Rover is not connected and reconciled')
        if self.vehicles['rover']['state'].get('moving'):
            raise ValueError('Stop rover before uploading a package')
        if sum(t['status'] in ('queued', 'uploading') for t in self.transfers) >= 4:
            raise ValueError('Transfer queue full')
        chunks = [raw[i:i + 1024] for i in range(0, len(raw), 1024)]
        ident = package['package_id']
        stages = [('PACKAGE_BEGIN', {'package_id': ident, 'version': package['version'],
                   'size': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'chunks': len(chunks)})]
        stages.extend(('PACKAGE_CHUNK', {'package_id': ident, 'index': i,
                      'data': base64.b64encode(chunk).decode()}) for i, chunk in enumerate(chunks))
        stages.append(('PACKAGE_COMMIT', {'package_id': ident}))
        t = {'id': uuid.uuid4().hex, 'package_id': ident, 'status': 'queued',
             'progress': 0, 'reason': 'Reviewed at C2; awaiting rover upload',
             '_stages': stages, '_index': 0, '_command': None}
        self.transfers.append(t)
        self.event('info', f'Package {ident} queued for transfer; activation remains separate')
        return {k: v for k, v in t.items() if not k.startswith('_')}

    def tick_transfers(self):
        # One bulk command in flight per transfer; control and STOP use separate priority.
        for t in self.transfers:
            if t['status'] not in ('queued', 'uploading'):
                continue
            rec = t['_command']
            if rec:
                if rec['status'] in ('requested', 'accepted'):
                    continue
                if rec['status'] != 'completed':
                    t.update(status='failed', reason='Upload unconfirmed/rejected: ' + rec['reason'])
                    t['_stages'] = []
                    continue
                if t['_index'] == 0:
                    received = rec.get('ack_state', {}).get('transfer', {}).get('received', [])
                    if isinstance(received, list):
                        t['_stages'] = [t['_stages'][0]] + [s for s in t['_stages'][1:] if s[0] != 'PACKAGE_CHUNK' or s[1]['index'] not in received]
                t['_index'] += 1
                t['progress'] = round(t['_index'] / len(t['_stages']), 3)
            if t['_index'] >= len(t['_stages']):
                t.update(status='accepted', progress=1, reason='Rover validated integrity and schema. Explicit activation required.')
                t['_stages'] = []
                t['_command'] = None
                self.event('info', f'Package {t["package_id"]} accepted by rover')
                continue
            action, args = t['_stages'][t['_index']]
            try:
                t['_command'] = self.command('rover', action, args, internal=True)
                t['status'] = 'uploading'
            except ValueError as exc:
                t.update(status='failed', reason=str(exc))
                t['_stages'] = []

    def step(self):
        now = time.monotonic()
        for _ in range(64):
            try:
                packet, addr = self.sock.recvfrom(9000)
            except BlockingIOError:
                break
            try:
                body = decode_message(packet, self.key)
                if not isinstance(body, dict):
                    raise ValueError('Invalid message')
            except (ValueError, TypeError, KeyError):
                self.invalid += 1
                continue
            kind = body.get('kind')
            self.link.schedule(('incoming', body, addr), now=now, priority=1 if kind == 'ack' else 2, kind=kind, incoming=True)
        for ident, p in list(self.pending.items()):
            rec = p['record']
            if now >= p['deadline']:
                rec.update(status='timeout', reason='Acknowledgement/completion not confirmed; inspect fresh telemetry before retrying')
                del self.pending[ident]
                if not rec['internal']:
                    self.event('warning', f'{rec["vehicle"]}: {rec["action"]} timed out; outcome unconfirmed')
                continue
            # Re-send an accepted command only to query its deduplicated result.
            # The receiver returns its cache before testing the expired window;
            # an evicted command cannot execute again with that old window.
            limit = 124 if rec['status'] == 'accepted' else 4
            if now >= p['next_send'] and p['attempts'] < limit:
                action = p['body']['action']
                priority = 0 if action == 'STOP' else 3 if action.startswith('PACKAGE_') else 1
                packet = p['packet']
                if priority == 3 and self.link.config['corrupt_bulk']:
                    packet = packet[:-1] + bytes([packet[-1] ^ 1])
                    self.link.metrics['corrupted'] += 1
                self.link.schedule(('outgoing', packet, self.peers[rec['vehicle']]), now=now, priority=priority, kind='command')
                p['attempts'] += 1
                p['next_send'] = now + (1.0 if rec['status'] == 'accepted' else .3)
        for direction, content, addr in self.link.drain(now):
            if direction == 'outgoing':
                self.sock.sendto(content, addr)
            else:
                self.receive(content, addr, now)
        if now - self.last_drone_forward >= .4 and self.connected('drone', now) and self.vehicles['rover']['synced']:
            self.last_drone_forward = now
            drone = self.vehicles['drone']
            s = drone['state']
            try:
                self.command('rover', 'DRONE_STATE', {'boot_id': drone['boot_id'], 'seq': drone['seq'],
                             'flight_state': s.get('flight_state'), 'at_designated_pad': s.get('at_designated_pad', False),
                             'flight_locked': s.get('flight_locked', False)}, internal=True)
            except ValueError:
                pass
        if now - self.last_rover_forward >= .4 and self.connected('rover', now) and self.vehicles['drone']['synced']:
            self.last_rover_forward = now
            rover = self.vehicles['rover']
            s = rover['state']
            try:
                self.command('drone', 'ROVER_STATE', {'boot_id': rover['boot_id'], 'seq': rover['seq'],
                             'mission': s.get('mission'), 'mode': s.get('mode'), 'moving': s.get('moving', False)}, internal=True)
            except ValueError:
                pass
        self.tick_transfers()

    def loop(self):
        while self.running:
            with self.lock:
                self.step()
            time.sleep(.01)

    def snapshot(self):
        now = time.monotonic()
        return {'simulation': True, 'session': self.session, 'csrf_token': self.csrf,
                'vehicles': {name: {'connected': self.connected(name, now),
                             'age_s': round(now - v['received'], 3) if v['received'] else None,
                             'boot_id': v['boot_id'], 'synced': v['synced'], 'state': v['state']} for name, v in self.vehicles.items()},
                'commands': [{k: v for k, v in r.items() if k not in ('internal', 'ack_state')} for r in self.commands],
                'events': list(self.events), 'transfers': [{k: v for k, v in t.items() if not k.startswith('_')} for t in self.transfers],
                'faults': self.link.config.copy(), 'metrics': self.link.snapshot() | {'invalid_packets': self.invalid, 'pending_commands': len(self.pending)}}


def trusted_hosts(port):
    hosts = {f'127.0.0.1:{port}', f'localhost:{port}'}
    if port in (80, 443):
        hosts |= {'127.0.0.1', 'localhost'}
    name, domain = os.getenv('CODESPACE_NAME', ''), os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', '')
    if name and domain and re.fullmatch(r'[a-zA-Z0-9-]+', name) and re.fullmatch(r'[a-zA-Z0-9.-]+', domain):
        host = f'{name}-{port}.{domain}'.lower()
        hosts |= {host, host + ':443'}
    return hosts


class BoundedServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 16
    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(16)
        super().__init__(*args, **kwargs)
    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, address)
        except Exception:
            self.slots.release()
            raise
    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()


def make_handler(c2, port):
    allowed = trusted_hosts(port)
    class Handler(BaseHTTPRequestHandler):
        server_version = 'Comms2027'
        def setup(self):
            super().setup()
            self.connection.settimeout(3)
        def log_message(self, *_):
            pass
        def respond(self, status, value, content_type='application/json'):
            raw = json.dumps(value, allow_nan=False).encode() if content_type == 'application/json' else value
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def valid_host_origin(self):
            host = self.headers.get('Host', '').lower()
            if host not in allowed or len(self.headers.get_all('Host', [])) != 1:
                self.respond(403, {'error': 'Untrusted Host'})
                return False
            origin = self.headers.get('Origin')
            if origin:
                parsed = urlsplit(origin)
                if parsed.scheme not in ('http', 'https') or parsed.netloc.lower() != host or parsed.path or parsed.query or parsed.fragment:
                    self.respond(403, {'error': 'Cross-origin requests are denied'})
                    return False
            return True
        def do_GET(self):
            if not self.valid_host_origin():
                return
            if self.path == '/api/state':
                with c2.lock:
                    result = c2.snapshot()
                return self.respond(200, result)
            assets = {'/': ('index.html', 'text/html; charset=utf-8'), '/app.js': ('app.js', 'text/javascript; charset=utf-8'), '/styles.css': ('styles.css', 'text/css; charset=utf-8')}
            if self.path in assets:
                name, mime = assets[self.path]
                path = ROOT / 'web' / name
                if path.is_file():
                    return self.respond(200, path.read_bytes(), mime)
            self.respond(404, {'error': 'Not found'})
        def do_POST(self):
            if not self.valid_host_origin():
                return
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token', ''), c2.csrf):
                return self.respond(403, {'error': 'Missing or invalid CSRF token'})
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                return self.respond(415, {'error': 'application/json required'})
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if not 0 < length <= 98304 or self.headers.get('Transfer-Encoding'):
                    return self.respond(413, {'error': 'Body must be 1..98304 bytes with Content-Length'})
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise ValueError('Incomplete body')
                data = json.loads(raw, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
                if not isinstance(data, dict):
                    raise ValueError('JSON object required')
                with c2.lock:
                    if self.path == '/api/command':
                        result = c2.command(data.get('vehicle'), data.get('action'), data.get('args', {})).copy()
                    elif self.path == '/api/transfer':
                        result = c2.transfer(data.get('package'))
                    elif self.path == '/api/faults':
                        c2.link.configure(data)
                        result = c2.link.config.copy()
                        c2.event('warning', 'Simulation network fault profile changed')
                    else:
                        return self.respond(404, {'error': 'Not found'})
                self.respond(202, result)
            except (ValueError, TypeError, KeyError, OverflowError) as exc:
                self.respond(400, {'error': str(exc)[:250]})
    return Handler


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port', type=int, default=8080)
    p.add_argument('--host', default='127.0.0.1', choices=['127.0.0.1'])
    p.add_argument('--udp-port', type=int, default=12050)
    p.add_argument('--rover-port', type=int, default=12051)
    p.add_argument('--drone-port', type=int, default=12052)
    p.add_argument('--key-file', required=True)
    args = p.parse_args()
    key = Path(args.key_file).read_bytes()
    if len(key) != 32:
        p.error('key file must contain 32 random bytes')
    c2 = C2(key, args.udp_port, args.rover_port, args.drone_port)
    server = BoundedServer((args.host, args.port), make_handler(c2, args.port))
    thread = threading.Thread(target=c2.loop, daemon=True)
    thread.start()
    print(f'SIMULATION dashboard port {args.port}; command traffic restricted to loopback', flush=True)
    try:
        server.serve_forever(poll_interval=.2)
    finally:
        c2.running = False
        server.server_close()
        thread.join(timeout=2)
        c2.sock.close()


if __name__ == '__main__':
    main()
