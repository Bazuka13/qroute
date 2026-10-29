"""Hardware model: coupling graph + per-edge calibration error rates.

Nodes are always relabelled 0..n-1.  `origin[i]` gives the index of node i on the
full device it was cut from (so results can be mapped back to the real chip).
"""
from __future__ import annotations
import heapq
import math
from dataclasses import dataclass, field

import networkx as nx
import numpy as np

TWO_Q_NAMES = ("cx", "ecr", "cz")


@dataclass
class Hardware:
    name: str
    graph: nx.Graph                      # edge attr "error" in [0,1)
    origin: list = field(default_factory=list)
    t1: dict = field(default_factory=dict)   # optional, node -> seconds
    t2: dict = field(default_factory=dict)

    def __post_init__(self):
        g = self.graph
        assert sorted(g.nodes) == list(range(g.number_of_nodes())), "nodes must be 0..n-1"
        if not self.origin:
            self.origin = list(range(g.number_of_nodes()))
        self.n = g.number_of_nodes()
        self.edges = sorted(tuple(sorted(e)) for e in g.edges)
        self._err = {}
        for u, v, d in g.edges(data=True):
            e = min(float(d.get("error", 0.0)), 0.999)
            self._err[(u, v)] = self._err[(v, u)] = e
        self.adj = [set(g.neighbors(i)) for i in range(self.n)]
        lengths = dict(nx.all_pairs_shortest_path_length(g))
        self.dist = np.full((self.n, self.n), 10**6, dtype=np.int64)
        for a, row in lengths.items():
            for b, d in row.items():
                self.dist[a, b] = d

    # --- queries -------------------------------------------------------
    def err(self, u, v):
        return self._err[(u, v)]

    def has_edge(self, u, v):
        return v in self.adj[u]

    def mean_error(self):
        return float(np.mean([self._err[e] for e in self.edges])) if self.edges else 0.0

    # --- sub-regions ---------------------------------------------------
    def best_region(self, size: int) -> "Hardware":
        """Greedy low-noise connected region of `size` qubits (Prim-style growth
        from every start node; best mean induced-edge error wins)."""
        size = min(size, self.n)
        best, best_score = None, math.inf
        for s in range(self.n):
            chosen, heap, seen = {s}, [], {s}
            for w in self.adj[s]:
                heapq.heappush(heap, (self.err(s, w), w))
            while len(chosen) < size and heap:
                _, w = heapq.heappop(heap)
                if w in chosen:
                    continue
                chosen.add(w)
                for x in self.adj[w]:
                    if x not in chosen:
                        heapq.heappush(heap, (self.err(w, x), x))
            if len(chosen) < size:
                continue
            ed = [self.err(a, b) for a, b in self.edges if a in chosen and b in chosen]
            score = np.mean(ed) - 1e-4 * len(ed)       # prefer low noise, then more links
            if score < best_score:
                best, best_score = sorted(chosen), score
        return self.subgraph(best)

    def subgraph(self, nodes) -> "Hardware":
        nodes = sorted(nodes)
        relabel = {o: i for i, o in enumerate(nodes)}
        g = nx.Graph()
        g.add_nodes_from(range(len(nodes)))
        for a, b in self.edges:
            if a in relabel and b in relabel:
                g.add_edge(relabel[a], relabel[b], error=self.err(a, b))
        return Hardware(self.name + f"[{len(nodes)}q]", g, [self.origin[o] for o in nodes],
                        {relabel[o]: self.t1[o] for o in nodes if o in self.t1},
                        {relabel[o]: self.t2[o] for o in nodes if o in self.t2})


# ----------------------------------------------------------------------------
# Synthetic topologies (used when no IBM data is reachable, and for tests)
# ----------------------------------------------------------------------------
def _add_noise(g: nx.Graph, rng, mean_err, hot_frac, hot_mult, sigma=0.5):
    for u, v in g.edges:
        e = mean_err * math.exp(rng.normal(0, sigma))
        if rng.random() < hot_frac:
            e *= hot_mult                      # "bad" coupler
        g[u][v]["error"] = float(min(e, 0.5))
    return g


