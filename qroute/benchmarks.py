"""Benchmark circuits (Qiskit-generated; MQT Bench loader if installed)."""
from __future__ import annotations
import networkx as nx
from qiskit import QuantumCircuit
from qiskit.circuit.library import QFT
from qiskit.circuit.random import random_circuit


def qaoa_maxcut(n=8, p=1, degree=3, seed=0, gamma=0.7, beta=0.4) -> QuantumCircuit:
    """QAOA MaxCut on a random regular graph: commuting RZZ cost layer (commutativity showcase)."""
    g = nx.random_regular_graph(degree, n, seed=seed)
    qc = QuantumCircuit(n)
    qc.h(range(n))
    for _ in range(p):
        for u, v in g.edges:
            qc.rzz(2 * gamma, u, v)
        for q in range(n):
            qc.rx(2 * beta, q)
    return qc


def qft(n=6) -> QuantumCircuit:
    return QFT(n, do_swaps=False).decompose(reps=2)


def ghz(n=8) -> QuantumCircuit:
    qc = QuantumCircuit(n); qc.h(0)
    for i in range(n - 1):
        qc.cx(i, i + 1)
    return qc


def random_cx(n=8, depth=8, seed=0) -> QuantumCircuit:
    return random_circuit(n, depth, max_operands=2, seed=seed)


def mqt(name="dj", n=8, level="alg"):
    """Load from MQT Bench (pip install mqt.bench)."""
    from mqt.bench import get_benchmark
    return get_benchmark(name, level, n)


SUITE = {
    "qaoa_6":  lambda: qaoa_maxcut(6, 1, 3, 1),
    "qaoa_8":  lambda: qaoa_maxcut(8, 1, 3, 2),
    "qaoa_10": lambda: qaoa_maxcut(10, 1, 3, 3),
    "qft_5":   lambda: qft(5),
    "qft_6":   lambda: qft(6),
    "ghz_8":   lambda: ghz(8),
    "rand_8":  lambda: random_cx(8, 6, 1),
}
