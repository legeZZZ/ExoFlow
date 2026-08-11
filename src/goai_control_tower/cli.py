"""Installed command-line entry point for the runnable GOAI package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .configuration import load_config, resolve_output_dir, validate_evidence_pack
from .track1 import run_demo as run_track1
from .track2 import public_case, run_case
from .track2_benchmark import run_hidden_benchmark
from .track2_datasets import load_dataset_catalog
from .track2_real_data import fetch_bank_marketing_csv, run_real_data_case


def _read_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run GOAI AgentTeams vertical slices")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--output", help="runtime output directory")
    parser.add_argument("--track", choices=["all", "track1", "track2"], default="all")
    parser.add_argument("--provider", default=None, help="Track 1 CodeExecutionPort provider")
    parser.add_argument("--track1-input", help="Track 1 sample input JSON")
    parser.add_argument("--track2-benchmark", action="store_true", help="Run the process-isolated Track 2 hidden benchmark")
    parser.add_argument("--track2-benchmark-seeds", type=int, default=8, help="Number of deterministic hidden benchmark seeds")
    parser.add_argument("--track2-datasets", action="store_true", help="Print the verified public dataset catalog")
    parser.add_argument("--track2-real-data", action="store_true", help="Analyze the cached UCI Bank Marketing history")
    parser.add_argument("--track2-fetch-real-data", action="store_true", help="Download, verify and analyze UCI Bank Marketing")
    parser.add_argument("--track2-real-data-path", type=Path, help="Override the UCI Bank Marketing CSV path")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    output_dir = resolve_output_dir(config, args.output)
    result: Dict[str, Any] = {}

    if args.track in {"all", "track1"}:
        provider = args.provider or config["runtime"]["track1_provider"]
        track1 = run_track1(output_dir, provider_id=provider, input_payload=_read_json(args.track1_input))
        validate_evidence_pack(track1, config)
        result["track1"] = {
            "state": track1["summary"]["final_state"],
            "provider": track1["provider"],
            "hidden_verification": track1["summary"]["hidden_verification"],
            "events": len(track1["trace"]),
            "evidence_pack": track1.get("evidence_pack_path"),
        }

    if args.track in {"all", "track2"}:
        cases = config["runtime"].get("track2_cases", ["A", "B", "C"])
        result["track2"] = {}
        for case in cases:
            public = public_case(run_case(output_dir, case))
            validate_evidence_pack(public, config)
            result["track2"][case] = {
                "state": public["summary"]["final_state"],
                "causal_outcome": public["summary"]["causal_outcome"],
                "claim_type": public["summary"]["claim_type"],
                "evidence_pack": public.get("evidence_pack_path"),
            }
        if args.track2_benchmark:
            seeds = tuple(100 + index * 101 for index in range(max(1, args.track2_benchmark_seeds)))
            result["track2"]["benchmark"] = run_hidden_benchmark(seeds=seeds)

    if args.track2_datasets:
        result["track2_datasets"] = load_dataset_catalog()

    if args.track2_real_data or args.track2_fetch_real_data:
        real_data_path = args.track2_real_data_path or output_dir / "datasets" / "uci-bank-marketing" / "data.csv"
        if args.track2_fetch_real_data:
            fetch_bank_marketing_csv(real_data_path)
        result["track2_real_data"] = run_real_data_case(output_dir, real_data_path)

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