def heavy_hex(rows=2, cols=2, seed=0, mean_err=0.01, hot_frac=0.15, hot_mult=8.0) -> Hardware:
    """IBM-style heavy-hex lattice = hexagonal lattice with every edge subdivided."""
    base = nx.hexagonal_lattice_graph(rows, cols)
    idx = {n: i for i, n in enumerate(base.nodes)}
    g, nxt = nx.Graph(), len(idx)
    for u, v in base.edges:
        g.add_edge(idx[u], nxt); g.add_edge(nxt, idx[v]); nxt += 1
    rng = np.random.default_rng(seed)
    _add_noise(g, rng, mean_err, hot_frac, hot_mult)
    return Hardware(f"heavy_hex_{rows}x{cols}", g)


def grid(rows=4, cols=4, seed=0, mean_err=0.01, hot_frac=0.15, hot_mult=8.0) -> Hardware:
    g = nx.convert_node_labels_to_integers(nx.grid_2d_graph(rows, cols))
    _add_noise(g, np.random.default_rng(seed), mean_err, hot_frac, hot_mult)
    return Hardware(f"grid_{rows}x{cols}", g)


def line(n=8, seed=0, mean_err=0.01, hot_frac=0.15, hot_mult=8.0) -> Hardware:
    g = nx.path_graph(n)
    _add_noise(g, np.random.default_rng(seed), mean_err, hot_frac, hot_mult)
    return Hardware(f"line_{n}", g)


# ----------------------------------------------------------------------------
# Real IBM calibration data
# ----------------------------------------------------------------------------
def from_backend(backend, name=None) -> Hardware:
    """Build a Hardware from any Qiskit BackendV2 (real or fake) via its Target."""
    target = backend.target
    errs = {}
    for op in target.operation_names:
        if op not in TWO_Q_NAMES:
            continue
        for qargs, props in target[op].items():
            if qargs is None or len(qargs) != 2:
                continue
            e = getattr(props, "error", None)
            e = 0.01 if e is None else float(e)
            key = tuple(sorted(qargs))
            errs[key] = min(errs.get(key, 1.0), e)
    # Some bundled fake snapshots (e.g. FakeKyoto) carry placeholder errors of 1.0.
    bad = [k for k, e in errs.items() if e >= 0.5]
    if errs and len(bad) > 0.5 * len(errs):
        import warnings
        warnings.warn(f"{name or backend.name}: calibration data unusable (placeholder errors); "
                      "using seeded synthetic noise on the real topology")
        rng = np.random.default_rng(0)
        for k in errs:
            e = 0.01 * math.exp(rng.normal(0, 0.5)) * (8.0 if rng.random() < 0.15 else 1.0)
            errs[k] = min(e, 0.5)
    g = nx.Graph()
    g.add_nodes_from(range(target.num_qubits))
    for (a, b), e in errs.items():
        g.add_edge(a, b, error=e)
    t1, t2 = {}, {}
    for i in range(target.num_qubits):
        qp = target.qubit_properties[i] if target.qubit_properties else None
        if qp is not None:
            if qp.t1: t1[i] = qp.t1
            if qp.t2: t2[i] = qp.t2
    return Hardware(name or getattr(backend, "name", "backend"), g, t1=t1, t2=t2)


def load_backend(name: str) -> Hardware:
    """name: 'synthetic', 'fake_brisbane', 'fake_kyoto', ... or a live IBM backend name
    (needs a saved QiskitRuntimeService account)."""
    n = name.lower()
    if n in ("synthetic", "heavy_hex"):
        return heavy_hex(3, 3)
    if n.startswith("fake_"):
        from qiskit_ibm_runtime import fake_provider as fp
        cls = "Fake" + "".join(p.capitalize() for p in n[5:].split("_"))
        return from_backend(getattr(fp, cls)(), name=n)
    from qiskit_ibm_runtime import QiskitRuntimeService
    return from_backend(QiskitRuntimeService().backend(name), name=name)
