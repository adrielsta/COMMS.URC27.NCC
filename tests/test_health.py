"""Electrical telemetry, independent sample freshness, and alarm lifecycles."""
import copy
import json
import threading
import time
import unittest
import urllib.error
import urllib.request

from comms.c2 import BoundedServer, C2, make_handler
from comms.health import BY_ID, COMPONENTS, HEALTH_TTL, HealthMonitor, SimulatedHealth, catalog
from comms.protocol import MAX_BODY_BYTES, ProtocolError, canonical_json, decode_message, encode_message
from comms.vehicle import Vehicle, WINDOW_TTL


class HealthModelTests(unittest.TestCase):
    def test_power_loss_cascades_only_through_electrical_dependencies(self):
        model = SimulatedHealth()
        model.inject('pdu', 'power_loss')
        values = model.sample(10)['components']
        self.assertEqual(values['battery']['status'], 'nominal')
        self.assertTrue(values['battery']['powered'])
        self.assertEqual(values['pdu']['fault'], 'power_loss')
        for ident in BY_ID.keys() - {'battery', 'pdu'}:
            self.assertEqual(values[ident]['fault'], 'upstream_loss')
            self.assertFalse(values[ident]['powered'])
            self.assertEqual((values[ident]['voltage_v'], values[ident]['current_a']), (0, 0))
        model.inject('pdu', 'clear')
        model.inject('drive_fl', 'power_loss')
        values = model.sample(10)['components']
        self.assertEqual(values['drive_fl']['status'], 'critical')
        self.assertEqual(values['drive_fr']['status'], 'nominal')
        model.inject('battery', 'power_loss')
        self.assertTrue(all(not item['powered'] for item in model.sample(10)['components'].values()))

    def test_sensor_loss_does_not_invent_loss_of_supply_or_healthy_values(self):
        model = SimulatedHealth()
        baseline = model.sample(10)
        model.inject('pdu', 'sensor_loss')
        health = model.sample(10)
        self.assertEqual(health['components']['pdu']['status'], 'unknown')
        for key in ('voltage_v', 'current_a', 'temperature_c', 'powered'):
            self.assertIsNone(health['components']['pdu'][key])
        for ident in BY_ID.keys() - {'pdu'}:
            self.assertEqual(health['components'][ident], baseline['components'][ident])

    def test_bus_current_conserves_load_power_across_voltage_rails(self):
        model = SimulatedHealth()
        for moving in (False, True):
            with self.subTest(moving=moving):
                values = model.sample(10, moving)['components']
                for bus in ('pdu', 'battery'):
                    expected_watts = sum(values[item['id']]['voltage_v'] * values[item['id']]['current_a']
                                         for item in COMPONENTS if bus in item['dependencies'])
                    reported = values[bus]['voltage_v'] * (values[bus]['current_a'] - BY_ID[bus]['idle_current_a'])
                    self.assertAlmostEqual(reported, expected_watts, delta=.13)
        self.assertGreater(model.sample(10, True)['components']['battery']['current_a'],
                           model.sample(10, False)['components']['battery']['current_a'])

    def test_overheated_buses_still_report_the_power_consumed_by_their_loads(self):
        for heated in ('pdu', 'battery'):
            with self.subTest(heated=heated):
                model = SimulatedHealth()
                baseline = model.sample(10, moving=True)['components']
                model.inject(heated, 'overtemp')
                values = model.sample(10, moving=True)['components']
                self.assertEqual(values[heated]['temperature_c'], 86)
                self.assertEqual(values[heated]['fault'], 'overtemp')
                self.assertTrue(all(value['powered'] for value in values.values()))
                for bus in ('pdu', 'battery'):
                    self.assertEqual(values[bus]['current_a'], baseline[bus]['current_a'])
                    load_watts = sum(values[item['id']]['voltage_v'] * values[item['id']]['current_a']
                                     for item in COMPONENTS if bus in item['dependencies'])
                    input_watts = values[bus]['voltage_v'] * (values[bus]['current_a'] - BY_ID[bus]['idle_current_a'])
                    self.assertAlmostEqual(input_watts, load_watts, delta=.13)

    def test_fault_limits_and_bad_injections(self):
        model = SimulatedHealth()
        for fault, metric in (('overtemp', 'temperature_c'), ('overcurrent', 'current_a')):
            model.inject('drive_fl', fault)
            value = model.sample(10)['components']['drive_fl']
            self.assertEqual(value['status'], 'critical')
            self.assertGreater(value[metric], BY_ID['drive_fl']['limits'][metric]['critical'])
        before = model.faults.copy()
        for component, fault in (('absent', 'power_loss'), ('pdu', 'invented'), ([], 'clear'), ('battery', {})):
            with self.subTest(component=component, fault=fault), self.assertRaises(ValueError):
                model.inject(component, fault)
        self.assertEqual(before, model.faults)
        model.inject('drive_fl', 'clear')
        self.assertEqual(model.sample(10)['overall'], 'nominal')


