import time
import unittest
from comms.c2 import C2
from comms.vehicle import LEASE_TTL, Vehicle


class C2StateTests(unittest.TestCase):
    def setUp(self):
        self.c2 = C2(b'k' * 32, udp_port=0)
        for name, vehicle in self.c2.vehicles.items():
            vehicle.update(boot_id=name + '-boot', window='window', received=time.monotonic(), synced=True,
                           state={'mission': 'delivery'})

    def tearDown(self):
        self.c2.sock.close()

    def test_stop_has_reserved_admission_and_preempts_full_queue(self):
        for _ in range(56):
            self.c2.command('rover', 'CLAIM_CONTROL')
        with self.assertRaises(ValueError):
            self.c2.command('rover', 'CLAIM_CONTROL')
        for _ in range(12):
            self.c2.command('rover', 'STOP')
        self.assertEqual(len(self.c2.pending), 64)
        self.assertEqual(self.c2.commands[-1]['action'], 'STOP')
        self.assertEqual(self.c2.commands[-1]['status'], 'requested')

    def test_new_vehicle_sync_does_not_kill_worker_with_saturated_queue(self):
        for _ in range(64):
            self.c2.command('rover', 'STOP')
        self.c2.receive({'kind': 'telemetry', 'vehicle': 'drone', 'boot_id': 'new-drone',
                         'seq': 0, 'window': 'window', 'state': {}}, self.c2.peers['drone'], time.monotonic())
        self.assertLessEqual(len(self.c2.pending), 64)
        self.assertTrue(any(p['body']['action'] == 'SYNC' and p['record']['vehicle'] == 'drone' for p in self.c2.pending.values()))

    def test_ack_must_match_command_vehicle(self):
        rec = self.c2.command('rover', 'STOP')
        ack = {'kind': 'ack', 'vehicle': 'drone', 'boot_id': 'drone-boot',
               'session': self.c2.session, 'id': rec['id'], 'status': 'completed', 'reason': 'wrong endpoint'}
        self.c2.receive(ack, self.c2.peers['drone'], time.monotonic())
        self.assertEqual(rec['status'], 'requested')
        ack.update(vehicle='rover', boot_id='rover-boot')
        self.c2.receive(ack, self.c2.peers['rover'], time.monotonic())
        self.assertEqual(rec['status'], 'completed')

    def test_out_of_order_and_retired_boot_telemetry_cannot_restore_state(self):
        def telemetry(boot, seq, mode):
            self.c2.receive({'kind': 'telemetry', 'vehicle': 'rover', 'boot_id': boot,
                             'seq': seq, 'window': 'window', 'state': {'mode': mode}},
                            self.c2.peers['rover'], time.monotonic())
        telemetry('rover-boot', 3, 'stopped')
        telemetry('rover-boot', 2, 'manual')
        self.assertEqual(self.c2.vehicles['rover']['state']['mode'], 'stopped')
        telemetry('new-rover', 0, 'stopped')
        telemetry('rover-boot', 4, 'manual')
        self.assertEqual(self.c2.vehicles['rover']['boot_id'], 'new-rover')

    def test_claim_result_uses_exact_ack_lease_while_telemetry_lags_and_still_expires(self):
        now = [time.monotonic()]
        rover = Vehicle('rover', boot_id='rover-boot', clock=lambda: now[0])
        self.c2.receive(rover.telemetry(), self.c2.peers['rover'], now[0])

        def execute(action, args=None, internal=False):
            rec = self.c2.command('rover', action, args, internal=internal)
            body = self.c2.pending[rec['id']]['body']
            ack = rover.handle_command(body)
            self.c2.receive(ack, self.c2.peers['rover'], now[0])
            return rec

        execute('SYNC', internal=True)
        previous = execute('CLAIM_CONTROL')
        self.c2.receive(rover.telemetry(), self.c2.peers['rover'], now[0])
        current = execute('CLAIM_CONTROL')
        public = self.c2.snapshot()
        record = next(item for item in public['commands'] if item['id'] == current['id'])
        self.assertEqual(record['status'], 'completed')
        self.assertEqual(record['boot_id'], rover.boot_id)
        self.assertEqual(record['result'], {'lease_id': rover.lease_id})
        self.assertNotEqual(record['result'], previous['result'])
        self.assertEqual(public['vehicles']['rover']['state']['lease_id'], previous['result']['lease_id'])
        self.assertNotIn('ack_state', record)
        self.assertEqual(execute('MANUAL', {'speed': .5, 'lease_id': record['result']['lease_id']})['status'], 'completed')
        self.assertTrue(rover.moving)

        now[0] += LEASE_TTL + .01
        self.c2.receive(rover.telemetry(), self.c2.peers['rover'], now[0])
        expired = execute('MANUAL', {'speed': .5, 'lease_id': record['result']['lease_id']})
        self.assertEqual(expired['status'], 'rejected')
        self.assertIn('receiver-local manual lease', expired['reason'])
        self.assertFalse(rover.moving)

    def test_only_matching_completed_claims_publish_a_valid_lease_result(self):
        lease = 'a' * 24
        claim = self.c2.command('rover', 'CLAIM_CONTROL')
        ack = {'kind': 'ack', 'vehicle': 'rover', 'boot_id': 'rover-boot',
               'session': self.c2.session, 'id': claim['id'], 'status': 'completed',
               'reason': 'lease granted', 'state': {'lease_id': lease, 'health': {'private': 'snapshot'}}}
        self.assertNotIn('result', claim)
        for mismatch in ({'id': 'different-claim'}, {'boot_id': 'old-boot'}, {'session': 'old-session'}):
            self.c2.receive(ack | mismatch, self.c2.peers['rover'], time.monotonic())
            self.assertEqual(claim['status'], 'requested')
            self.assertNotIn('result', claim)
        self.c2.receive(ack | {'status': 'accepted'}, self.c2.peers['rover'], time.monotonic())
        self.assertNotIn('result', claim)
        self.c2.receive(ack, self.c2.peers['rover'], time.monotonic())
        self.assertEqual(claim['result'], {'lease_id': lease})

        for action, status, state in (
                ('STOP', 'completed', {'lease_id': lease}),
                ('CLAIM_CONTROL', 'rejected', {'lease_id': lease}),
                ('CLAIM_CONTROL', 'completed', {'lease_id': None}),
                ('CLAIM_CONTROL', 'completed', {'lease_id': ['a' * 24]}),
                ('CLAIM_CONTROL', 'completed', {'lease_id': 'invalid-token'})):
            with self.subTest(action=action, status=status, state=state):
                rec = self.c2.command('rover', action)
                self.c2.receive(ack | {'id': rec['id'], 'status': status, 'state': state},
                                self.c2.peers['rover'], time.monotonic())
                self.assertNotIn('result', rec)
        for record in self.c2.snapshot()['commands']:
            self.assertNotIn('ack_state', record)


if __name__ == '__main__':
    unittest.main()
