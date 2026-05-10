#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.config import load_config
from cmf_hft_backtester.reporting import write_outputs
from cmf_hft_backtester.simulator import Simulator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/as_microprice.yaml")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-events", type=int, default=None)
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    config = load_config(config_path)
    if args.max_events is not None:
        config.setdefault("data", {})["max_events"] = args.max_events

    simulator = Simulator(config, PROJECT_ROOT)
    result = simulator.run()

    output_dir = args.output_dir or config.get("report", {}).get("output_dir", "outputs/latest")
    output_path = Path(output_dir)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path
    write_outputs(output_path, result.records, result.fills, result.metrics, config)

    print(json.dumps(result.metrics, indent=2, sort_keys=True))
    print(f"Wrote report outputs to {output_path}")


if __name__ == "__main__":
    main()
