"""Bounded, priority-aware simulated transport faults (never a radio model)."""
import heapq
import random

DEFAULTS = dict(loss=0.0, delay_ms=0.0, jitter_ms=0.0, duplicate=0.0,
                reorder=0.0, disconnect=False, telemetry_only=False,
                corrupt_bulk=False, ack_loss=0.0)


class FaultLink:
    def __init__(self, seed=2027):
        self.config = DEFAULTS.copy()
        self.random = random.Random(seed)
        self.queues = [[], [], [], []]
        self.counter = 0
        self.metrics = dict(queued=0, dropped=0, duplicated=0, delivered=0,
                            overflow=0, corrupted=0)

    def configure(self, changes):
        if not isinstance(changes, dict) or set(changes) - DEFAULTS.keys():
            raise ValueError('Unknown fault setting')
        new = DEFAULTS | changes
        for name in ('loss', 'duplicate', 'reorder', 'ack_loss'):
            if isinstance(new[name], bool) or not isinstance(new[name], (int, float)) or not 0 <= new[name] <= 1:
                raise ValueError(name + ' must be between 0 and 1')
        for name in ('delay_ms', 'jitter_ms'):
            if isinstance(new[name], bool) or not isinstance(new[name], (int, float)) or not 0 <= new[name] <= 3000:
                raise ValueError(name + ' must be between 0 and 3000')
        for name in ('disconnect', 'telemetry_only', 'corrupt_bulk'):
            if not isinstance(new[name], bool):
                raise ValueError(name + ' must be boolean')
        self.config = new
        # Already queued frames remain subject to new disconnection on delivery.

    def schedule(self, item, *, now, priority, kind, incoming=False):
        c = self.config
        if (c['disconnect'] or incoming and c['telemetry_only'] and kind == 'telemetry'
                or incoming and kind == 'ack' and self.random.random() < c['ack_loss']
                or self.random.random() < c['loss']):
            self.metrics['dropped'] += 1
            return
        copies = 2 if self.random.random() < c['duplicate'] else 1
        self.metrics['duplicated'] += copies - 1
        for _ in range(copies):
            q = self.queues[priority]
            # Bulk has its own cap and cannot consume control queue capacity.
            if len(q) >= (64 if priority == 3 else 128):
                self.metrics['overflow'] += 1
                continue
            delay = max(0, c['delay_ms'] + self.random.uniform(-c['jitter_ms'], c['jitter_ms'])) / 1000
            if self.random.random() < c['reorder']:
                delay += self.random.uniform(.1, .6)
            self.counter += 1
            heapq.heappush(q, (now + delay, self.counter, item, kind, incoming))
            self.metrics['queued'] += 1

    def drain(self, now, limit=32):
        ready = []
        for q in self.queues:
            while q and q[0][0] <= now and len(ready) < limit:
                _, _, item, kind, incoming = heapq.heappop(q)
                if self.config['disconnect'] or incoming and self.config['telemetry_only'] and kind == 'telemetry':
                    self.metrics['dropped'] += 1
                    continue
                ready.append(item)
                self.metrics['delivered'] += 1
        return ready

    def snapshot(self):
        return self.metrics | {'queue_depth': sum(map(len, self.queues)),
                               'queues_by_priority': list(map(len, self.queues))}
