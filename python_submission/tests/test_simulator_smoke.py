import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from cmf_hft_backtester.simulator import Simulator


class TestSimulatorSmoke(unittest.TestCase):
    def test_sample_cmf_run_produces_metrics(self):
        config = {
            "data": {
                "source": "cmf",
                "data_dir": "data/sample",
                "levels": 5,
                "max_events": 500,
                "max_lob_rows": 500,
                "max_trade_rows": 500,
            },
            "market": {"tick_size": 0.0000001, "maker_fee_bps": 0.0},
            "simulation": {
                "quote_interval_ns": 100_000_000,
                "record_interval_ns": 1_000_000_000,
                "partial_fills": True,
                "use_trade_events": True,
            },
            "risk": {"order_qty": 5000.0, "max_inventory": 50000.0},
            "strategy": {
                "name": "avellaneda_stoikov_microprice",
                "gamma": 0.05,
                "k": 200000.0,
                "tau_seconds": 60.0,
            },
        }
        result = Simulator(config, PROJECT_ROOT).run()
        self.assertGreater(result.metrics["processed_events"], 0)
        self.assertIn("final_pnl", result.metrics)


if __name__ == "__main__":
    unittest.main()
