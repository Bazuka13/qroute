"""Compare all methods over the benchmark suite.  Usage:
    python run_benchmarks.py --backend synthetic --beta 5 --out results
    python run_benchmarks.py --backend fake_brisbane --fidelity         # real IBM calibration snapshot
"""
import argparse, os
import pandas as pd
from qroute import load_backend, route, METHODS
from qroute.pipeline import build_routed_circuit
from qroute.benchmarks import SUITE
from qroute.hardware import heavy_hex


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default="synthetic")
    ap.add_argument("--beta", type=float, default=5.0)
    ap.add_argument("--weight", type=float, default=1.0, help="weighted-A* factor (>1 = faster, sub-optimal)")
    ap.add_argument("--max-nodes", type=int, default=20000)
    ap.add_argument("--time-limit", type=float, default=30.0)
    ap.add_argument("--fidelity", action="store_true", help="Aer noisy simulation (slower)")
    ap.add_argument("--out", default="results")
    a = ap.parse_args()
    os.makedirs(a.out, exist_ok=True)
    hw = load_backend(a.backend)
    print(f"hardware: {hw.name}  qubits={hw.n}  mean CNOT err={hw.mean_error():.4f}")

    rows = []
    for cname, make in SUITE.items():
        circ = make()
        for m in METHODS:
            res, info = route(circ, hw, m, beta=a.beta, weight=a.weight, max_nodes=a.max_nodes,
                              time_limit=a.time_limit, measure_memory=True)
            row = dict(circuit=cname, method=m, ok=res.success, swaps=res.swaps,
                       noise_cost=round(res.swap_cost, 3), esp=res.esp, expanded=res.nodes_expanded,
                       generated=res.nodes_generated, runtime_s=round(res.runtime, 4),
                       mem_kb=round(res.peak_mem_kb, 1), note=res.note)
            if not res.success:                      # e.g. BFS ran out of budget -> N/A, not 0
                row.update(swaps=None, noise_cost=None, esp=None)
            if a.fidelity and res.success and circ.num_qubits <= 10:
                from qroute.quantum_eval import noisy_fidelity
                row["sim_fidelity"] = noisy_fidelity(info["circ"], build_routed_circuit(res, info),
                                                     res.l2p_final, info["hw"])
            rows.append(row); print(row)
    df = pd.DataFrame(rows)
    df.to_csv(f"{a.out}/results.csv", index=False)
    print(df.pivot_table(index="circuit", columns="method", values="noise_cost").round(2).to_string())

    import matplotlib; matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    metrics = [("noise_cost", "Noise-weighted SWAP cost (lower better)"),
               ("esp", "Estimated success probability (higher better)"),
               ("expanded", "Search nodes expanded (log)"), ("runtime_s", "Runtime [s] (log)")]
    fig, axs = plt.subplots(2, 2, figsize=(13, 8))
    for ax, (col, title) in zip(axs.ravel(), metrics):
        df.pivot(index="circuit", columns="method", values=col)[list(METHODS)].plot.bar(ax=ax, logy=col in ("expanded", "runtime_s"))
        ax.set_title(title); ax.set_xlabel("")
    plt.tight_layout(); plt.savefig(f"{a.out}/comparison.png", dpi=140)
    print(f"saved {a.out}/results.csv and comparison.png")


if __name__ == "__main__":
    main()
