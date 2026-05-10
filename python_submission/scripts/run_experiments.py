#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.config import load_config
from cmf_hft_backtester.reporting import write_comparison_outputs, write_outputs
from cmf_hft_backtester.simulator import Simulator


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--configs",
        nargs="+",
        default=[
            "configs/fixed_spread.yaml",
            "configs/as_mid.yaml",
            "configs/as_microprice.yaml",
            "configs/as_obi_hybrid.yaml",
            "configs/as_ewma_vol.yaml",
        ],
    )
    parser.add_argument("--output-dir", default="outputs/experiments")
    parser.add_argument("--max-events", type=int, default=None)
    args = parser.parse_args()

    out_root = Path(args.output_dir)
    if not out_root.is_absolute():
        out_root = PROJECT_ROOT / out_root
    out_root.mkdir(parents=True, exist_ok=True)

    comparison_results = {}
    for cfg in args.configs:
        cfg_path = Path(cfg)
        if not cfg_path.is_absolute():
            cfg_path = PROJECT_ROOT / cfg_path
        config = load_config(cfg_path)
        if args.max_events is not None:
            config.setdefault("data", {})["max_events"] = args.max_events
        strategy_name = config.get("strategy", {}).get("name", cfg_path.stem)
        run_dir = out_root / strategy_name
        result = Simulator(config, PROJECT_ROOT).run()
        write_outputs(run_dir, result.records, result.fills, result.metrics, config)
        comparison_results[strategy_name] = (result.records, result.metrics)
        print(f"{strategy_name}: pnl={result.metrics['final_pnl']:.8f}, fills={result.metrics['num_fills']}")

    write_comparison_outputs(out_root, comparison_results)
    print(f"Wrote comparison to {out_root / 'comparison.csv'}")
    print(f"Wrote comparison report to {out_root / 'comparison.md'}")


if __name__ == "__main__":
    main()
