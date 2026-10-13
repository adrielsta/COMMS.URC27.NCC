"""Start three independent simulation processes; no physical adapters."""
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    runtime = Path(os.getenv('COMMS_RUNTIME_DIR', str(ROOT / '.runtime')))
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    key = runtime / 'transport.key'
    if not key.exists():
        try:
            fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as f:
                f.write(secrets.token_bytes(32))
        except FileExistsError:
            pass
    if len(key.read_bytes()) != 32:
        raise SystemExit('Invalid simulation key file; expected 32 random bytes')
    port = int(os.getenv('COMMS_HTTP_PORT', '8080'))
    udp = int(os.getenv('COMMS_UDP_PORT', '12050'))
    host = os.getenv('COMMS_HTTP_HOST', '127.0.0.1')
    commands = {
        'c2': [sys.executable, '-m', 'comms.c2', '--port', str(port), '--host', host,
               '--udp-port', str(udp), '--rover-port', str(udp + 1), '--drone-port', str(udp + 2), '--key-file', str(key)],
        'rover': [sys.executable, '-m', 'comms.vehicle', '--kind', 'rover', '--port', str(udp + 1), '--c2-port', str(udp), '--key-file', str(key)],
        'drone': [sys.executable, '-m', 'comms.vehicle', '--kind', 'drone', '--port', str(udp + 2), '--c2-port', str(udp), '--key-file', str(key)],
    }
    processes, logs, restarts = {}, {}, {k: [] for k in commands}
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def start(name):
        if name not in logs:
            logs[name] = open(runtime / f'{name}.log', 'a', buffering=1)
        processes[name] = subprocess.Popen(commands[name], cwd=ROOT, stdout=logs[name], stderr=subprocess.STDOUT)
        (runtime / 'processes.json').write_text(json.dumps({k: p.pid for k, p in processes.items()}))
    exit_code = 0
    try:
        for name in commands:
            start(name)
        print(f'SIMULATION running: dashboard port {port}; logs in {runtime}. Ctrl-C to stop.', flush=True)
        while not stopping:
            for name, proc in list(processes.items()):
                if proc.poll() is not None:
                    now = time.monotonic()
                    restarts[name] = [t for t in restarts[name] if now - t < 30]
                    if len(restarts[name]) >= 3:
                        print(f'{name} repeatedly failed; inspect {runtime / (name + ".log")}', file=sys.stderr)
                        stopping, exit_code = True, 1
                        break
                    restarts[name].append(now)
                    print(f'Restarting simulated {name}; a new session must reconcile before control.', flush=True)
                    start(name)
            time.sleep(.1)
    finally:
        for proc in processes.values():
            if proc.poll() is None:
                proc.terminate()
        for proc in processes.values():
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        for f in logs.values():
            f.close()
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
