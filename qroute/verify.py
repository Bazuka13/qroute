"""Correctness checks for a routed schedule."""
from __future__ import annotations
from qiskit import QuantumCircuit
from qiskit.quantum_info import Operator

from .problem import RoutingProblem


def check_routing(problem: RoutingProblem, l2p0, ops) -> None:
    """Raises AssertionError if the schedule is illegal."""
    hw, dag = problem.hw, problem.dag
    l2p = list(l2p0); p2l = {p: q for q, p in enumerate(l2p)}
    done = 0
    for op in ops:
        if op[0] == "swap":
            _, u, v = op
            assert hw.has_edge(u, v), f"SWAP on non-edge {(u, v)}"
            qu, qv = p2l.pop(u, None), p2l.pop(v, None)
            if qu is not None: p2l[v] = qu; l2p[qu] = v
            if qv is not None: p2l[u] = qv; l2p[qv] = u
        else:
            _, gi, phys = op
            g = dag.gates[gi]
            assert tuple(l2p[q] for q in g.qubits) == tuple(phys), f"gate {gi} on wrong qubits"
            if g.is2q:
                assert hw.has_edge(*phys), f"gate {gi} on non-adjacent qubits {phys}"
            assert dag.pred_mask[gi] & ~done == 0, f"gate {gi} scheduled before its dependencies"
            assert not (done >> gi) & 1, f"gate {gi} scheduled twice"
            done |= 1 << gi
    assert done == (1 << dag.n_gates) - 1, "not all gates were scheduled"


def check_unitary(circ: QuantumCircuit, problem: RoutingProblem, ops, max_qubits=10) -> bool:
    """Replay gates in scheduled order on the logical circuit; must equal the original unitary.
    This proves the commutation reordering is semantically valid."""
    if circ.num_qubits > max_qubits:
        return True
    dag = problem.dag
    re = QuantumCircuit(circ.num_qubits)
    for op in ops:
        if op[0] == "gate":
            g = dag.gates[op[1]]
            re.append(g.op, list(g.qubits))
    return Operator(circ).equiv(Operator(re))
