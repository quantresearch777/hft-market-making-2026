from __future__ import annotations

import argparse
import json
from pathlib import Path


def markdown_cell(source: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": source.splitlines(keepends=True)}


def code_cell(source: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": source.splitlines(keepends=True),
    }


def build_notebook(output_path: Path) -> None:
    cells = [
        markdown_cell(
            """# Task 3: Large Liquidation Reaction Filter

This notebook is the handoff for HW 1 Task 3. It summarizes the EDA, filter implementation, train/validation metrics, and Task 2 baseline comparison.
"""
        ),
        code_cell(
            """from pathlib import Path
import pandas as pd
from IPython.display import Markdown, display, Image

ROOT = Path.cwd().resolve()
if ROOT.name == 'notebooks':
    ROOT = ROOT.parent
elif not (ROOT / 'src').exists() and (ROOT.parent / 'src').exists():
    ROOT = ROOT.parent
REPORTS = ROOT / 'reports'
TABLES = REPORTS / 'tables'
FIGURES = REPORTS / 'figures'
pd.set_option('display.max_columns', 100)
"""
        ),
        markdown_cell("## Assignment Logic\n\nThe filter removes trades after large liquidations when trade side matches liquidation side. Bybit liquidations are shifted by `+200 ms` before matching."),
        code_cell(
            """solution_path = ROOT / 'src' / 'task3_solution.py'
print(solution_path)
print(solution_path.read_text()[:4000])
"""
        ),
        markdown_cell("## Liquidation Thresholds"),
        code_cell(
            """thresholds = pd.read_csv(TABLES / 'task3_liq_thresholds.csv')
thresholds
"""
        ),
        markdown_cell("## Event Study\n\nAverage 30s maker markout from 0 to 300 seconds after large liquidations."),
        code_cell(
            """event_study = pd.read_csv(TABLES / 'task3_event_study.csv')
event_study.head(20)
"""
        ),
        code_cell(
            """for path in sorted(FIGURES.glob('task3_event_study_*.png')):
    print(path.name)
    display(Image(filename=str(path)))
"""
        ),
        markdown_cell("## Train / Validation Metrics"),
        code_cell(
            """summary_path = TABLES / 'task3_final_summary_by_split.csv'
if not summary_path.exists():
    summary_path = TABLES / 'task3_full_grid_summary_by_split.csv'
if not summary_path.exists():
    summary_path = TABLES / 'task3_grid_summary_by_split.csv'
summary = pd.read_csv(summary_path)
summary
"""
        ),
        markdown_cell("## Robustness Checks\n\nFinal strategy stability by split, horizon, symbol, and daily score distribution."),
        code_cell(
            """robustness_path = TABLES / 'task3_final_robustness.csv'
symbol_path = TABLES / 'task3_final_symbol_summary.csv'
if robustness_path.exists():
    robustness = pd.read_csv(robustness_path)
    display(robustness)
else:
    print('Robustness table is not available yet.')

if symbol_path.exists():
    symbol_summary = pd.read_csv(symbol_path)
    display(symbol_summary)
else:
    print('Symbol summary table is not available yet.')
"""
        ),
        markdown_cell("## Experiment Log\n\nAdditional variants were saved instead of overwritten."),
        code_cell(
            """experiment_log = REPORTS / 'experiments' / 'experiment_log.md'
if experiment_log.exists():
    display(Markdown(experiment_log.read_text()))
else:
    print('Experiment log is not available yet.')
"""
        ),
        markdown_cell("## Baseline Comparison"),
        code_cell(
            """baseline_path = TABLES / 'task3_task2_baseline_reference.csv'
if baseline_path.exists():
    baseline = pd.read_csv(baseline_path)
    display(baseline)
else:
    print('Task 2 baseline reference table is not available yet.')
"""
        ),
        markdown_cell("## Final Report"),
        code_cell(
            """report_path = REPORTS / 'task3_report.md'
if report_path.exists():
    display(Markdown(report_path.read_text()))
else:
    print('Report is not available yet.')
"""
        ),
    ]

    nb = {
        "cells": cells,
        "metadata": {
            "kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"},
            "language_info": {"name": "python", "pygments_lexer": "ipython3"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(nb, indent=1), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="notebooks/task3_large_liquidation_reaction_filter.ipynb")
    args = parser.parse_args()
    build_notebook(Path(args.output))


if __name__ == "__main__":
    main()
