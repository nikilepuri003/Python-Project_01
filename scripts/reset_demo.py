"""Reset the in-memory incident store for a fresh demo run."""

from __future__ import annotations

import argparse
import json

import httpx


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the CodePulse incident store.")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    args = parser.parse_args()

    with httpx.Client() as client:
        response = client.post(f"{args.base_url}/api/v1/incidents/reset", timeout=30.0)
        response.raise_for_status()
        print(json.dumps(response.json(), indent=2))


if __name__ == "__main__":
    main()
