import time
import unittest
from comms.c2 import C2


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


if __name__ == '__main__':
    unittest.main()
