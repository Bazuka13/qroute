"""Batch Benchmark Runner and Performance Visualizer.

Executes all 5 routing algorithms across the standard benchmark suite,
measures runtime, memory, SWAP counts, noise cost, and Estimated Success Probability,
and saves quantitative results to CSV and comparative charts to PNG.

Usage:
    python run_benchmarks.py --backend synthetic --beta 10.0 --out results
    python run_benchmarks.py --backend fake_brisbane --fidelity
"""

from __future__ import annotations
import argparse
import os
from typing import Any, Dict, List

import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from qroute import load_backend, route, METHODS
from qroute.pipeline import build_routed_circuit
from qroute.benchmarks import SUITE


def main() -> None:
    parser = argparse.ArgumentParser(description="QRoute: Benchmark all routing methods.")
    parser.add_argument("--backend", default="synthetic", help="Hardware backend ('synthetic', 'fake_brisbane', 'fake_kyoto')")
    parser.add_argument("--beta", type=float, default=10.0, help="Coupler error penalty multiplier beta")
    parser.add_argument("--weight", type=float, default=1.0, help="Weighted-A* factor w (>1 yields faster sub-optimal search)")
    parser.add_argument("--max-nodes", type=int, default=20000, help="Maximum search node expansion budget")
    parser.add_argument("--time-limit", type=float, default=30.0, help="Per-circuit search timeout in seconds")
    parser.add_argument("--fidelity", action="store_true", help="Run Aer noisy simulator to compute Hellinger fidelity")
    parser.add_argument("--out", default="results", help="Output directory for CSV and plots")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    hw = load_backend(args.backend)
    print(f"Target Hardware: {hw.name} | Qubits: {hw.n} | Mean CNOT Error: {hw.mean_error():.4f}")

    rows: List[Dict[str, Any]] = []
    for cname, make_circuit in SUITE.items():
        circ = make_circuit()
        for method_name in METHODS:
            res, info = route(
                circ,
                hw,
                method=method_name,
                beta=args.beta,
                weight=args.weight,
                max_nodes=args.max_nodes,
                time_limit=args.time_limit,
                measure_memory=True,
            )
            row: Dict[str, Any] = {
                "circuit": cname,
                "method": method_name,
                "ok": res.success,
                "swaps": res.swaps,
                "noise_cost": round(res.swap_cost, 3),
                "esp": res.esp,
                "expanded": res.nodes_expanded,
                "generated": res.nodes_generated,
                "runtime_s": round(res.runtime, 4),
                "mem_kb": round(res.peak_mem_kb, 1),
                "note": res.note,
            }
            if not res.success:
                row.update(swaps=None, noise_cost=None, esp=None)

            if args.fidelity and res.success and circ.num_qubits <= 10:
                from qroute.quantum_eval import noisy_fidelity
                row["sim_fidelity"] = noisy_fidelity(
                    info["circ"],
                    build_routed_circuit(res, info),
                    res.l2p_final,
                    info["hw"],
                )

            rows.append(row)
            print(f"[{cname}] {method_name:15s} | Success={str(res.success):5s} | SWAPs={str(res.swaps):4s} | Runtime={res.runtime:.3f}s")

    df = pd.DataFrame(rows)
    csv_path = os.path.join(args.out, "results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nSaved benchmark results to {csv_path}")

    # Generate comparative bar plots
    metrics = [
        ("noise_cost", "Noise-Weighted SWAP Cost (Lower is Better)"),
        ("esp", "Estimated Success Probability (Higher is Better)"),
        ("expanded", "Search Nodes Expanded [Log Scale]"),
        ("runtime_s", "Execution Runtime [Seconds, Log Scale]"),
    ]
    fig, axs = plt.subplots(2, 2, figsize=(14, 8), dpi=200)
    for ax, (col, title) in zip(axs.ravel(), metrics):
        pivot = df.pivot(index="circuit", columns="method", values=col)[list(METHODS.keys())]
        pivot.plot.bar(ax=ax, logy=(col in ("expanded", "runtime_s")), rot=15)
        ax.set_title(title, fontweight="bold", fontsize=11)
        ax.set_xlabel("")
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend(frameon=True, fontsize=8)

    plt.tight_layout()
    chart_path = os.path.join(args.out, "comparison.png")
    plt.savefig(chart_path)
    print(f"Saved comparative chart to {chart_path}")


if __name__ == "__main__":
    main()
