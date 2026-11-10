"""End-to-End Quantum Compilation and Routing Pipeline.

Provides the unified one-call API:
    result, info = route(circuit, hardware, method="A*-noise+comm", beta=10.0)

Includes registry of baseline and ablation compiler configurations:
- 'A*-noise+comm': Proposed full algorithm (noise-weighted costs + commutativity-aware DAG).
- 'A*-noise': Ablation (noise-weighted costs under strict per-qubit sequential order).
- 'A*-hop': Ablation (unit-cost SWAPs under strict per-qubit sequential order).
- 'Greedy': Local heuristic baseline moving nearest ready gates.
- 'BFS': Uninformed breadth-first search baseline.
"""

from __future__ import annotations
import time
import tracemalloc
from typing import Any, Dict, Optional, Tuple

from qiskit import QuantumCircuit

from .circuit import DependencyDAG, prepare_circuit
from .hardware import Hardware
from .problem import RoutingProblem, evaluate, RouteResult
from .placement import trivial_placement, greedy_placement
from .astar import astar_route
from .baselines import bfs_route, greedy_route
from .verify import check_routing, check_unitary

# Registry of supported methods:
# method_name -> (algorithm_type, commutativity_enabled, noise_aware_enabled)
METHODS: Dict[str, Tuple[str, bool, bool]] = {
    "BFS": ("bfs", False, False),
    "Greedy": ("greedy", False, False),
    "A*-hop": ("astar", False, False),          # Unit-cost SWAPs, strict program order
    "A*-noise": ("astar", False, True),         # Calibration error weighted, strict order
    "A*-noise+comm": ("astar", True, True),     # Full proposed method: noise + commutation
}


def route(
    circ: QuantumCircuit,
    hw: Hardware,
    method: str = "A*-noise+comm",
    *,
    beta: float = 5.0,
    placement: str = "greedy",
    region: bool = True,
    region_slack: int = 2,
    weight: float = 1.0,
    restrict_swaps: bool = True,
    max_nodes: int = 20_000,
    time_limit: float = 30.0,
    gate_weight: float = 0.0,
    record_trace: int = 0,
    verify: bool = True,
    measure_memory: bool = False,
) -> Tuple[RouteResult, Dict[str, Any]]:
    """Compile and route an input quantum circuit onto target hardware coupling constraints.

    Args:
        circ: Input Qiskit QuantumCircuit.
        hw: Target Hardware topology.
        method: Routing algorithm identifier from METHODS registry.
        beta: Noise penalty multiplier (higher beta routes around noisy couplers).
        placement: Initial placement method ('greedy' or 'trivial').
        region: Whether to extract a low-noise sub-region from large hardware.
        region_slack: Extra qubit margin when extracting sub-region.
        weight: Heuristic inflation factor w in f(n) = g(n) + w * h(n).
        restrict_swaps: Prune SWAPs to only those adjacent to active frontier gates.
        max_nodes: Search node expansion limit before greedy fallback.
        time_limit: Search timeout in seconds before greedy fallback.
        gate_weight: Cost penalty factor on scheduled two-qubit gate errors.
        record_trace: Number of search states to log for convergence analysis.
        verify: Assert routing legality and unitary matrix equivalence.
        measure_memory: Measure peak heap allocation in kilobytes.

    Returns:
        Tuple of (RouteResult, info_dict).
        info_dict contains:
            - 'hw': Active Hardware region used.
            - 'dag': Circuit DependencyDAG.
            - 'problem': Initialized RoutingProblem.
            - 'circ': Prepared QuantumCircuit.
            - 'l2p0': Initial logical-to-physical placement tuple.
    """
    if method not in METHODS:
        raise ValueError(f"Unknown routing method '{method}'. Choose from: {list(METHODS.keys())}")

    algo, comm, noisy = METHODS[method]
    prepared = prepare_circuit(circ)

    # Extract lowest-noise connected sub-region if processor is larger than circuit
    target_qubits = prepared.num_qubits + region_slack
    if region and hw.n > target_qubits:
        sub = hw.best_region(target_qubits)
    else:
        sub = hw

    dag = DependencyDAG(prepared, commutative=comm)
    active_beta = beta if noisy else 0.0
    active_gw = gate_weight if noisy else 0.0
    problem = RoutingProblem(sub, dag, beta=active_beta, gate_weight=active_gw)

    placement_fn = greedy_placement if placement == "greedy" else trivial_placement
    l2p0 = placement_fn(dag, sub)

    if measure_memory:
        tracemalloc.start()

    if algo == "bfs":
        res = bfs_route(problem, l2p0, max_nodes=max_nodes, time_limit=time_limit, name=method)
    elif algo == "greedy":
        res = greedy_route(problem, l2p0, name=method)
    else:
        res = astar_route(
            problem,
            l2p0,
            weight=weight,
            restrict_swaps=restrict_swaps,
            max_nodes=max_nodes,
            time_limit=time_limit,
            record_trace=record_trace,
            name=method,
        )

    if measure_memory:
        res.peak_mem_kb = tracemalloc.get_traced_memory()[1] / 1024.0
        tracemalloc.stop()

    if res.success:
        # Evaluate all solutions against a shared benchmark yardstick
        metrics = evaluate(sub, dag, l2p0, res.ops, beta=beta)
        res.swaps = metrics["swaps"]
        res.swap_cost = metrics["swap_cost"]
        res.esp = metrics["esp"]
        res.l2p_final = metrics["l2p_final"]

        if verify:
            check_routing(problem, l2p0, res.ops)
            assert check_unitary(prepared, problem, res.ops), (
                "Unitary equivalence check failed: commutation reordering altered mathematical semantics!"
            )

    return res, {
        "hw": sub,
        "dag": dag,
        "problem": problem,
        "circ": prepared,
        "l2p0": l2p0,
    }


def build_routed_circuit(res: RouteResult, info: Dict[str, Any]) -> QuantumCircuit:
    """Materialize the routed schedule into a physical Qiskit QuantumCircuit.

    Explicitly embeds all inserted SWAP gates and maps logical operations to
    their scheduled physical hardware couplers.

    Args:
        res: RouteResult with scheduled operations.
        info: Info dictionary returned by route().

    Returns:
        Qiskit QuantumCircuit defined on the physical hardware qubits.
    """
    hw: Hardware = info["hw"]
    dag: DependencyDAG = info["dag"]
    qc = QuantumCircuit(hw.n)

    for op in res.ops:
        if op[0] == "swap":
            qc.swap(op[1], op[2])
        else:
            g = dag.gates[op[1]]
            qc.append(g.op, list(op[2]))

    return qc
