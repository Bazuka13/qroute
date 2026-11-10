"""Initial Logical-to-Physical Qubit Placement Strategies.

Provides strategies for embedding logical program qubits (q in L) into
physical hardware vertices (p in V_P) before routing begins:
1. Trivial Placement: Direct 1-to-1 index matching (q_i -> P_i).
2. Greedy Interaction-Graph Placement: Analyzes the circuit's two-qubit interaction
   frequency graph and embeds heavily interacting logical qubits into well-connected,
   low-noise hardware clusters.
"""

from __future__ import annotations
from typing import Dict, List, Set, Tuple

from .circuit import DependencyDAG
from .hardware import Hardware


def trivial_placement(dag: DependencyDAG, hw: Hardware) -> Tuple[int, ...]:
    """Map logical qubit q_i directly to physical qubit P_i.

    Args:
        dag: Circuit DependencyDAG.
        hw: Target Hardware topology.

    Returns:
        Tuple where index q corresponds to physical qubit p.
    """
    return tuple(range(dag.n_qubits))


def greedy_placement(dag: DependencyDAG, hw: Hardware) -> Tuple[int, ...]:
    """Greedy Interaction-Graph Placement.

    Analyzes two-qubit gate interaction frequencies:
    1. Computes the weighted degree of each logical qubit.
    2. Places the most heavily interacting logical qubit onto the hardware node with
       highest physical degree and lowest average coupler noise.
    3. Greedily places each subsequent logical qubit onto the available hardware node
       that minimizes weighted hardware distance to already placed interacting qubits.

    Args:
        dag: Circuit DependencyDAG.
        hw: Target Hardware topology.

    Returns:
        Tuple where index q corresponds to physical qubit p.
    """
    n = dag.n_qubits
    weights = dag.interaction_counts()
    degrees = [0] * n
    for (a, b), w in weights.items():
        degrees[a] += w
        degrees[b] += w

    # Calculate mean coupler error per physical qubit
    node_noise: List[float] = [
        sum(hw.err(u, v) for v in hw.adj[u]) / max(1, len(hw.adj[u]))
        for u in range(hw.n)
    ]

    l2p: Dict[int, int] = {}
    free: Set[int] = set(range(hw.n))

    # Order logical qubits by interaction volume
    order = sorted(range(n), key=lambda q: -degrees[q])
    first = order[0]

    # Best initial seed: highest degree, lowest noise
    l2p[first] = min(free, key=lambda p: (-len(hw.adj[p]), node_noise[p]))
    free.discard(l2p[first])

    remaining = set(order[1:])
    while remaining:
        # Choose remaining logical qubit with highest connection to placed qubits
        q = max(
            remaining,
            key=lambda x: (
                sum(
                    w for (a, b), w in weights.items()
                    if (a == x and b in l2p) or (b == x and a in l2p)
                ),
                degrees[x],
            ),
        )

        def score_node(p: int) -> Tuple[float, float]:
            weighted_dist = sum(
                w * hw.dist[p][l2p[o]]
                for (a, b), w in weights.items()
                for o in ((b,) if a == q and b in l2p else (a,) if b == q and a in l2p else ())
            )
            return (weighted_dist, node_noise[p])

        best_phys = min(free, key=score_node)
        l2p[q] = best_phys
        free.discard(best_phys)
        remaining.discard(q)

    return tuple(l2p[q] for q in range(n))
