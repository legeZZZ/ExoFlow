#!/usr/bin/env python3
"""Run the incident-fix fixture demo and print a compact summary."""

from pathlib import Path
import json
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))

from exoflow.pipeline import run_demo


def main() -> None:
    pack = run_demo(PROJECT / "runtime_data", provider_id="fixture-local")
    print(json.dumps({
        "state": pack["summary"]["final_state"],
        "provider": pack["provider"],
        "hidden_verification": pack["summary"]["hidden_verification"],
        "events": len(pack["trace"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
