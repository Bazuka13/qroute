"""Batch Benchmark Runner and Performance Visualizer.

Executes routing algorithms across the standard benchmark suite, including
QRoute algorithms (A*-noise+comm, A*-noise, A*-hop, Greedy, BFS) and
Qiskit's built-in transpiler routing passes (Qiskit-Sabre, Qiskit-Stochastic, Qiskit-Lookahead).

Measures:
- Circuit Depth
- SWAP Gate Overhead
- Noise-Weighted SWAP Cost (1 + beta * eps)
- Estimated Success Probability (ESP = prod(1 - error))
- Search Nodes Expanded & Generated
- Execution Runtime & Peak Heap Memory

Saves quantitative results to CSV and comparative charts to PNG.

Usage:
    python run_benchmarks.py --backend synthetic --beta 10.0 --out results
    python run_benchmarks.py --backend synthetic --methods A*-noise+comm Qiskit-Sabre Qiskit-Stochastic
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
    parser = argparse.ArgumentParser(description="QRoute: Benchmark routing methods against Qiskit Transpiler.")
    parser.add_argument("--backend", default="synthetic", help="Hardware backend ('synthetic', 'fake_brisbane')")
    parser.add_argument("--beta", type=float, default=10.0, help="Coupler error penalty multiplier beta")
    parser.add_argument("--weight", type=float, default=1.0, help="Weighted-A* factor w")
    parser.add_argument("--max-nodes", type=int, default=20000, help="Search node budget")
    parser.add_argument("--time-limit", type=float, default=30.0, help="Timeout in seconds")
    parser.add_argument("--methods", nargs="*", default=None, help="Subset of methods to benchmark (defaults to all)")
    parser.add_argument("--fidelity", action="store_true", help="Run Aer noisy simulator to compute Hellinger fidelity")
    parser.add_argument("--out", default="results", help="Output directory for CSV and plots")
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    hw = load_backend(args.backend)
    active_methods = args.methods if args.methods else list(METHODS.keys())
    print(f"Target Hardware: {hw.name} | Qubits: {hw.n} | Mean Coupler Error: {hw.mean_error():.4f}")
    print(f"Evaluating Methods: {active_methods}")

    rows: List[Dict[str, Any]] = []
    for cname, make_circuit in SUITE.items():
        circ = make_circuit()
        for method_name in active_methods:
            try:
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
                depth = info.get("depth", 0)
                if depth == 0 and res.success:
                    routed_qc = build_routed_circuit(res, info)
                    depth = routed_qc.depth()

                row: Dict[str, Any] = {
                    "circuit": cname,
                    "method": method_name,
                    "ok": res.success,
                    "swaps": res.swaps,
                    "depth": depth,
                    "noise_cost": round(res.swap_cost, 3),
                    "esp": res.esp,
                    "expanded": res.nodes_expanded,
                    "generated": res.nodes_generated,
                    "runtime_s": round(res.runtime, 4),
                    "mem_kb": round(res.peak_mem_kb, 1),
                    "note": res.note,
                }
                if not res.success:
                    row.update(swaps=None, depth=None, noise_cost=None, esp=None)

                if args.fidelity and res.success and circ.num_qubits <= 10:
                    from qroute.quantum_eval import noisy_fidelity
                    row["sim_fidelity"] = noisy_fidelity(
                        info["circ"],
                        build_routed_circuit(res, info),
                        res.l2p_final,
                        info["hw"],
                    )

                rows.append(row)
                print(
                    f"[{cname:7s}] {method_name:18s} | Success={str(res.success):5s} | "
                    f"SWAPs={str(res.swaps):3s} | Depth={depth:3d} | ESP={res.esp:.4f} | Time={res.runtime:.3f}s"
                )
            except Exception as e:
                print(f"[{cname:7s}] {method_name:18s} | FAILED: {e}")

    df = pd.DataFrame(rows)
    csv_path = os.path.join(args.out, "results.csv")
    df.to_csv(csv_path, index=False)
    print(f"\nSaved benchmark results to {csv_path}")

    # 1. Comprehensive comparative plot
    plot_methods = [m for m in active_methods if m in df["method"].unique()]
    metrics = [
        ("noise_cost", "Noise-Weighted Cost (Lower is Better)"),
        ("esp", "Estimated Success Probability (Higher is Better)"),
        ("depth", "Circuit Depth (Lower is Better)"),
        ("runtime_s", "Execution Runtime [Seconds, Log Scale]"),
    ]
    fig, axs = plt.subplots(2, 2, figsize=(15, 9), dpi=200)
    for ax, (col, title) in zip(axs.ravel(), metrics):
        pivot = df.pivot(index="circuit", columns="method", values=col)[plot_methods]
        pivot.plot.bar(ax=ax, logy=(col == "runtime_s"), rot=15)
        ax.set_title(title, fontweight="bold", fontsize=11)
        ax.set_xlabel("")
        ax.grid(True, linestyle=":", alpha=0.6)
        ax.legend(frameon=True, fontsize=8)

    plt.tight_layout()
    chart_path = os.path.join(args.out, "comparison.png")
    plt.savefig(chart_path)
    print(f"Saved comparative chart to {chart_path}")

    # 2. Focused QRoute vs Qiskit Transpiler Head-to-Head plot
    qiskit_focus = [m for m in ["A*-noise+comm", "Qiskit-Sabre", "Qiskit-Stochastic"] if m in df["method"].unique()]
    if len(qiskit_focus) >= 2:
        fig2, (ax_esp, ax_depth) = plt.subplots(1, 2, figsize=(14, 5), dpi=200)
        
        # ESP comparison
        pivot_esp = df.pivot(index="circuit", columns="method", values="esp")[qiskit_focus]
        pivot_esp.plot.bar(ax=ax_esp, rot=15, color=["#10B981", "#3B82F6", "#8B5CF6"][:len(qiskit_focus)])
        ax_esp.set_title("Fidelity Advantage: Estimated Success Probability (ESP)", fontweight="bold", fontsize=11)
        ax_esp.set_ylabel("ESP (Product of 1 - error)")
        ax_esp.grid(True, linestyle=":", alpha=0.6)
        ax_esp.legend(frameon=True, fontsize=9)

        # Depth comparison
        pivot_depth = df.pivot(index="circuit", columns="method", values="depth")[qiskit_focus]
        pivot_depth.plot.bar(ax=ax_depth, rot=15, color=["#10B981", "#3B82F6", "#8B5CF6"][:len(qiskit_focus)])
        ax_depth.set_title("Depth Reduction: Commutativity DAG Optimization", fontweight="bold", fontsize=11)
        ax_depth.set_ylabel("Circuit Gate Depth (Lower is Better)")
        ax_depth.grid(True, linestyle=":", alpha=0.6)
        ax_depth.legend(frameon=True, fontsize=9)

        plt.tight_layout()
        qiskit_chart_path = os.path.join(args.out, "qiskit_comparison.png")
        plt.savefig(qiskit_chart_path)
        print(f"Saved Qiskit head-to-head comparison chart to {qiskit_chart_path}")


if __name__ == "__main__":
    main()
