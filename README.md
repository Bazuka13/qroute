<div align="center">

# ⚛️ QRoute — Noise-Adaptive & Commutativity-Aware A\* Qubit Routing

**Route optimization for quantum circuits using classical AI search algorithms**

*Adani University · Computer Science & Engineering (AI-ML) · ECSCT24301 – Foundation of AI*

[![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)](https://python.org)
[![Qiskit](https://img.shields.io/badge/Qiskit-1.0%2B-6929C4?logo=ibm)](https://qiskit.org)
[![Streamlit](https://img.shields.io/badge/Dashboard-Streamlit-FF4B4B?logo=streamlit)](https://streamlit.io)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

</div>

---

## 📖 Table of Contents

1. [Introduction](#-introduction)
2. [Problem Statement](#-problem-statement)
3. [Architecture Overview](#-architecture-overview)
4. [Algorithms Implemented](#-algorithms-implemented)
5. [Project Structure](#-project-structure)
6. [Environment & PEAS Model](#-environment--peas-model)
7. [Key Concepts](#-key-concepts)
8. [Interactive Dashboard](#-interactive-dashboard)
9. [Benchmark Results](#-benchmark-results)
10. [Installation & Usage](#-installation--usage)
11. [Running Tests](#-running-tests)
12. [Admissibility & Consistency Proof](#-admissibility--consistency-proof)
13. [Team](#-team)
14. [Supervisor](#-supervisor)
15. [References](#-references)

---

## 🌌 Introduction

Quantum computers promise exponential speedups for certain problems — but today's **NISQ (Noisy Intermediate-Scale Quantum)** devices impose strict **physical connectivity constraints**. Two-qubit quantum gates (like CNOT) can only execute between physically adjacent qubits on the chip.

When a quantum program's logical circuit doesn't match the device's coupling topology, a **compiler** must insert **SWAP gates** to physically move qubit states until operands are adjacent. Every inserted SWAP:
- Introduces **3 additional CNOT gates** (3× gate overhead)
- Compounds **decoherence noise** from calibration error rates
- Reduces the overall **circuit fidelity**

**QRoute** solves this challenge using classical AI search — specifically a **noise-adaptive, commutativity-aware A\* algorithm** — to find routing solutions that minimize both the number of SWAPs and their noise impact on real superconducting quantum processors like IBM Brisbane and IBM Kyoto.

---

## 🎯 Problem Statement

> **Given** a logical quantum circuit Q with n qubits and a physical quantum processor H with coupling graph G(V, E), **find** a minimal-cost sequence of SWAP operations that transforms Q into a physically executable circuit Q' such that every two-qubit gate in Q' acts on adjacent physical qubits, while minimizing aggregate calibration error.

### Formal Definition

- **State**: A tuple `(π, G_rem)` where `π: L → P` is the current logical-to-physical qubit mapping and `G_rem` is the set of remaining unexecuted gates in the dependency DAG.
- **Initial State**: `(π₀, G_all)` — initial placement of logical qubits, all gates pending.
- **Goal State**: Any state where `G_rem = ∅` — all gates have been executed.
- **Actions**: Insert a SWAP on any physical coupler `(u, v) ∈ E`, swapping the qubit states of P_u and P_v.
- **Step Cost**: `c(SWAP on (u,v)) = 1 + β · ε(u,v)` where `ε(u,v)` is the two-qubit gate calibration error rate and `β` is the noise penalty weight.
- **Objective**: Minimize the total accumulated cost `Σ c(SWAPs)`.

---

## 🏛️ Architecture Overview

```
┌──────────────────────────────────────────────────────────────────────┐
│                         QRoute Architecture                          │
├──────────────┬──────────────────────────────┬────────────────────────┤
│   INPUT      │        CORE ENGINE           │      OUTPUT            │
│              │                              │                        │
│ Quantum      │  ┌─────────────────────┐    │  Routed Qiskit         │
│ Circuit      │  │  Dependency DAG     │    │  Circuit               │
│ (.qasm /     ├─▶│  (Commutation-aware)│    │                        │
│ Benchmark)   │  └────────┬────────────┘    │  SWAP Sequence         │
│              │           │                 │                        │
│ Hardware     │  ┌────────▼────────────┐    │  Performance           │
│ Topology     ├─▶│  Routing Problem    │    │  Metrics               │
│ (IBM /       │  │  State Space        │    │  (SWAPs, ESP,          │
│ Synthetic)   │  └────────┬────────────┘    │   Cost, Runtime)       │
│              │           │                 │                        │
│ Parameters   │  ┌────────▼────────────┐    │  Interactive           │
│ (β, w,       │  │  Search Algorithm   │    │  Visualization         │
│  max_nodes)  │  │  A* / BFS / Greedy  │    │  (Streamlit)           │
│              │  └─────────────────────┘    │                        │
└──────────────┴──────────────────────────────┴────────────────────────┘
```

### Data Flow

```
Quantum Circuit (OpenQASM / Benchmark)
        │
        ▼
  prepare_circuit()          ← Decomposes to basis gates, extracts qubit count
        │
        ▼
  DependencyDAG()            ← Builds gate dependency graph with commutation rules
        │
        ├──────────────────────────────────────────────────┐
        ▼                                                  ▼
  Hardware.best_region()     ← Selects lowest-noise     Placement()
  (coupling sub-graph)          hardware sub-region     (greedy / trivial)
        │                                                  │
        └──────────────────┬───────────────────────────────┘
                           ▼
              RoutingProblem(sub_hw, dag, β)
                           │
                           ▼
               ┌───────────────────────┐
               │    Route Algorithm    │
               │  ┌─────────────────┐  │
               │  │   A* Search     │  │  ← Priority queue on f(n)=g(n)+w·h(n)
               │  │   BFS           │  │  ← Layer-by-layer uninformed search
               │  │   Greedy        │  │  ← Nearest-gate heuristic
               │  └─────────────────┘  │
               └───────────┬───────────┘
                           │
                           ▼
                    RouteResult
                    (ops, swaps, swap_cost, ESP, runtime, trace)
                           │
                           ├──▶  verify()        ← Unitary equivalence check
                           ├──▶  evaluate()      ← Noise metrics computation
                           └──▶  Streamlit Dashboard
```

---

## 🧠 Algorithms Implemented

### 1. A\* Search — Noise-Adaptive & Commutativity-Aware *(Proposed)*

The full proposal. Evaluation function:

```
f(n) = g(n) + w · h(n)
```

- **`g(n)`** — Accumulated noise-weighted SWAP cost: `Σ (1 + β · ε(u,v))` for each SWAP inserted.
- **`h(n)`** — Admissible lower-bound heuristic: `max over remaining gates g of (dist(l2p[g.q0], l2p[g.q1]) - 1)`.
- **`w`** — Heuristic weight multiplier. `w=1` guarantees optimal cost; `w>1` trades optimality for speed.
- **Commutativity**: Gates that commute (Z-diagonal, X-type, CX control/target roles) can execute out of program order, reducing the effective "remaining" gate set and unlocking more SWAP choices.

### 2. A\* Search — Noise-Aware Only *(Ablation)*

Same A\* with noise-weighted costs but **strict sequential gate order** (no commutation reordering).

### 3. A\* Search — Distance Only / Hop Count *(Ablation)*

Classic A\* with β=0 (all SWAPs cost 1, no noise awareness) and strict gate order.

### 4. Greedy Nearest-Gate Router *(Heuristic Baseline)*

Fast O(n) router: at each step, executes the SWAP that brings the nearest pending two-qubit gate pair one hop closer. No search tree.

### 5. Breadth-First Search *(Uninformed Baseline)*

Layer-by-layer BFS over the routing state space with no heuristic guidance. Optimal for tiny circuits; exponentially slow otherwise.

---

## 📁 Project Structure

```
QA/
├── app.py                      # Streamlit interactive dashboard (main entry point)
├── run_benchmarks.py           # CLI batch benchmark runner → results.csv + plots
├── requirements.txt            # Python dependencies
├── results.csv                 # Pre-computed benchmark results table
├── comparison.png              # Algorithm comparison bar chart
│
├── qroute/                     # Core Python package
│   ├── __init__.py             # Public API: load_backend, route, METHODS, load_qasm
│   ├── hardware.py             # Hardware coupling graph, per-edge errors, IBM loaders, region selection
│   ├── circuit.py              # Circuit preparation, commutation-aware dependency DAG
│   ├── problem.py              # State space: RoutingProblem, SWAP actions, heuristic h, evaluate()
│   ├── astar.py                # Noise-weighted A* search (weighted-A*, node/time budget)
│   ├── baselines.py            # BFS and greedy routing baselines
│   ├── placement.py            # Initial qubit placement: trivial / interaction-graph greedy
│   ├── pipeline.py             # route() one-call API, METHODS registry, build_routed_circuit()
│   ├── verify.py               # Routing legality + unitary equivalence verification
│   ├── quantum_eval.py         # Aer noisy simulation → Hellinger fidelity
│   ├── benchmarks.py           # Standard benchmark circuits: QAOA, QFT, GHZ, random
│   └── visualizer.py           # SVG hardware graph renderer, precomputed replay, matplotlib export
│
└── tests/
    ├── test_core.py            # Correctness, admissibility, consistency unit tests
    └── ...
```

---

## 🤖 Environment & PEAS Model

| Component | Description |
|-----------|-------------|
| **Performance Measure** | Minimize total SWAP count, minimize accumulated calibration noise cost `Σ(1+β·ε)`, maximize Estimated Success Probability (ESP) |
| **Environment** | Physical superconducting quantum processor with a sparse coupling graph; calibration error rates per coupler |
| **Actuators** | Insert SWAP gate on a physical coupler `(u,v)` — exchanges logical qubit states between two adjacent physical qubits |
| **Sensors** | Current logical-to-physical mapping `π`, remaining gate dependency DAG `G_rem`, hardware adjacency and error matrix |

### Environment Properties

| Property | Value |
|----------|-------|
| **Fully Observable** | ✅ Yes — complete mapping and gate set known |
| **Deterministic** | ✅ Yes — SWAP outcome is fully predictable |
| **Static** | ✅ Yes — hardware topology does not change during search |
| **Discrete** | ✅ Yes — finite qubit positions and gate set |
| **Single Agent** | ✅ Yes — one compiler solving the routing problem |
| **Sequential** | ✅ Yes — SWAP ordering matters for final cost |

---

## 💡 Key Concepts

### Physical vs. Logical Qubits

| Concept | Description |
|---------|-------------|
| **Logical Qubit** | A qubit in the programmer's abstract quantum circuit (e.g., `q[0]`) |
| **Physical Qubit** | A real superconducting transmon on the chip (e.g., `P42` on IBM Brisbane) |
| **Mapping π: L → P** | The assignment of logical qubits to physical qubits at any given moment |

### CNOT Error & ESP

- **CNOT Error Rate `ε(u,v)`**: Probability that a two-qubit gate between physical qubits u and v produces an incorrect result due to hardware imperfection. Sourced from IBM calibration data.
- **Estimated Success Probability (ESP)**: `∏ (1 - ε_gate)` over all gates in the routed circuit — approximates the probability of getting the correct measurement.

### Commutativity Rules

Two gates commute and can be reordered if:
- Both are **Z-diagonal** (RZ, CZ, CP, RZZ, …) — they share no X/Y components.
- Both are **X-type** and act on separate qubits.
- One is a **CX control** and the other is a **Z-diagonal** on the same qubit.

Exploiting commutativity allows the router to execute gates out of program order, unlocking additional valid SWAP choices and reducing total cost.

---

## 🖥️ Interactive Dashboard

Launch the full interactive Streamlit dashboard:

```bash
streamlit run app.py
```

### Dashboard Features

| Tab | Description |
|-----|-------------|
| **🔄 Interactive SWAP Replay** | Step-by-step hardware graph animation; scrub through every SWAP with prev/next buttons |
| **📊 Compilation Overview & Topology** | Hardware characteristics, circuit complexity, coupler error distribution chart |
| **🧠 A\* Search Frontier & Heuristics** | Live convergence chart of g(n), h(n), f(n); priority queue size over expansion steps |
| **🔬 Benchmark All 5 Methods** | Side-by-side comparison table of all algorithms on the current circuit |
| **📜 Routed Circuit & OpenQASM** | Full Qiskit circuit diagram and exportable OpenQASM output |
| **📖 Quantum Architecture Guide** | Glossary and educational reference for all quantum routing concepts |

### Sidebar Configuration

- **Hardware Target**: Synthetic (24Q), IBM Brisbane (127Q), IBM Kyoto (127Q)
- **Input Circuit**: 7 pre-built benchmark circuits or upload your own `.qasm` file
- **Algorithm**: All 5 routing methods selectable
- **Advanced Tuning**: Noise penalty β, heuristic weight w, search node budget
- **Optimization Presets**: One-click recommended configurations

---

## 📊 Benchmark Results

All experiments run on the **Synthetic Heavy-Hex (24 qubit)** processor with `β=10`, `w=1.0`, `max_nodes=20000`.

| Circuit | Qubits | Two-Qubit Gates | BFS SWAPs | Greedy SWAPs | A\*-hop SWAPs | A\*-noise SWAPs | **A\*-noise+comm SWAPs** |
|---------|--------|-----------------|-----------|--------------|---------------|-----------------|--------------------------|
| QAOA Max-Cut | 6 | 15 | 12 | 9 | 7 | 6 | **5** |
| QAOA Max-Cut | 8 | 28 | — | 14 | 11 | 9 | **7** |
| QFT | 5 | 10 | 8 | 7 | 5 | 5 | **4** |
| GHZ State | 8 | 7 | 4 | 4 | 3 | 3 | **3** |
| Random 2Q | 8 | 20 | — | 11 | 8 | 7 | **6** |

*BFS marked `—` where node budget was exhausted.*

### Key Findings

- **A\*-noise+comm consistently achieves the lowest SWAP count** across all benchmarks — typically 20–40% fewer SWAPs than the greedy baseline.
- **Commutativity awareness** (comparing A\*-noise+comm vs A\*-noise) provides an additional **1–3 SWAP reduction** by reordering commuting gates.
- **Noise awareness** (comparing A\*-noise vs A\*-hop) reduces calibration-weighted cost by routing around high-error couplers even when SWAP count is equal.
- **Greedy** is fastest but produces 30–60% more SWAPs than the proposed algorithm.

---

## 🚀 Installation & Usage

### Prerequisites

- Python 3.10 or higher
- Git

### Install

```bash
git clone https://github.com/Bazuka13/qroute.git
cd qroute
pip install -r requirements.txt
```

### Quick Start (Python API)

```python
from qroute import load_backend, route
from qroute.benchmarks import SUITE

# Load a quantum hardware backend
hw = load_backend("fake_brisbane")       # or "synthetic", "fake_kyoto"

# Pick a benchmark circuit
circuit = SUITE["qaoa_6"]()              # QAOA Max-Cut on 6 qubits

# Run the proposed noise-adaptive A* router
result, info = route(circuit, hw, "A*-noise+comm", beta=10, weight=1.0)

print(f"Inserted SWAPs     : {result.swaps}")
print(f"Noise-Weighted Cost: {result.swap_cost:.2f}")
print(f"Success Probability: {result.esp * 100:.1f}%")
print(f"States Explored    : {result.nodes_expanded:,}")
print(f"Runtime            : {result.runtime:.3f}s")
```

### Upload Your Own Circuit

```python
from qroute import load_backend, route, load_qasm

hw = load_backend("fake_brisbane")
with open("my_circuit.qasm") as f:
    qasm_str = f.read()

circuit = load_qasm(qasm_str)
result, info = route(circuit, hw, "A*-noise+comm", beta=15)
```

### Run Batch Benchmarks (CLI)

```bash
# Run all 5 algorithms on all circuits, save results + comparison plot
python run_benchmarks.py --backend fake_brisbane --beta 20

# Results saved to results.csv and comparison.png
```

### Launch Dashboard

```bash
streamlit run app.py
```

---

## 🧪 Running Tests

```bash
# Full test suite (correctness + admissibility + consistency checks)
pytest -q tests/

# Individual test file
pytest tests/test_core.py -v
```

Tests verify:
- Routing legality (no gates executed before dependencies are met)
- Unitary equivalence (routed circuit is mathematically identical to the original)
- Heuristic admissibility `h(n) ≤ true_cost(n)` on sampled states
- Heuristic consistency `h(n) ≤ c(n,n') + h(n')` across random transitions

---

## 📐 Admissibility & Consistency Proof

### Heuristic Definition

```
h(n) = max over all remaining gates g of: max(dist_hw(l2p[g.q0], l2p[g.q1]) - 1, 0)
```

Where `dist_hw` is the shortest-path distance on the physical coupling graph.

### Admissibility

A gate `g` at hardware distance `d` requires **at least `d-1` SWAPs** to become adjacent (each SWAP reduces distance by at most 1, and the final SWAP executes the gate simultaneously). Since every SWAP costs `≥ 1`:

```
h(n) = max_g(d_g - 1) ≤ true remaining cost    ✅ Admissible
```

### Consistency (Monotonicity)

After performing one SWAP on coupler `(u,v)`:
- If the farthest gate's distance decreases by 1: `h(n') ≥ h(n) - 1`, so `h(n) ≤ 1 + h(n') ≤ c(n,n') + h(n')` ✅
- If the gate executes (distance was ≤ 2): `h(n) ≤ 1 ≤ c(n,n')` ✅
- If the distance is unchanged: `h(n) = h(n') ≤ c(n,n') + h(n')` ✅

**Conclusion**: The heuristic is both admissible and consistent → A\* with `w=1.0` is guaranteed to find the optimal-cost routing.

> ⚠️ **Note**: With `restrict_swaps=True` (default), only SWAPs touching a frontier qubit are explored — faster but not provably optimal. Use `restrict_swaps=False, weight=1.0` for full optimality guarantee on small circuits.

---

## 📦 Hardware Backends

| Backend ID | Description | Qubits |
|------------|-------------|--------|
| `synthetic` | Heavy-hex lattice with synthetic calibration error hotspots | 24 |
| `fake_brisbane` | IBM Eagle r3 (Brisbane) calibration snapshot | 127 |
| `fake_kyoto` | IBM Eagle (Kyoto) topology with noise profile | 127 |
| `ibm_brisbane` | Live IBM Quantum (requires IBM account) | 127 |

---

## 👥 Team

| Name | Enrollment Number | Role |
|------|-------------------|------|
| **Samarth** | 2410111147 | Algorithm Design, A\* Implementation, Dashboard |
| **Rehan Vahora** | 2410111181 | Benchmarking, Hardware Integration, Testing |
| **Harsh Thakar** | 2410111169 | Circuit Analysis, Visualization, Evaluation |

---

## 👨‍🏫 Supervisor

**Asst. Prof. Dr. Krishna Hingrajiya**  
Department of Computer Science & Engineering (AI-ML)  
Adani University

---

## 📚 References

1. Cowtan, A., et al. (2019). *On the Qubit Routing Problem*. TQC 2019. [arXiv:1902.08091](https://arxiv.org/abs/1902.08091)
2. Li, G., Ding, Y., & Xie, Y. (2019). *Tackling the Qubit Mapping Problem for NISQ-Era Quantum Devices*. ASPLOS 2019.
3. Zulehner, A., Paler, A., & Wille, R. (2018). *An Efficient Methodology for Mapping Quantum Circuits to the IBM QX Architectures*. IEEE TCAD.
4. IBM Quantum (2024). *Qiskit: An Open-source Framework for Quantum Computing*. [qiskit.org](https://qiskit.org)
5. Siraichi, M. Y., et al. (2018). *Qubit Allocation*. CGO 2018.
6. Wille, R., et al. (2019). *Mapping Quantum Circuits to IBM QX Architectures Using the Minimal Number of SWAP and H Operations*. DAC 2019.

---

## 📄 License

This project is released under the [MIT License](LICENSE).

---

<div align="center">

*Built with ❤️ at Adani University · Foundation of AI (ECSCT24301)*

⚛️ **Happy Routing!** ⚛️

</div>
