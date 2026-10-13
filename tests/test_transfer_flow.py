"""Real process route delivery and corrupted/interrupted transfer demonstrations."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from test_end_to_end import reserve_ports


class TransferFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='comms-transfer-')
        http, udp = reserve_ports()
        cls.url = f'http://127.0.0.1:{http}'
        cls.log = open(Path(cls.tmp.name) / 'supervisor.log', 'w')
        cls.proc = subprocess.Popen([sys.executable, '-m', 'comms.supervisor'],
                                   cwd=Path(__file__).resolve().parents[1],
                                   env=os.environ | {'COMMS_HTTP_PORT': str(http), 'COMMS_UDP_PORT': str(udp),
                                                     'COMMS_RUNTIME_DIR': cls.tmp.name, 'COMMS_HTTP_HOST': '127.0.0.1'},
                                   stdout=cls.log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            cls.wait(lambda s: all(v['connected'] and v['synced'] for v in s['vehicles'].values()), timeout=10)
        except BaseException:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        try:
            os.killpg(cls.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(cls.proc.pid, signal.SIGKILL)
            cls.proc.wait(timeout=2)
        cls.log.close()
        cls.tmp.cleanup()

    @classmethod
    def request(cls, path='/api/state', body=None):
        headers = {}
        if body is not None:
            headers = {'Content-Type': 'application/json', 'X-CSRF-Token': cls.request()['csrf_token']}
        req = urllib.request.Request(cls.url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
        with urllib.request.urlopen(req, timeout=2) as response:
            return json.load(response)

    @classmethod
    def wait(cls, check, timeout=6):
        deadline = time.monotonic() + timeout
        state = None
        while time.monotonic() < deadline:
            try:
                state = cls.request()
                if check(state):
                    return state
            except OSError:
                pass
            time.sleep(.04)
        diagnostic = None if state is None else {
            'vehicles': {k: {'connected': v['connected'], 'mode': v['state'].get('mode'),
                             'mission': v['state'].get('mission')} for k, v in state['vehicles'].items()},
            'commands': state['commands'][-6:], 'transfers': state['transfers'], 'metrics': state['metrics']}
        raise AssertionError(f'Expected state not observed; diagnostic: {diagnostic}')

    def command(self, vehicle, action, args=None, expected='completed'):
        rec = self.request('/api/command', {'vehicle': vehicle, 'action': action, 'args': args or {}})
        self.wait(lambda s: any(r['id'] == rec['id'] and r['status'] == expected for r in s['commands']))
        return rec

    def test_survey_review_upload_accept_activate_and_onboard_route(self):
        self.wait(lambda s: s['vehicles']['drone']['state'].get('rover_state_fresh', True))
        # The drone really generates the synthetic product in its own process.
        time.sleep(.5)
        self.command('drone', 'DRONE_TAKEOFF')
        self.command('drone', 'DRONE_SURVEY')
        s = self.wait(lambda s: bool(s['vehicles']['drone']['state'].get('survey_product')))
        package = s['vehicles']['drone']['state']['survey_product']
        self.assertTrue(package['synthetic'])
        transfer = self.request('/api/transfer', {'package': package})
        self.wait(lambda s: any(t['id'] == transfer['id'] and t['status'] == 'accepted' for t in s['transfers']))
        self.assertIsNone(self.request()['vehicles']['rover']['state']['active_package'])
        self.command('rover', 'ACTIVATE_PACKAGE', {'package_id': package['package_id']})
        self.command('rover', 'SET_MISSION', {'mission': 'route_finding'})
        self.command('rover', 'START_ROUTE', expected='rejected')
        self.command('drone', 'DRONE_LAND')
        self.command('drone', 'SET_MISSION', {'mission': 'route_finding'})
        self.wait(lambda s: s['vehicles']['drone']['state'].get('flight_locked', False))
        time.sleep(.5)
        started = self.command('rover', 'START_ROUTE', expected='accepted')
        self.request('/api/faults', {'disconnect': True})
        # Onboard route advances with zero C2 packets. Completion ACK is lost.
        time.sleep(1.4)
        before_reconnect = next(r for r in self.request()['commands'] if r['id'] == started['id'])
        self.assertEqual(before_reconnect['status'], 'accepted', 'Lost completion ACK must not be inferred')
        self.request('/api/faults', {})
        s = self.wait(lambda s: s['vehicles']['rover']['connected'] and s['vehicles']['rover']['state']['route_status']['status'] == 'completed')
        rover = s['vehicles']['rover']['state']
        self.assertFalse(rover['moving'])
        self.assertEqual(rover['position'], package['waypoints'][-1])
        self.wait(lambda s: any(r['id'] == started['id'] and r['status'] == 'completed' for r in s['commands']))
        self.command('rover', 'CLAIM_CONTROL', expected='rejected')
        recovery = self.command('rover', 'RECOVER_ROUTE', expected='accepted')
        self.wait(lambda s: any(r['id'] == recovery['id'] and r['status'] == 'completed' for r in s['commands']))
        self.command('rover', 'SET_MISSION', {'mission': 'delivery'})
        time.sleep(.6)
        self.command('drone', 'SET_MISSION', {'mission': 'delivery'})

    def test_transfer_corruption_times_out_then_explicit_resume_succeeds(self):
        package = {'schema_version': 1, 'package_id': 'corrupt-resume', 'version': 1,
                   'crs': 'EPSG:4326', 'units': 'degrees', 'synthetic': True,
                   'source': 'simulated-drone', 'waypoints': [{'lat': 38.418, 'lon': -110.777}] * 100}
        self.request('/api/faults', {'corrupt_bulk': True})
        t = self.request('/api/transfer', {'package': package})
        self.wait(lambda s: any(r['id'] == t['id'] and r['status'] == 'failed' for r in s['transfers']), timeout=8)
        self.assertNotEqual(self.request()['vehicles']['rover']['state']['active_package'], package['package_id'])
        self.request('/api/faults', {})
        t2 = self.request('/api/transfer', {'package': package})
        stop = self.request('/api/command', {'vehicle': 'rover', 'action': 'STOP', 'args': {}})
        self.wait(lambda s: any(r['id'] == stop['id'] and r['status'] == 'completed' for r in s['commands']), timeout=1.5)
        self.wait(lambda s: any(r['id'] == t2['id'] and r['status'] == 'accepted' for r in s['transfers']), timeout=8)
        self.assertNotEqual(self.request()['vehicles']['rover']['state']['active_package'], package['package_id'])


if __name__ == '__main__':
    unittest.main()