class HealthMonitorTests(unittest.TestCase):
    def setUp(self):
        self.model = SimulatedHealth()
        self.monitor = HealthMonitor()

    def observe(self, now, boot='one'):
        value = self.model.sample(now)
        self.monitor.observe(boot, value, now, wall=1000 + now)
        return value

    def test_acknowledged_fault_stays_active_until_confirmed_recovery(self):
        self.model.inject('drive_fl', 'overtemp')
        self.observe(10)
        _, status = self.monitor.snapshot(10, wall=1010)
        alarm = next(a for a in status['alarms'] if a['component'] == 'drive_fl')
        self.monitor.acknowledge(alarm['id'], wall=1010.1)
        health, status = self.monitor.snapshot(10.1, wall=1010.1)
        self.assertEqual(health['components']['drive_fl']['status'], 'critical')
        self.assertEqual(status['active_count'], 1)
        self.assertEqual(status['unacknowledged_count'], 0)
        self.assertTrue(status['alarms'][0]['active'])
        self.model.inject('drive_fl', 'sensor_loss')
        self.observe(10.2)
        _, status = self.monitor.snapshot(10.2, wall=1010.2)
        original = next(a for a in status['alarms'] if a['id'] == alarm['id'])
        self.assertTrue(original['active'])
        self.assertFalse(original['confirmed'])
        self.model.inject('drive_fl', 'clear')
        self.observe(10.3)
        _, status = self.monitor.snapshot(10.3, wall=1010.3)
        self.assertEqual(status['active_count'], 0)
        self.assertTrue(all(a['resolved_at'] == 1010.3 for a in status['alarms']))
        self.model.inject('drive_fl', 'overtemp')
        self.observe(10.4)
        _, status = self.monitor.snapshot(10.4, wall=1010.4)
        new_alarm = next(a for a in status['alarms'] if a['active'])
        self.assertNotEqual(new_alarm['id'], alarm['id'])
        self.assertFalse(new_alarm['acknowledged'])

    def test_repeated_samples_do_not_freshen_and_stale_does_not_resolve(self):
        self.model.inject('pdu', 'power_loss')
        sample = self.observe(10)
        self.monitor.observe('one', sample, 10.9, wall=1010.9)
        health, status = self.monitor.snapshot(10 + HEALTH_TTL, wall=1011)
        self.assertTrue(health['stale'])
        self.assertEqual(health['age_s'], HEALTH_TTL)
        self.assertTrue(all(v['status'] == 'stale' for v in health['components'].values()))
        alarm = next(a for a in status['alarms'] if a['component'] == 'pdu')
        self.assertTrue(alarm['active'])
        self.assertFalse(alarm['confirmed'])
        self.assertTrue(any(a['code'] == 'health_stale' and a['active'] for a in status['alarms']))
        self.observe(11.2)
        health, status = self.monitor.snapshot(11.2, wall=1011.2)
        self.assertFalse(health['stale'])
        self.assertTrue(next(a for a in status['alarms'] if a['component'] == 'pdu')['confirmed'])

    def test_missing_or_invalid_channels_never_become_nominal(self):
        self.model.inject('arm', 'overcurrent')
        self.observe(10)
        for bad in (None, 'ok', {'source': 'hardware'}, {'schema_version': True}):
            self.monitor.observe('one', bad, 10.1, wall=1010.1)
            health, status = self.monitor.snapshot(10.1, wall=1010.1)
            self.assertEqual(health['overall'], 'unknown')
            self.assertTrue(any(a['component'] == 'arm' and a['active'] and not a['confirmed'] for a in status['alarms']))
        for bad in (None, {}, {'status': 'nominal'}, {'powered': True, 'fault': None,
                    'voltage_v': 24, 'current_a': None, 'temperature_c': 30}):
            sample = self.model.sample(10.2)
            sample['components']['science'] = bad
            self.monitor.observe('one', sample, 10.2, wall=1010.2)
            health, _ = self.monitor.snapshot(10.2, wall=1010.2)
            self.assertEqual(health['components']['science']['status'], 'unknown')
            self.assertIsNone(health['components']['science']['current_a'])

    def test_thresholds_are_evaluated_even_if_sender_claims_nominal(self):
        sample = self.model.sample(10)
        sample['components']['arm'].update(status='nominal', fault=None, temperature_c=90)
        self.monitor.observe('one', sample, 10, wall=1010)
        health, alarms = self.monitor.snapshot(10, wall=1010)
        self.assertEqual(health['components']['arm']['status'], 'critical')
        self.assertEqual(alarms['alarms'][0]['code'], 'overtemp')

    def test_simultaneous_limit_alarms_resolve_only_when_their_channel_recovers(self):
        def observe_channels(now, current, temperature):
            sample = self.model.sample(now)
            sample['components']['arm'].update(current_a=current, temperature_c=temperature)
            self.monitor.observe('one', sample, now, wall=1000 + now)
            return {alarm['code']: alarm for alarm in self.monitor.snapshot(now, wall=1000 + now)[1]['alarms']
                    if alarm['component'] == 'arm'}

        alarms = observe_channels(10, 20, 30)
        current_alarm_id = alarms['overcurrent']['id']
        self.monitor.acknowledge(current_alarm_id)
        alarms = observe_channels(10.1, 20, 90)
        self.assertTrue(alarms['overcurrent']['active'])
        self.assertTrue(alarms['overcurrent']['acknowledged'])
        self.assertEqual(alarms['overcurrent']['id'], current_alarm_id)
        self.assertTrue(alarms['overtemp']['active'])
        self.assertTrue(all(alarm['severity'] == 'critical' and alarm['confirmed'] for alarm in alarms.values()))
        alarms = observe_channels(10.2, 13, 90)
        self.assertEqual(alarms['overcurrent']['severity'], 'warning')
        self.assertFalse(alarms['overcurrent']['acknowledged'])
        self.assertIsNone(alarms['overcurrent']['resolved_at'])
        self.assertEqual(alarms['overtemp']['severity'], 'critical')
        alarms = observe_channels(10.3, 20, 65)
        self.assertEqual(alarms['overcurrent']['severity'], 'critical')
        self.assertEqual(alarms['overtemp']['severity'], 'warning')
        self.model.inject('arm', 'sensor_loss')
        self.observe(10.4)
        alarms = {alarm['code']: alarm for alarm in self.monitor.snapshot(10.4)[1]['alarms'] if alarm['component'] == 'arm'}
        self.assertTrue(all(alarms[code]['active'] and not alarms[code]['confirmed'] for code in ('overtemp', 'overcurrent')))
        self.model.inject('arm', 'clear')
        alarms = observe_channels(10.5, 20, 30)
        self.assertFalse(alarms['overtemp']['active'])
        self.assertFalse(alarms['sensor_loss']['active'])
        self.assertTrue(alarms['overcurrent']['active'])
        self.assertTrue(alarms['overcurrent']['confirmed'])
        alarms = observe_channels(10.6, 1, 30)
        self.assertFalse(any(alarm['active'] for alarm in alarms.values()))

    def test_power_loss_does_not_duplicate_low_voltage_alarms(self):
        self.model.inject('battery', 'power_loss')
        self.observe(10)
        alarms = self.monitor.snapshot(10)[1]['alarms']
        self.assertEqual(len(alarms), len(COMPONENTS))
        self.assertTrue(all(alarm['code'] in ('power_loss', 'upstream_loss') for alarm in alarms))

    def test_new_boot_requires_new_samples_and_history_is_bounded(self):
        self.observe(10)
        self.monitor.observe('two', None, 10.1, wall=1010.1)
        health, status = self.monitor.snapshot(10.1, wall=1010.1)
        self.assertTrue(health['stale'])
        self.assertEqual(health['seq'], -1)
        self.assertTrue(any(event['type'] == 'boot_changed' for event in status['events']))
        self.model = SimulatedHealth()
        self.observe(10.2, boot='two')
        self.assertFalse(self.monitor.snapshot(10.2)[0]['stale'])
        for i in range(200):
            self.model.inject('pdu', 'power_loss' if i % 2 else 'clear')
            self.observe(11 + i / 10, boot='two')
        self.assertLessEqual(len(self.monitor.events), 128)
        self.assertLessEqual(len(self.monitor.alarms), 128)


