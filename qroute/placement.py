"""Initial placements pi_0."""
from __future__ import annotations
from .hardware import Hardware
from .circuit import DependencyDAG


def trivial_placement(dag: DependencyDAG, hw: Hardware):
    return tuple(range(dag.n_qubits))


def greedy_placement(dag: DependencyDAG, hw: Hardware):
    """Interaction-graph embedding: busiest logical qubit goes to a well-connected low-noise node;
    each next logical qubit goes to the free node closest (by interaction weight) to what is placed."""
    n = dag.n_qubits
    W = dag.interaction_counts()
    deg = [0] * n
    for (a, b), w in W.items():
        deg[a] += w; deg[b] += w
    node_noise = [sum(hw.err(u, v) for v in hw.adj[u]) / max(1, len(hw.adj[u])) for u in range(hw.n)]
    l2p, free = {}, set(range(hw.n))
    order = sorted(range(n), key=lambda q: -deg[q])
    first = order[0]
    l2p[first] = min(free, key=lambda p: (-len(hw.adj[p]), node_noise[p]))
    free.discard(l2p[first])
    remaining = set(order[1:])
    while remaining:
        q = max(remaining, key=lambda x: (sum(w for (a, b), w in W.items()
                                              if (a == x and b in l2p) or (b == x and a in l2p)), deg[x]))
        def score(p):
            s = sum(w * hw.dist[p][l2p[o]] for (a, b), w in W.items()
                    for o in ((b,) if a == q and b in l2p else (a,) if b == q and a in l2p else ()))
            return (s, node_noise[p])
        l2p[q] = min(free, key=score); free.discard(l2p[q]); remaining.discard(q)
    return tuple(l2p[q] for q in range(n))
