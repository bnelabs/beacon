#!/usr/bin/env python3
"""Ground-truth sanity harness for the clearing engine on e-MID networks.

The e-MID interbank transaction dataset (registered research access) is the
closest thing to a measured interbank network in the literature. This script
does NOT download it -- it reads a user-supplied edge-list CSV and runs the
multiplex clearing engine over it, printing the statistics a validation
note needs:

    columns: debtor, creditor, amount   (optional: as_of)

    python scripts/validate_clearing_emid.py edges.csv \
        [--endowment-ratio 0.1] [--shock BANK_ID ...]

Outputs: network size/density, clearing recovery rate, default set, total
shortfall, and (with --shock) the contagion delta per shocked institution.
Comparing these against published e-MID aggregate statistics is a manual,
documented step -- the harness measures, the researcher judges.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.modules.risk.clearing import NetworkLayer, clear_multiplex


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edges", type=Path)
    parser.add_argument("--endowment-ratio", type=float, default=0.1)
    parser.add_argument("--shock", nargs="*", default=[])
    args = parser.parse_args()

    frame = pd.read_csv(args.edges)
    missing = {"debtor", "creditor", "amount"} - set(frame.columns)
    if missing:
        print(f"error: edge list missing columns: {sorted(missing)}", file=sys.stderr)
        return 2

    nodes = sorted(set(frame["debtor"]) | set(frame["creditor"]))
    index = {node: i for i, node in enumerate(nodes)}
    matrix = np.zeros((len(nodes), len(nodes)))
    for row in frame.itertuples(index=False):
        matrix[index[row.debtor], index[row.creditor]] += float(row.amount)

    obligations = matrix.sum(axis=1)
    endowments = obligations * args.endowment_ratio
    layer = NetworkLayer(name="interbank", liabilities=matrix, seniority=0)
    result = clear_multiplex([layer], endowments, node_ids=nodes)

    total_nominal = float(matrix.sum())
    paid = total_nominal - float(result.total_shortfall)
    print(f"network: {len(nodes)} institutions, {int((matrix > 0).sum())} edges, "
          f"density {(matrix > 0).mean():.3f}")
    print(f"baseline clearing: recovery {paid / total_nominal:.4f}, "
          f"defaults {result.n_defaults}, shortfall {result.total_shortfall:.6g}")

    for bank in args.shock:
        if bank not in index:
            print(f"warn: unknown institution {bank!r}, skipped", file=sys.stderr)
            continue
        shocked = endowments.copy()
        shocked[index[bank]] = 0.0
        outcome = clear_multiplex([layer], shocked, node_ids=nodes)
        delta = float(outcome.total_shortfall) - float(result.total_shortfall)
        print(f"shock {bank}: shortfall delta {delta:.6g}, "
              f"defaults {outcome.n_defaults} (baseline {result.n_defaults})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