class HealthTransportTests(unittest.TestCase):
    def setUp(self):
        self.now = 10.0
        self.vehicle = Vehicle('rover', clock=lambda: self.now)
        self.seq = 0
        self.key = b'h' * 32
        self.send('SYNC')

    def command(self, action, args=None):
        self.seq += 1
        return {'kind': 'command', 'vehicle': 'rover', 'boot_id': self.vehicle.boot_id,
                'session': 'health-test-session', 'id': f'health-{self.seq}', 'seq': self.seq,
                'window': self.vehicle.telemetry()['window'], 'action': action, 'args': args or {}}

    def send(self, action, args=None):
        command = decode_message(encode_message(self.command(action, args), self.key), self.key)
        return decode_message(encode_message(self.vehicle.handle_command(command), self.key), self.key)

    def test_injection_uses_authenticated_expiring_idempotent_command_path(self):
        command = self.command('SIM_HEALTH_FAULT', {'component': 'pdu', 'fault': 'power_loss'})
        encoded = encode_message(command, self.key)
        with self.assertRaises(ProtocolError):
            decode_message(encoded, b'x' * 32)
        ack = self.vehicle.handle_command(decode_message(encoded, self.key))
        self.assertEqual(ack['status'], 'completed')
        self.send('SIM_HEALTH_FAULT', {'component': 'pdu', 'fault': 'clear'})
        self.assertEqual(self.vehicle.handle_command(command), ack)
        self.assertEqual(self.vehicle.snapshot()['health']['overall'], 'nominal')
        command = self.command('SIM_HEALTH_FAULT', {'component': 'battery', 'fault': 'power_loss'})
        self.now += WINDOW_TTL + .1
        self.assertEqual(self.vehicle.handle_command(command)['status'], 'rejected')
        self.assertEqual(self.vehicle.snapshot()['health']['overall'], 'nominal')

    def test_faults_do_not_change_motion_policy_and_bad_requests_are_rejected(self):
        lease = self.send('CLAIM_CONTROL')['state']['lease_id']
        self.send('MANUAL', {'lease_id': lease, 'speed': .5})
        self.send('SIM_HEALTH_FAULT', {'component': 'battery', 'fault': 'power_loss'})
        self.assertTrue(self.vehicle.moving)
        self.assertEqual(self.vehicle.snapshot()['health']['overall'], 'critical')
        for args in ({'component': 'nope', 'fault': 'clear'}, {'component': 'pdu', 'fault': 'bad'},
                     {'component': 'pdu', 'fault': 'clear', 'extra': True}):
            self.assertEqual(self.send('SIM_HEALTH_FAULT', args)['status'], 'rejected')
        self.send('STOP')
        self.assertFalse(self.vehicle.moving)

    def test_largest_rover_state_and_ack_fit_authenticated_wire_limit(self):
        # Include every bounded legacy state collection and maximal string IDs;
        # health must not make a late route/transfer ACK unencodable.
        self.vehicle.boot_id = 'b' * 128
        self.vehicle.session = 's' * 128
        self.vehicle.lease_id = 'l' * 24
        self.vehicle.packages.validated = {
            str(i) + 'p' * 63: {'version': 2**31 - 1, 'waypoints': [None] * 128}
            for i in range(4)}
        self.vehicle.packages.active_package = next(iter(self.vehicle.packages.validated))
        self.vehicle.packages.last_transfer = {'package_id': 'p' * 64, 'received': list(range(128)), 'chunks': 128, 'status': 'validated'}
        self.vehicle.mission = 'route_finding'
        for _ in range(8):
            self.vehicle._intervention('RECOVER_ROUTE')
        self.vehicle.route_status = {'status': 'accepted', 'index': 128, 'count': 128, 'command_id': 'i' * 128}
        command = {'session': 's' * 128, 'id': 'i' * 128}
        for fault in ('power_loss', 'overtemp', 'overcurrent', 'sensor_loss', 'clear'):
            for ident in BY_ID:
                self.vehicle.health.inject(ident, fault)
            for packet in (self.vehicle.telemetry(), self.vehicle._ack(command, 'rejected', 'r' * 512)):
                with self.subTest(fault=fault, kind=packet['kind']):
                    self.assertLessEqual(len(canonical_json(packet)), MAX_BODY_BYTES)
                    self.assertEqual(decode_message(encode_message(packet, self.key), self.key), packet)

    def test_c2_uses_telemetry_not_ack_snapshot_for_health_confirmation(self):
        c2 = C2(self.key, udp_port=0)
        self.addCleanup(c2.sock.close)
        now = time.monotonic()
        c2.receive(self.vehicle.telemetry(), c2.peers['rover'], now)
        c2.vehicles['rover']['synced'] = True
        rec = c2.command('rover', 'SIM_HEALTH_FAULT', {'component': 'pdu', 'fault': 'power_loss'})
        self.assertEqual(rec['status'], 'requested')
        self.assertEqual(c2.snapshot()['vehicles']['rover']['state']['health']['overall'], 'nominal')
        pending = c2.pending[rec['id']]['body']
        # The vehicle must synchronize with the real C2 session before injection.
        sync = self.command('SYNC')
        sync['session'] = c2.session
        self.vehicle.handle_command(sync)
        pending['seq'] = self.seq + 1
        ack = self.vehicle.handle_command(pending)
        self.assertEqual(ack['status'], 'completed')
        c2.receive(ack, c2.peers['rover'], now + .01)
        self.assertEqual(rec['status'], 'completed')
        self.assertEqual(c2.snapshot()['vehicles']['rover']['state']['health']['overall'], 'nominal')
        c2.receive(self.vehicle.telemetry(), c2.peers['rover'], now + .02)
        self.assertEqual(c2.snapshot()['vehicles']['rover']['state']['health']['overall'], 'critical')


