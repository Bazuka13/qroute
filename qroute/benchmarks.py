"""Standard Quantum Benchmark Circuit Generators.

Provides benchmark suites spanning diverse entanglement topologies:
- Quantum Approximate Optimization Algorithm (QAOA) Max-Cut circuits
- Quantum Fourier Transform (QFT) circuits
- Greenberger-Horne-Zeilinger (GHZ) entangled state circuits
- Randomized entangling two-qubit circuits
- Optional MQT Bench integration
"""

from __future__ import annotations
import networkx as nx
from qiskit import QuantumCircuit
from qiskit.circuit.random import random_circuit


def qaoa_maxcut(
    n: int = 8,
    p: int = 1,
    degree: int = 3,
    seed: int = 0,
    gamma: float = 0.7,
    beta: float = 0.4,
) -> QuantumCircuit:
    """Generate a QAOA Max-Cut circuit on a random regular graph.

    QAOA circuits contain dense layers of commuting two-qubit RZZ interactions,
    making them ideal for benchmarking commutativity-aware dependency relaxation.

    Args:
        n: Number of logical qubits (graph vertices).
        p: Number of QAOA alternating operator steps (circuit depth).
        degree: Degree of each vertex in the regular graph.
        seed: Random seed for deterministic graph generation.
        gamma: Problem Hamiltonian angle parameter.
        beta: Mixer Hamiltonian angle parameter.

    Returns:
        Qiskit QuantumCircuit representing the uncompiled QAOA ansatz.
    """
    g = nx.random_regular_graph(degree, n, seed=seed)
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for _ in range(p):
        for u, v in g.edges:
            qc.rzz(2.0 * gamma, u, v)
        for q in range(n):
            qc.rx(2.0 * beta, q)
    return qc


def qft(n: int = 6) -> QuantumCircuit:
    """Generate a Quantum Fourier Transform (QFT) circuit on n qubits without final SWAPs.

    QFT exhibits an all-to-all cascading entangling topology where every qubit
    must interact with all other qubits via controlled phase rotations.

    Args:
        n: Number of logical qubits.

    Returns:
        Qiskit QuantumCircuit representing the QFT circuit decomposed into 1Q and 2Q gates.
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        from qiskit.circuit.library import QFT
        return QFT(n, do_swaps=False).decompose(reps=2)


def ghz(n: int = 8) -> QuantumCircuit:
    """Generate a Greenberger-Horne-Zeilinger (GHZ) state preparation circuit.

    Prepares the maximally entangled cat state (|00...0> + |11...1>) / sqrt(2)
    using a Hadamard gate followed by a linear cascade of CNOT gates.

    Args:
        n: Number of logical qubits.

    Returns:
        Qiskit QuantumCircuit for GHZ state preparation.
    """
    qc = QuantumCircuit(n)
    qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


def random_cx(n: int = 8, depth: int = 8, seed: int = 0) -> QuantumCircuit:
    """Generate a pseudo-random entangling circuit with single- and two-qubit gates.

    Serves as an unbiased stress test for routing algorithms across non-structured
    entanglement graphs.

    Args:
        n: Number of logical qubits.
        depth: Number of circuit gate layers.
        seed: Random seed for reproducibility.

    Returns:
        Randomized Qiskit QuantumCircuit.
    """
    return random_circuit(n, depth, max_operands=2, seed=seed)


def mqt(name: str = "dj", n: int = 8, level: str = "alg") -> QuantumCircuit:
    """Load an algorithmic benchmark from the Munich Quantum Toolkit (MQT Bench).

    Requires optional dependency: `pip install mqt.bench`

    Args:
        name: Benchmark identifier (e.g., 'dj', 'ghz', 'qft', 'ae').
        n: Number of qubits.
        level: Compilation abstraction level ('alg', 'indep', 'native').

    Returns:
        Qiskit QuantumCircuit loaded from MQT Bench.
    """
    from mqt.bench import get_benchmark
    return get_benchmark(name, level, n)


# Standard benchmark test suite dictionary mapping identifier to circuit factory
SUITE = {
    "qaoa_6": lambda: qaoa_maxcut(6, p=1, degree=3, seed=1),
    "qaoa_8": lambda: qaoa_maxcut(8, p=1, degree=3, seed=2),
    "qaoa_10": lambda: qaoa_maxcut(10, p=1, degree=3, seed=3),
    "qft_5": lambda: qft(5),
    "qft_6": lambda: qft(6),
    "ghz_8": lambda: ghz(8),
    "rand_8": lambda: random_cx(8, depth=6, seed=1),
}
