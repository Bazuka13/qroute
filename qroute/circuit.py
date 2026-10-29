"""Circuit -> gate list + commutativity-aware dependency DAG (Qiskit integration)."""
from __future__ import annotations
from dataclasses import dataclass, field

from qiskit import QuantumCircuit, transpile

# --- commutation "roles" ------------------------------------------------------
# On every qubit a gate acts as: 'z' (diagonal in Z basis), 'x' (X-type) or 'o' (other).
# Two gates commute if on each shared qubit both are 'z' or both are 'x'
# (sufficient condition; exact for the Pauli-axis gates below).
_Z1 = {"z", "s", "sdg", "t", "tdg", "rz", "p", "u1", "id", "i"}
_X1 = {"x", "rx", "sx", "sxdg"}
_ZZ = {"cz", "cp", "cu1", "rzz", "crz", "ccz"}
CX_COUNT = {"cx": 1, "cz": 1, "ecr": 1, "rzz": 2, "cp": 2, "swap": 3}   # CNOT-equivalents

BASIS = ["u", "rz", "rx", "ry", "x", "sx", "h", "s", "sdg", "t", "tdg", "p",
         "cx", "cz", "cp", "rzz", "swap"]


def gate_roles(name: str, nq: int):
    if nq == 1:
        return ("z",) if name in _Z1 else ("x",) if name in _X1 else ("o",)
    if name in _ZZ:
        return ("z", "z")
    if name == "cx":
        return ("z", "x")
    if name == "rxx":
        return ("x", "x")
    if name == "rzx":
        return ("z", "x")
    return ("o", "o")


@dataclass
class Gate:
    idx: int
    name: str
    qubits: tuple          # logical qubit indices
    op: object             # original qiskit Instruction
    roles: tuple
    @property
    def is2q(self): return len(self.qubits) == 2


def prepare_circuit(circ: QuantumCircuit) -> QuantumCircuit:
    """Decompose to 1- and 2-qubit gates only, keeping commuting gates (rzz/cz/cp) intact."""
    c = circ.remove_final_measurements(inplace=False)
    return transpile(c, basis_gates=BASIS, optimization_level=0)


class DependencyDAG:
    """gate dependency DAG.  commutative=True -> only NON-commuting gate pairs get edges,
    so the routing frontier is much larger (the key pruning idea of the project).
    commutative=False -> strict per-qubit program order (what classic routers use)."""

    def __init__(self, circ: QuantumCircuit, commutative: bool = True):
        self.n_qubits = circ.num_qubits
        self.commutative = commutative
        self.gates: list[Gate] = []
        for inst in circ.data:
            op = inst.operation
            if op.name in ("barrier", "measure", "delay"):
                continue
            qs = tuple(circ.find_bit(q).index for q in inst.qubits)
            if len(qs) > 2:
                raise ValueError(f"gate {op.name} has {len(qs)} qubits; call prepare_circuit() first")
            self.gates.append(Gate(len(self.gates), op.name, qs, op, gate_roles(op.name, len(qs))))
        n = len(self.gates)
        preds = [set() for _ in range(n)]
        if commutative:
            cur_role = [None] * self.n_qubits
            cur_grp = [[] for _ in range(self.n_qubits)]
            prev_grp = [[] for _ in range(self.n_qubits)]
            for g in self.gates:
                for q, r in zip(g.qubits, g.roles):
                    if r in "zx" and cur_role[q] == r:
                        preds[g.idx].update(prev_grp[q]); cur_grp[q].append(g.idx)
                    else:
                        preds[g.idx].update(cur_grp[q])
                        prev_grp[q], cur_grp[q], cur_role[q] = cur_grp[q], [g.idx], r
        else:
            last = [None] * self.n_qubits
            for g in self.gates:
                for q in g.qubits:
                    if last[q] is not None:
                        preds[g.idx].add(last[q])
                    last[q] = g.idx
        self.pred_mask = [sum(1 << p for p in ps) for ps in preds]
        self.succ = [[] for _ in range(n)]
        for i, ps in enumerate(preds):
            for p in ps:
                self.succ[p].append(i)
        self.preds = [sorted(p) for p in preds]
        self.n_gates = n
        self.n_2q = sum(g.is2q for g in self.gates)

    def initial_frontier(self):
        return [i for i in range(self.n_gates) if self.pred_mask[i] == 0]

    def interaction_counts(self):
        w = {}
        for g in self.gates:
            if g.is2q:
                k = tuple(sorted(g.qubits)); w[k] = w.get(k, 0) + 1
        return w


# --- OpenQASM helpers -----------------------------------------------------------
def load_qasm(text: str) -> QuantumCircuit:
    try:
        from qiskit import qasm2
        return qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
    except Exception:
        from qiskit import qasm3
        return qasm3.loads(text)
