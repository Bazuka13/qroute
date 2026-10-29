import pytest
from qiskit import QuantumCircuit
from qroute import route, METHODS, heavy_hex, line, DependencyDAG
from qroute.benchmarks import qaoa_maxcut, qft, ghz
from qroute.problem import RoutingProblem


def test_all_methods_valid_on_all_circuits():
    hw = heavy_hex(2, 2, seed=3)
    for c in (qaoa_maxcut(6, 1, 3, 1), qft(5), ghz(6)):
        for m in METHODS:
            res, _ = route(c, hw, m)            # route() verifies legality + unitary internally
            assert res.success


def test_commutation_dag_larger_frontier():
    c = qaoa_maxcut(8, 1, 3, 2)
    strict = DependencyDAG(c, commutative=False)
    comm = DependencyDAG(c, commutative=True)
    assert len(comm.initial_frontier()) >= len(strict.initial_frontier())
    assert len(comm.initial_frontier()) > 1


def test_cx_chain_does_not_commute():
    qc = QuantumCircuit(3); qc.cx(0, 1); qc.cx(1, 2)       # target(0,1)=1 is control of next -> dependent
    d = DependencyDAG(qc)
    assert d.preds[1] == [0]


def test_astar_matches_exhaustive_bfs_when_exact():
    """weight=1, all SWAPs allowed, beta=0 -> A* must equal BFS optimum (admissibility check)."""
    hw = line(5, seed=0)
    qc = QuantumCircuit(5); qc.cx(0, 4); qc.cx(1, 3); qc.cx(0, 2)
    r_bfs, _ = route(qc, hw, "BFS", region=False, placement="trivial")
    r_a, _ = route(qc, hw, "A*-hop", region=False, placement="trivial", restrict_swaps=False)
    assert r_a.swaps == r_bfs.swaps and r_a.optimal


def test_noise_aware_never_worse_in_cost_than_hop_under_same_dag():
    hw = heavy_hex(2, 2, seed=5)
    c = qft(5)
    a, _ = route(c, hw, "A*-hop", beta=10, restrict_swaps=False)
    b, _ = route(c, hw, "A*-noise", beta=10, restrict_swaps=False)
    assert b.swap_cost <= a.swap_cost + 1e-9


def test_heuristic_consistent_on_random_edges():
    hw = heavy_hex(2, 2, seed=1)
    prob = RoutingProblem(hw, DependencyDAG(qft(5), True), beta=3.0)
    from qroute.placement import greedy_placement
    node = prob.initial_node(greedy_placement(prob.dag, hw))
    for _ in range(6):
        if not node.frontier: break
        for u, v in prob.candidates(node):
            child = prob.apply_swap(node, u, v)
            assert prob.h(node) <= prob.swap_cost[(u, v)] + prob.h(child) + 1e-9
        node = prob.apply_swap(node, *prob.candidates(node)[0])
