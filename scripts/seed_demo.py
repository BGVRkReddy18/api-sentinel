"""Register demo endpoints against a running Sentinel instance.

Usage:  python scripts/seed_demo.py [--api http://localhost:8000] [--target http://demo-target:9000]
"""

import argparse
import os
import sys

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default=os.getenv("SENTINEL_URL", "http://localhost:8000"))
    parser.add_argument("--target", default=os.getenv("DEMO_TARGET_URL", "http://localhost:8000/demo"))
    parser.add_argument("--api-key", default=os.getenv("SENTINEL_API_KEY"))
    args = parser.parse_args()

    endpoints = [
        {"name": "demo-healthy", "url": f"{args.target}/ok", "interval_seconds": 10, "timeout_seconds": 2},
        {"name": "demo-latency-spikes", "url": f"{args.target}/slow", "interval_seconds": 10,
         "timeout_seconds": 3, "max_retries": 1, "max_latency_ms": 1000},
        {"name": "demo-flaky", "url": f"{args.target}/flaky", "interval_seconds": 15,
         "timeout_seconds": 2, "max_retries": 2, "retry_backoff_seconds": 0.5},
        {"name": "demo-orders", "url": f"{args.target}/orders", "interval_seconds": 10,
         "timeout_seconds": 2, "max_retries": 1, "expected_body_contains": "orders", "max_latency_ms": 500},
        {"name": "httpbin-status", "url": "https://httpbin.org/status/200", "interval_seconds": 60},
    ]
    headers = {"X-API-Key": args.api_key} if args.api_key else {}
    with httpx.Client(base_url=args.api, headers=headers, timeout=10) as client:
        for payload in endpoints:
            response = client.post("/api/v1/endpoints", json=payload)
            if response.status_code == 201:
                print(f"created  {payload['name']}")
            elif response.status_code == 409:
                print(f"exists   {payload['name']}")
            else:
                print(f"FAILED   {payload['name']}: {response.status_code} {response.text}", file=sys.stderr)
                return 1
    print(f"\nDashboard: {args.api}/dashboard/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
