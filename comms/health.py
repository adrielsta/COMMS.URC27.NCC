"""Illustrative rover electrical telemetry and receipt-local health monitoring.

The six-wheel catalog is a configurable development template, not the team's
as-built wiring or component ratings. Fault injection changes this telemetry
model only; it does not implement motor protection or a physical power switch.
"""
from collections import OrderedDict, deque
import copy
import math
import time
import uuid

MODEL_ID = 'ncc-six-wheel-v1'
HEALTH_TTL = 1.0
FAULTS = ('power_loss', 'overtemp', 'overcurrent', 'sensor_loss', 'clear')
METRICS = ('voltage_v', 'current_a', 'temperature_c')


def _component(ident, name, group, parent, voltage, current, trip):
    return {'id': ident, 'name': name, 'group': group,
            'dependencies': [] if parent is None else [parent],
            'nominal_voltage_v': voltage, 'idle_current_a': current,
            'limits': {'voltage_v': {'min': round(voltage * .85, 2), 'max': round(voltage * 1.15, 2)},
                       'current_a': {'warning': round(trip * .8, 2), 'critical': trip},
                       'temperature_c': {'warning': 60, 'critical': 75}}}


# Parents precede consumers: this is also the order used for power propagation.
COMPONENTS = (
    _component('battery', 'Main battery', 'Power', None, 24, .0, 60),
    _component('pdu', 'Power distribution', 'Power', 'battery', 24, .15, 55),
    *(_component(f'drive_{side}{position}', f'{label} {wheel} drive', 'Mobility', 'pdu', 24, .28, 12)
      for side, label in (('f', 'Front'), ('m', 'Middle'), ('r', 'Rear'))
      for position, wheel in (('l', 'left'), ('r', 'right'))),
    _component('compute', 'Onboard computer', 'Avionics', 'pdu', 12, 2.1, 6),
    _component('radio', 'Telemetry radio', 'Communications', 'pdu', 12, .65, 3),
    _component('gnss', 'GNSS receiver', 'Navigation', 'pdu', 5, .18, 1),
    _component('camera', 'Navigation camera', 'Navigation', 'pdu', 5, .32, 2),
    _component('arm', 'Manipulator', 'Payload', 'pdu', 24, .42, 15),
    _component('science', 'Science payload', 'Payload', 'pdu', 12, .55, 5),
)
BY_ID = {component['id']: component for component in COMPONENTS}


def catalog():
    return {'schema_version': 1, 'model_id': MODEL_ID, 'source': 'simulation',
            'illustrative': True, 'description': 'Six-wheel development template; replace topology and limits with measured rover configuration.',
            'units': {'voltage_v': 'V', 'current_a': 'A', 'temperature_c': '\u00b0C'},
            'freshness_limit_s': HEALTH_TTL, 'faults': list(FAULTS),
            'components': copy.deepcopy(list(COMPONENTS))}


def _unknown(fault='sensor_loss'):
    return {'status': 'unknown', 'powered': None, 'voltage_v': None,
            'current_a': None, 'temperature_c': None, 'fault': fault}


def _overall(components):
    states = {item['status'] for item in components.values()}
    return next((status for status in ('stale', 'critical', 'unknown', 'warning') if status in states), 'nominal')


def _classify(component, value):
    """Never turn incomplete or invalid measurements into a healthy channel."""
    if not isinstance(value, dict):
        return _unknown()
    result = {key: value.get(key) for key in (*METRICS, 'powered', 'fault')}
    if (type(result['powered']) is not bool or
            any(type(result[key]) not in (int, float) or not math.isfinite(result[key])
                or abs(result[key]) > 10000 for key in METRICS) or
            result['voltage_v'] < 0 or result['current_a'] < 0 or result['temperature_c'] < -273.15):
        return _unknown()
    if result['fault'] not in (None, *FAULTS[:-1], 'upstream_loss', 'voltage_range'):
        return _unknown()
    limits = component['limits']
    if result['fault'] == 'sensor_loss':
        return _unknown()
    if not result['powered'] or result['fault'] in ('power_loss', 'upstream_loss'):
        result['status'] = 'critical'
        result['fault'] = result['fault'] or 'power_loss'
    elif result['temperature_c'] >= limits['temperature_c']['critical']:
        result.update(status='critical', fault='overtemp')
    elif result['current_a'] >= limits['current_a']['critical']:
        result.update(status='critical', fault='overcurrent')
    elif not limits['voltage_v']['min'] <= result['voltage_v'] <= limits['voltage_v']['max']:
        result.update(status='warning', fault='voltage_range')
    elif result['temperature_c'] >= limits['temperature_c']['warning']:
        result.update(status='warning', fault='overtemp')
    elif result['current_a'] >= limits['current_a']['warning']:
        result.update(status='warning', fault='overcurrent')
    elif result['fault'] in ('overtemp', 'overcurrent'):
        # A sender's asserted fault is retained, even if the sample is normal.
        result['status'] = 'warning'
    else:
        result.update(status='nominal', fault=None)
    return result


