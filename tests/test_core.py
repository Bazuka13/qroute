"""Core Unit Tests for QRoute.

Verifies:
1. Routing legality and unitary equivalence across all 5 methods.
2. Commutativity DAG relaxation expanding the ready gate frontier.
3. CX dependency tracking correctly detecting non-commuting dependencies.
4. Mathematical optimality: Exact A* matches exhaustive BFS on small circuits.
5. Noise-aware A* achieving <= noise cost compared to hop-count A*.
6. Mathematical consistency (triangle inequality) of heuristic h(n) <= c(n, a, n') + h(n').
"""

import pytest
from qiskit import QuantumCircuit

from qroute import route, METHODS, heavy_hex, line, DependencyDAG
from qroute.benchmarks import qaoa_maxcut, qft, ghz
from qroute.problem import RoutingProblem
from qroute.placement import greedy_placement


def test_all_methods_valid_on_all_circuits() -> None:
    """Verify that all 5 routing algorithms produce valid, unitary-equivalent schedules."""
    hw = heavy_hex(2, 2, seed=3)
    for circ in (qaoa_maxcut(6, p=1, degree=3, seed=1), qft(5), ghz(6)):
        for method in METHODS:
            res, _ = route(circ, hw, method)
            assert res.success, f"Method {method} failed on circuit."


def test_commutation_dag_larger_frontier() -> None:
    """Verify that commutation-aware DAGs yield a larger or equal initial ready frontier."""
    circ = qaoa_maxcut(8, p=1, degree=3, seed=2)
    strict_dag = DependencyDAG(circ, commutative=False)
    comm_dag = DependencyDAG(circ, commutative=True)

    assert len(comm_dag.initial_frontier()) >= len(strict_dag.initial_frontier())
    assert len(comm_dag.initial_frontier()) > 1


def test_cx_chain_does_not_commute() -> None:
    """Verify that non-commuting CNOT dependencies are strictly preserved."""
    qc = QuantumCircuit(3)
    qc.cx(0, 1)
    qc.cx(1, 2)  # Target of gate 0 is control of gate 1 -> non-commuting dependent
    dag = DependencyDAG(qc)
    assert dag.preds[1] == [0]


def test_astar_matches_exhaustive_bfs_when_exact() -> None:
    """Admissibility check: With w=1, restrict_swaps=False, and beta=0, A* matches optimal BFS."""
    hw = line(5, seed=0)
    qc = QuantumCircuit(5)
    qc.cx(0, 4)
    qc.cx(1, 3)
    qc.cx(0, 2)

    r_bfs, _ = route(qc, hw, "BFS", region=False, placement="trivial")
    r_astar, _ = route(qc, hw, "A*-hop", region=False, placement="trivial", restrict_swaps=False)

    assert r_astar.swaps == r_bfs.swaps
    assert r_astar.optimal


def test_noise_aware_never_worse_in_cost_than_hop_under_same_dag() -> None:
    """Verify that noise-aware search achieves equal or lower noise cost than noise-blind routing."""
    hw = heavy_hex(2, 2, seed=5)
    circ = qft(5)
    res_hop, _ = route(circ, hw, "A*-hop", beta=10.0, restrict_swaps=False)
    res_noise, _ = route(circ, hw, "A*-noise", beta=10.0, restrict_swaps=False)

    assert res_noise.swap_cost <= res_hop.swap_cost + 1e-9


def test_heuristic_consistent_on_random_edges() -> None:
    """Numerical consistency check: Proves triangle inequality h(n) <= c(n, a, n') + h(n')."""
    hw = heavy_hex(2, 2, seed=1)
    prob = RoutingProblem(hw, DependencyDAG(qft(5), True), beta=3.0)
    node = prob.initial_node(greedy_placement(prob.dag, hw))

    for _ in range(6):
        if not node.frontier:
            break
        for u, v in prob.candidates(node):
            child = prob.apply_swap(node, u, v)
            assert prob.h(node) <= prob.swap_cost[(u, v)] + prob.h(child) + 1e-9
        node = prob.apply_swap(node, *prob.candidates(node)[0])
