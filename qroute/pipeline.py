"""One-call API:  route(circuit, hardware, method=...)  ->  RouteResult + routed Qiskit circuit."""
from __future__ import annotations
import tracemalloc
from qiskit import QuantumCircuit

from .circuit import DependencyDAG, prepare_circuit
from .hardware import Hardware
from .problem import RoutingProblem, evaluate, RouteResult
from .placement import trivial_placement, greedy_placement
from .astar import astar_route
from .baselines import bfs_route, greedy_route
from .verify import check_routing, check_unitary

# name -> (algorithm, commutativity-aware DAG?, noise-aware cost (beta used in search)?)
METHODS = {
    "BFS":            ("bfs",    False, False),
    "Greedy":         ("greedy", False, False),
    "A*-hop":         ("astar",  False, False),   # classic: strict order, all SWAPs cost 1
    "A*-noise":       ("astar",  False, True),    # + noise-weighted step cost
    "A*-noise+comm":  ("astar",  True,  True),    # + commutativity (full proposal)
}


def route(circ: QuantumCircuit, hw: Hardware, method="A*-noise+comm", *, beta=5.0,
          placement="greedy", region=True, region_slack=2, weight=1.0, restrict_swaps=True,
          max_nodes=20_000, time_limit=30.0, gate_weight=0.0, record_trace=0,
          verify=True, measure_memory=False):
    """Returns (RouteResult, info dict).  info has: hw (region used), dag, problem, circ (prepared),
    routed (QuantumCircuit on region qubits, built lazily via build_routed_circuit)."""
    algo, comm, noisy = METHODS[method]
    prepared = prepare_circuit(circ)
    sub = hw.best_region(prepared.num_qubits + region_slack) if region and hw.n > prepared.num_qubits + region_slack else hw
    dag = DependencyDAG(prepared, commutative=comm)
    problem = RoutingProblem(sub, dag, beta=beta if noisy else 0.0, gate_weight=gate_weight if noisy else 0.0)
    l2p0 = (greedy_placement if placement == "greedy" else trivial_placement)(dag, sub)

    if measure_memory:
        tracemalloc.start()
    if algo == "bfs":
        res = bfs_route(problem, l2p0, max_nodes=max_nodes, time_limit=time_limit, name=method)
    elif algo == "greedy":
        res = greedy_route(problem, l2p0, name=method)
    else:
        res = astar_route(problem, l2p0, weight=weight, restrict_swaps=restrict_swaps,
                          max_nodes=max_nodes, time_limit=time_limit,
                          record_trace=record_trace, name=method)
    if measure_memory:
        res.peak_mem_kb = tracemalloc.get_traced_memory()[1] / 1024
        tracemalloc.stop()

    if res.success:
        m = evaluate(sub, dag, l2p0, res.ops, beta)          # common yardstick (same beta for all)
        res.swaps, res.swap_cost, res.esp, res.l2p_final = m["swaps"], m["swap_cost"], m["esp"], m["l2p_final"]
        if verify:
            check_routing(problem, l2p0, res.ops)
            assert check_unitary(prepared, problem, res.ops), "commutation reordering changed the unitary!"
    return res, dict(hw=sub, dag=dag, problem=problem, circ=prepared, l2p0=l2p0)


def build_routed_circuit(res: RouteResult, info) -> QuantumCircuit:
    """Materialise the schedule as a Qiskit circuit on the physical region (SWAPs explicit)."""
    hw, dag = info["hw"], info["dag"]
    qc = QuantumCircuit(hw.n)
    for op in res.ops:
        if op[0] == "swap":
            qc.swap(op[1], op[2])
        else:
            g = dag.gates[op[1]]
            qc.append(g.op, list(op[2]))
    return qc