def _alarm_conditions(component, value):
    """Evaluate each channel independently of the displayed dominant fault."""
    if value['status'] == 'unknown':
        return {'sensor_loss': 'warning'}
    conditions = {}
    power_lost = not value['powered'] or value['fault'] in ('power_loss', 'upstream_loss')
    if power_lost:
        conditions[value['fault'] if value['fault'] in ('power_loss', 'upstream_loss') else 'power_loss'] = 'critical'
    limits = component['limits']
    for metric, code in (('temperature_c', 'overtemp'), ('current_a', 'overcurrent')):
        if value[metric] >= limits[metric]['critical']:
            conditions[code] = 'critical'
        elif value[metric] >= limits[metric]['warning'] or value['fault'] == code:
            conditions[code] = 'warning'
    # A zero-voltage power outage is already annunciated as supply loss.
    if not power_lost and not limits['voltage_v']['min'] <= value['voltage_v'] <= limits['voltage_v']['max']:
        conditions['voltage_range'] = 'warning'
    return conditions


class SimulatedHealth:
    def __init__(self):
        self.faults = {}
        self.seq = 0

    def inject(self, component, fault):
        if not isinstance(component, str) or component not in BY_ID:
            raise ValueError('Unknown health component')
        if not isinstance(fault, str) or fault not in FAULTS:
            raise ValueError('Unknown simulation health fault')
        if fault == 'clear':
            self.faults.pop(component, None)
        else:
            self.faults[component] = fault

    def sample(self, now, moving=False):
        self.seq += 1
        physical_power, values = {}, {}
        for index, definition in enumerate(COMPONENTS):
            ident = definition['id']
            fault = self.faults.get(ident)
            upstream = all(physical_power[parent] for parent in definition['dependencies'])
            powered = upstream and fault != 'power_loss'
            physical_power[ident] = powered
            current = definition['idle_current_a']
            if moving and ident.startswith('drive_'):
                current += 2.8
            ripple = math.sin(now * .6 + index) * .025
            value = {'powered': powered,
                     'voltage_v': round(definition['nominal_voltage_v'] + ripple, 2) if powered else 0,
                     'current_a': round(current + abs(ripple), 2) if powered else 0,
                     'temperature_c': round(30 + index * .6 + (7 if moving and ident.startswith('drive_') else 0) + ripple, 1),
                     'fault': None if fault == 'sensor_loss' else fault}
            if not powered:
                value['fault'] = 'upstream_loss' if not upstream else 'power_loss'
            elif fault == 'overtemp':
                value['temperature_c'] = 86.0
            elif fault == 'overcurrent':
                value['current_a'] = round(definition['limits']['current_a']['critical'] * 1.2, 2)
            values[ident] = _classify(definition, value)
        # Ideal conversion model: input watts equal load watts (no converter
        # losses). The independent bus sensor still reports when a load sensor
        # is disconnected. Apply sensor omissions after physical calculation.
        for ident in ('pdu', 'battery'):
            if self.faults.get(ident) in ('power_loss', 'overcurrent') or not physical_power[ident]:
                continue
            children = [entry for entry in COMPONENTS if ident in entry['dependencies']]
            readings = [values[entry['id']] for entry in children]
            values[ident]['current_a'] = round(sum(item['current_a'] * item['voltage_v'] for item in readings) / values[ident]['voltage_v'] + BY_ID[ident]['idle_current_a'], 2)
            values[ident] = _classify(BY_ID[ident], values[ident])
        for ident, fault in self.faults.items():
            if fault == 'sensor_loss':
                values[ident] = _unknown()
        return {'schema_version': 1, 'model_id': MODEL_ID, 'source': 'simulation',
                'seq': self.seq, 'components': values, 'overall': _overall(values)}


