"""QRoute: Noise-Adaptive and Commutativity-Aware A* Qubit Routing Engine.

QRoute is a high-performance quantum circuit compilation framework that resolves
two-qubit physical coupling constraints on NISQ (Noisy Intermediate-Scale Quantum)
superconducting quantum processors. It combines:
1. Calibration noise-adaptive cost modeling.
2. Commutativity-aware Directed Acyclic Graph (DAG) dependency relaxation.
3. Admissible and consistent A* heuristic search with priority queue optimization.
4. Interactive step-by-step vector visualization and hardware replay.
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "Samarth"

from .hardware import Hardware, heavy_hex, grid, line, load_backend, from_backend
from .circuit import DependencyDAG, prepare_circuit, load_qasm
from .pipeline import route, build_routed_circuit, METHODS
from .problem import RouteResult, RoutingProblem, Node, evaluate

__all__ = [
    "Hardware",
    "DependencyDAG",
    "prepare_circuit",
    "load_qasm",
    "route",
    "build_routed_circuit",
    "METHODS",
    "RouteResult",
    "RoutingProblem",
    "Node",
    "evaluate",
    "load_backend",
    "heavy_hex",
    "grid",
    "line",
    "from_backend",
]
