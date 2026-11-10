"""Quantum Circuit Preparation and Commutativity-Aware Dependency DAG.

This module converts a Qiskit QuantumCircuit into an internal gate sequence and
constructs a Directed Acyclic Graph (DAG) that encodes quantum execution dependencies.

Key Innovation:
Traditional quantum compilers enforce strict sequential program order: if gate B
follows gate A on the same qubit, gate B cannot execute until gate A has settled.
However, if gates A and B commute algebraically ([A, B] = AB - BA = 0), they can be
safely reordered without altering the mathematical unitary transformation or measurement
probabilities.

Commutation Rules Implemented:
1. Z-Basis Commutation: Any two gates diagonal in the computational Z-basis commute:
   [RZ(theta), CZ] = 0, [CZ, CZ] = 0, [RZZ(theta), CZ] = 0, [P, CZ] = 0.
2. X-Basis Commutation: Pure X-type operations on independent bases commute:
   [RX(theta), X] = 0, [SX, X] = 0.
3. Control-Target Independence: A CNOT control is diagonal (Z-type), so it commutes
   with control-side Z-rotations and target-side X-rotations.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple

from qiskit import QuantumCircuit, transpile

# Gate classification by computational action basis
_Z1 = {"z", "s", "sdg", "t", "tdg", "rz", "p", "u1", "id", "i"}
_X1 = {"x", "rx", "sx", "sxdg"}
_ZZ = {"cz", "cp", "cu1", "rzz", "crz", "ccz"}

# Approximate CNOT count equivalents for two-qubit operations
CX_COUNT: Dict[str, int] = {
    "cx": 1,
    "cz": 1,
    "ecr": 1,
    "rzz": 2,
    "cp": 2,
    "swap": 3,
}

# Supported standard basis gates for decomposition
BASIS: List[str] = [
    "u", "rz", "rx", "ry", "x", "sx", "h", "s", "sdg", "t", "tdg", "p",
    "cx", "cz", "cp", "rzz", "swap",
]


def gate_roles(name: str, nq: int) -> Tuple[str, ...]:
    """Determine the commutation operator roles ('z', 'x', or 'o' for other) for each qubit operand.

    Args:
        name: Lowercase gate operation name (e.g., 'rz', 'cx', 'cz').
        nq: Number of qubit operands.

    Returns:
        Tuple of operator role characters ('z', 'x', or 'o') per operand.
    """
    if nq == 1:
        if name in _Z1:
            return ("z",)
        if name in _X1:
            return ("x",)
        return ("o",)
    if name in _ZZ:
        return ("z", "z")
    if name == "cx":
        # Control is Z-diagonal; target is X-type flip
        return ("z", "x")
    if name == "rxx":
        return ("x", "x")
    if name == "rzx":
        return ("z", "x")
    return ("o", "o")


@dataclass(frozen=True)
class Gate:
    """Internal lightweight representation of a scheduled quantum gate.

    Attributes:
        idx: Zero-based unique gate index in circuit topological order.
        name: Gate operator identifier (e.g., 'cx', 'rz').
        qubits: Tuple of logical program qubit indices involved.
        op: Original Qiskit CircuitInstruction / Operation object.
        roles: Commutation role tuple ('z', 'x', 'o') for each operand.
    """
    idx: int
    name: str
    qubits: Tuple[int, ...]
    op: object
    roles: Tuple[str, ...]

    @property
    def is2q(self) -> bool:
        """True if this operation is a two-qubit entangling gate."""
        return len(self.qubits) == 2


def prepare_circuit(circ: QuantumCircuit) -> QuantumCircuit:
    """Normalize input circuit into 1-qubit and 2-qubit basis gates.

    Removes final measurements and decomposes high-level composite gates while
    preserving native multi-qubit entangling operations (e.g., RZZ, CZ, CP) to
    maximize commutation opportunities.

    Args:
        circ: Input arbitrary Qiskit QuantumCircuit.

    Returns:
        Transpiled QuantumCircuit matching the compiler's decomposition basis.
    """
    c = circ.remove_final_measurements(inplace=False)
    return transpile(c, basis_gates=BASIS, optimization_level=0)


class DependencyDAG:
    """Quantum Circuit Dependency Directed Acyclic Graph (DAG).

    When `commutative=True`, dependencies are ONLY enforced between non-commuting
    gates, allowing independent operations to execute out-of-order whenever their
    qubits become physically adjacent on hardware.

    When `commutative=False`, strict sequential per-qubit program order is enforced
    (reproducing traditional quantum compiler behavior for baseline comparison).
    """

    def __init__(self, circ: QuantumCircuit, commutative: bool = True) -> None:
        """Construct gate dependency relationships for the input circuit.

        Args:
            circ: Prepared QuantumCircuit with 1Q and 2Q gates.
            commutative: Whether to relax dependencies using commutation analysis.
        """
        self.n_qubits: int = circ.num_qubits
        self.commutative: bool = commutative
        self.gates: List[Gate] = []

        # Extract gate sequence, skipping non-unitary barriers/delays
        for inst in circ.data:
            op = inst.operation
            if op.name in ("barrier", "measure", "delay"):
                continue
            qs = tuple(circ.find_bit(q).index for q in inst.qubits)
            if len(qs) > 2:
                raise ValueError(
                    f"Gate '{op.name}' has {len(qs)} operands. Call prepare_circuit() first."
                )
            self.gates.append(
                Gate(len(self.gates), op.name, qs, op, gate_roles(op.name, len(qs)))
            )

        n = len(self.gates)
        preds: List[Set[int]] = [set() for _ in range(n)]

        if commutative:
            # Track active commutation role per qubit and group commuting predecessors
            cur_role: List[Optional[str]] = [None] * self.n_qubits
            cur_grp: List[List[int]] = [[] for _ in range(self.n_qubits)]
            prev_grp: List[List[int]] = [[] for _ in range(self.n_qubits)]

            for g in self.gates:
                for q, r in zip(g.qubits, g.roles):
                    if r in "zx" and cur_role[q] == r:
                        # Same commuting axis: gate depends only on previous non-commuting group
                        preds[g.idx].update(prev_grp[q])
                        cur_grp[q].append(g.idx)
                    else:
                        # Non-commuting transition: gate depends on entire current group
                        preds[g.idx].update(cur_grp[q])
                        prev_grp[q], cur_grp[q], cur_role[q] = cur_grp[q], [g.idx], r
        else:
            # Strict per-qubit sequential order
            last_gate: List[Optional[int]] = [None] * self.n_qubits
            for g in self.gates:
                for q in g.qubits:
                    if last_gate[q] is not None:
                        preds[g.idx].add(last_gate[q])
                    last_gate[q] = g.idx

        # Precompute bitmasks for O(1) dependency resolution during search
        self.pred_mask: List[int] = [sum(1 << p for p in ps) for ps in preds]
        self.succ: List[List[int]] = [[] for _ in range(n)]
        for i, ps in enumerate(preds):
            for p in ps:
                self.succ[p].append(i)

        self.preds: List[List[int]] = [sorted(p) for p in preds]
        self.n_gates: int = n
        self.n_2q: int = sum(g.is2q for g in self.gates)

    def initial_frontier(self) -> List[int]:
        """Return indices of all gates ready for execution with zero predecessors."""
        return [i for i in range(self.n_gates) if self.pred_mask[i] == 0]

    def interaction_counts(self) -> Dict[Tuple[int, int], int]:
        """Compute the two-qubit interaction frequencies between all logical qubit pairs.

        Used by greedy placement algorithms to embed dense subgraphs into low-noise hardware.
        """
        weights: Dict[Tuple[int, int], int] = {}
        for g in self.gates:
            if g.is2q:
                k = tuple(sorted(g.qubits))  # type: ignore[assignment]
                weights[k] = weights.get(k, 0) + 1
        return weights


def load_qasm(text: str) -> QuantumCircuit:
    """Load a QuantumCircuit from an OpenQASM 2.0 or 3.0 string.

    Automatically handles version detection and custom gate definitions.

    Args:
        text: OpenQASM source string.

    Returns:
        Parsed Qiskit QuantumCircuit.
    """
    try:
        from qiskit import qasm2
        return qasm2.loads(text, custom_instructions=qasm2.LEGACY_CUSTOM_INSTRUCTIONS)
    except Exception:
        from qiskit import qasm3
        return qasm3.loads(text)