class HealthHttpTests(unittest.TestCase):
    def setUp(self):
        self.c2 = C2(b'h' * 32, udp_port=0)
        self.server = BoundedServer(('127.0.0.1', 0), make_handler(self.c2, 1))
        self.server.RequestHandlerClass = make_handler(self.c2, self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.c2.sock.close()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.url + path, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def test_catalog_and_csrf_protected_ack_cannot_clear_fault(self):
        self.assertEqual(self.request('/api/health/catalog'), catalog())
        model = SimulatedHealth()
        model.inject('radio', 'power_loss')
        self.c2.health_monitor.observe('boot', model.sample(10), time.monotonic())
        alarm = self.c2.snapshot()['health_monitor']['alarms'][0]
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/health/ack', {'alarm_id': alarm['id']})
        self.assertEqual(error.exception.code, 403)
        headers = {'X-CSRF-Token': self.c2.csrf, 'Content-Type': 'application/json'}
        result = self.request('/api/health/ack', {'alarm_id': alarm['id']}, headers)
        self.assertTrue(result['acknowledged'])
        self.assertTrue(result['active'])
        self.assertEqual(self.c2.snapshot()['vehicles']['rover']['state']['health']['components']['radio']['fault'], 'power_loss')
        for body in ({'alarm_id': 'absent'}, {'alarm_id': alarm['id'], 'clear': True}):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request('/api/health/ack', body, headers)
            self.assertEqual(error.exception.code, 400)


if __name__ == '__main__':
    unittest.main()
