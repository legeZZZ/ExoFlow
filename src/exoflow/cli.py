"""Installed command-line entry point for the ExoFlow package."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

from .configuration import load_config, resolve_output_dir, validate_evidence_pack
from .pipeline import run_demo


def _read_json(path: Optional[str]) -> Optional[Dict[str, Any]]:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ExoFlow incident-fix pipeline")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--output", help="runtime output directory")
    parser.add_argument("--provider", default=None, help="CodeExecutionPort provider")
    parser.add_argument("--input", help="sample input JSON")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    config = load_config(args.config)
    output_dir = resolve_output_dir(config, args.output)

    pack = run_demo(
        output_dir,
        provider_id=args.provider or config["runtime"]["provider"],
        input_payload=_read_json(args.input),
    )
    validate_evidence_pack(pack, config)
    result: Dict[str, Any] = {
        "state": pack["summary"]["final_state"],
        "provider": pack["provider"],
        "hidden_verification": pack["summary"]["hidden_verification"],
        "events": len(pack["trace"]),
        "evidence_pack": pack.get("evidence_pack_path"),
    }

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0
