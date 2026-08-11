#!/usr/bin/env python3
"""Run both vertical slices and print compact summaries."""

from pathlib import Path
import json
import sys

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))

from goai_control_tower.track1 import run_demo as run_track1
from goai_control_tower.track2 import public_case, run_case


def main() -> None:
    base_dir = PROJECT / "runtime_data"
    track1 = run_track1(base_dir, provider_id="fixture-local")
    cases = {case: public_case(run_case(base_dir, case)) for case in ("A", "B", "C")}
    print(json.dumps({
        "track1": {"state": track1["summary"]["final_state"], "provider": track1["provider"], "hidden_verification": track1["summary"]["hidden_verification"], "events": len(track1["trace"])},
        "track2": {case: {"state": result["summary"]["final_state"], "causal_outcome": result["summary"]["causal_outcome"], "claim_type": result["summary"]["claim_type"]} for case, result in cases.items()},
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
