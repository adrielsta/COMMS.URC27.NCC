#!/usr/bin/env python3
"""Read simulation telemetry and demonstrate an acknowledged rover STOP.

Run ./scripts/start.sh first. This program never requests vehicle motion.
"""

import argparse
import json
import time
import urllib.error
import urllib.request


def request(url, path, body=None, token=None):
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["X-CSRF-Token"] = token
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=None if body is None else json.dumps(body).encode(),
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=3) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()
    try:
        state = request(args.url, "/api/state")
        print(json.dumps({"vehicles": state["vehicles"]}, indent=2))
        command = request(
            args.url,
            "/api/command",
            {"vehicle": "rover", "action": "STOP", "args": {}},
            state["csrf_token"],
        )
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            state = request(args.url, "/api/state")
            record = next(
                (item for item in state["commands"] if item["id"] == command["id"]),
                None,
            )
            if record and record["status"] in {"completed", "rejected", "timeout"}:
                print(json.dumps({"command": record}, indent=2))
                return 0 if record["status"] == "completed" else 1
            time.sleep(0.1)
        parser.exit(1, "STOP acknowledgement did not arrive before the demo deadline.\n")
    except (OSError, ValueError, KeyError, urllib.error.HTTPError) as error:
        parser.exit(1, f"Demo failed: {error}. Start ./scripts/start.sh first.\n")


if __name__ == "__main__":
    raise SystemExit(main())
