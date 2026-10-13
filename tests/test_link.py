import unittest
from comms.link import FaultLink


class LinkTests(unittest.TestCase):
    def test_control_survives_bulk_capacity_and_is_delivered_first(self):
        link = FaultLink()
        for n in range(1000):
            link.schedule(('bulk', n), now=0, priority=3, kind='command')
        link.schedule('STOP', now=0, priority=0, kind='command')
        self.assertEqual(link.snapshot()['queue_depth'], 65)
        self.assertEqual(link.drain(0, limit=1), ['STOP'])
        self.assertEqual(link.metrics['overflow'], 936)

    def test_disconnect_drops_queued_as_well_as_new_frames(self):
        link = FaultLink()
        link.configure({'delay_ms': 200})
        link.schedule('old', now=0, priority=1, kind='command')
        link.configure({'disconnect': True})
        link.schedule('new', now=1, priority=1, kind='command')
        self.assertEqual(link.drain(2), [])
        self.assertEqual(link.metrics['dropped'], 2)

    def test_loss_delay_jitter_duplication_and_reordering(self):
        link = FaultLink(seed=7)
        link.configure({'loss': .3, 'delay_ms': 150, 'jitter_ms': 100,
                        'duplicate': 1, 'reorder': 1})
        for n in range(40):
            link.schedule(n, now=0, priority=1, kind='command')
        self.assertEqual(link.drain(.049), [])
        delivered = link.drain(2, limit=128)
        self.assertGreater(link.metrics['dropped'], 0)
        self.assertGreater(len(delivered), len(set(delivered)))
        self.assertNotEqual(delivered, sorted(delivered))
        self.assertLessEqual(link.snapshot()['queue_depth'], 128)

    def test_telemetry_only_fault_keeps_ack_path(self):
        link = FaultLink()
        link.configure({'telemetry_only': True})
        link.schedule('telemetry', now=0, priority=2, kind='telemetry', incoming=True)
        link.schedule('ack', now=0, priority=1, kind='ack', incoming=True)
        self.assertEqual(link.drain(0), ['ack'])

    def test_invalid_fault_config_preserves_previous_profile(self):
        link = FaultLink()
        for invalid in ({'loss': float('nan')}, {'loss': 1.2}, {'delay_ms': 4000},
                        {'disconnect': 1}, {'unknown': True}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                link.configure(invalid)
        self.assertEqual(link.config['loss'], 0)


if __name__ == '__main__':
    unittest.main()