class HealthMonitor:
    """Bounded C2 annunciation; acknowledgment is separate from resolution."""
    def __init__(self):
        self.boot_id = None
        self.seq = -1
        self.received = None
        self.latest = None
        self.alarms = OrderedDict()
        self.events = deque(maxlen=128)

    def _event(self, kind, alarm, wall):
        self.events.append({'time': wall, 'type': kind, 'component': alarm['component'],
                            'code': alarm['code'], 'alarm_id': alarm['id']})

    def _raise(self, component, code, severity, wall):
        key = (component, code)
        alarm = self.alarms.get(key)
        if alarm is None or not alarm['active']:
            alarm = {'id': uuid.uuid4().hex, 'component': component, 'code': code,
                     'severity': severity, 'active': True, 'acknowledged': False,
                     'confirmed': True, 'first_seen': wall, 'last_seen': wall,
                     'resolved_at': None}
            self.alarms[key] = alarm
            self.alarms.move_to_end(key)
            self._event('raised', alarm, wall)
            while len(self.alarms) > 128:
                self.alarms.popitem(last=False)
        else:
            if alarm['severity'] != severity:
                alarm.update(severity=severity, acknowledged=False)
                self._event('severity_changed', alarm, wall)
            alarm.update(last_seen=wall, confirmed=True)
        return alarm

    def _resolve(self, alarm, wall):
        alarm.update(active=False, confirmed=True, resolved_at=wall, last_seen=wall)
        self._event('resolved', alarm, wall)

    def observe(self, boot_id, health, now, wall=None):
        wall = time.time() if wall is None else wall
        if boot_id != self.boot_id:
            if self.boot_id is not None:
                self.events.append({'time': wall, 'type': 'boot_changed', 'component': 'telemetry',
                                    'code': 'boot_changed', 'alarm_id': None})
            self.boot_id, self.seq, self.received, self.latest = boot_id, -1, None, None
        if (not isinstance(health, dict) or type(health.get('schema_version')) is not int or health['schema_version'] != 1 or
                health.get('source') != 'simulation' or health.get('model_id') != MODEL_ID or
                type(health.get('seq')) is not int or not 0 <= health['seq'] <= 2**53 or
                not isinstance(health.get('components'), dict)):
            self.latest = None
            for alarm in self.alarms.values():
                if alarm['active']:
                    alarm['confirmed'] = False
            self._raise('telemetry', 'health_unavailable', 'warning', wall)
            return
        if health['seq'] <= self.seq:
            return  # New vehicle telemetry cannot freshen a repeated health sample.
        self.seq, self.received = health['seq'], now
        values = {item['id']: _classify(item, health['components'].get(item['id'])) for item in COMPONENTS}
        conditions = {ident: _alarm_conditions(BY_ID[ident], value) for ident, value in values.items()}
        self.latest = {'schema_version': 1, 'model_id': MODEL_ID, 'source': 'simulation',
                       'seq': self.seq, 'components': values, 'overall': _overall(values)}
        for alarm in self.alarms.values():
            if not alarm['active']:
                continue
            if alarm['component'] == 'telemetry':
                self._resolve(alarm, wall)
                continue
            value = values[alarm['component']]
            if value['status'] == 'unknown':
                alarm['confirmed'] = alarm['code'] == 'sensor_loss'
            elif alarm['code'] not in conditions[alarm['component']]:
                self._resolve(alarm, wall)
        for ident, faults in conditions.items():
            for code, severity in faults.items():
                self._raise(ident, code, severity, wall)

    def acknowledge(self, alarm_id, wall=None):
        if not isinstance(alarm_id, str):
            raise ValueError('alarm_id must be a string')
        alarm = next((item for item in self.alarms.values() if item['id'] == alarm_id), None)
        if alarm is None:
            raise ValueError('Unknown health alarm')
        if not alarm['acknowledged']:
            alarm['acknowledged'] = True
            self._event('acknowledged', alarm, time.time() if wall is None else wall)
        return copy.deepcopy(alarm)

    def snapshot(self, now, wall=None):
        wall = time.time() if wall is None else wall
        age = None if self.received is None else max(0, now - self.received)
        stale = age is None or age >= HEALTH_TTL
        if stale:
            for alarm in self.alarms.values():
                if alarm['active'] and alarm['component'] != 'telemetry':
                    alarm['confirmed'] = False
            self._raise('telemetry', 'health_stale' if self.received is not None else 'health_unavailable', 'warning', wall)
        health = copy.deepcopy(self.latest) if self.latest is not None else {
            'schema_version': 1, 'model_id': MODEL_ID, 'source': 'simulation',
            'seq': self.seq, 'components': {ident: _unknown() for ident in BY_ID}, 'overall': 'unknown'}
        if stale:
            for value in health['components'].values():
                value['last_status'] = value['status']
                value['status'] = 'stale'
            health['overall'] = 'stale'
        health.update(age_s=None if age is None else round(age, 3), stale=stale)
        alarms = list(self.alarms.values())
        return health, {'active_count': sum(item['active'] for item in alarms),
                        'unacknowledged_count': sum(item['active'] and not item['acknowledged'] for item in alarms),
                        'alarms': copy.deepcopy(alarms), 'events': list(self.events)}
