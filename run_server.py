#!/usr/bin/env python3
"""Dependency-free demo console for the two GOAI vertical slices."""

from __future__ import annotations

import json
import mimetypes
import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PROJECT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT / "src"))

from goai_control_tower.foundation import PORT_MANIFESTS
from goai_control_tower.configuration import load_config
from goai_control_tower.track1 import replay_provider, run_demo as run_track1
from goai_control_tower.track2 import public_case, run_case
from goai_control_tower.track2_benchmark import run_hidden_benchmark
from goai_control_tower.track2_datasets import load_dataset_catalog
from goai_control_tower.track2_real_data import run_real_data_case


RUNTIME = PROJECT / "runtime_data"
STATIC = PROJECT / "web" / "static"


class Handler(BaseHTTPRequestHandler):
    server_version = "GOAIControlTower/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def serve_static(self, path: str) -> None:
        relative = "index.html" if path == "/" else path.lstrip("/")
        candidate = (STATIC / relative).resolve()
        if STATIC.resolve() not in candidate.parents and candidate != STATIC.resolve():
            self.send_error(404)
            return
        if not candidate.is_file():
            self.send_error(404)
            return
        body = candidate.read_bytes()
        content_type = mimetypes.guess_type(str(candidate))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type + ("; charset=utf-8" if content_type.startswith("text/") or content_type == "application/javascript" else ""))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/health":
            self.send_json({"status": "ok", "runtime": "local-agentteams-conformance", "version": "0.1.0"})
            return
        if parsed.path == "/api/ports":
            self.send_json({"ports": PORT_MANIFESTS})
            return
        if parsed.path == "/api/track1/demo":
            provider = query.get("provider", ["fixture-local"])[0]
            self.send_json(run_track1(RUNTIME, provider_id=provider))
            return
        if parsed.path == "/api/track1/replay":
            provider = query.get("provider", ["scripted-local"])[0]
            self.send_json(replay_provider(provider, RUNTIME))
            return
        if parsed.path == "/api/track2/case":
            case = query.get("case", ["A"])[0].upper()
            self.send_json(public_case(run_case(RUNTIME, case)))
            return
        if parsed.path == "/api/track2/benchmark":
            seed_count = max(1, min(20, int(query.get("seeds", ["8"])[0])))
            seeds = tuple(100 + index * 101 for index in range(seed_count))
            self.send_json(run_hidden_benchmark(seeds=seeds))
            return
        if parsed.path == "/api/track2/datasets":
            self.send_json(load_dataset_catalog())
            return
        if parsed.path == "/api/track2/real-data":
            csv_path = RUNTIME / "datasets" / "uci-bank-marketing" / "data.csv"
            if not csv_path.is_file():
                self.send_json({
                    "error": "真实数据尚未下载",
                    "dataset": "UCI Bank Marketing",
                    "download_command": "python3 -m goai_control_tower --track2-fetch-real-data",
                }, status=404)
                return
            self.send_json(run_real_data_case(RUNTIME, csv_path))
            return
        self.serve_static(parsed.path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GOAI Control Tower console")
    parser.add_argument("port", nargs="?", type=int, help="port override")
    parser.add_argument("--config", type=Path, help="JSON configuration file")
    parser.add_argument("--host", help="host override")
    parser.add_argument("--runtime", help="runtime output directory override")
    args = parser.parse_args()
    config = load_config(args.config)
    global RUNTIME
    RUNTIME = Path(args.runtime or config["runtime"]["output_dir"]).expanduser()
    host = args.host or config["server"]["host"]
    port = args.port if args.port is not None else int(config["server"]["port"])
    server = ThreadingHTTPServer((host, port), Handler)
    print("GOAI Control Tower: http://%s:%d" % (host, port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
